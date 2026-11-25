"""Flujo de revisión y distribución. El agente PREPARA el informe; una PERSONA (Felipe Guerrero) lo aprueba o lo rechaza con comentarios.
Rechazo → nueva versión que responde a los comentarios. Distribución SOLO tras la aprobación y SOLO a los destinatarios del briefing."""
from __future__ import annotations

import json
from pathlib import Path

from . import config, ingest as ingest_mod, report as report_mod
from .agent import FinancialCloseAgent
from .sensitive import clean
from .store import CloseStore, DataStore, now


class WorkflowError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


class CloseEngine:
    def __init__(self, data: DataStore, close: CloseStore):
        self.data, self.close = data, close

    # --------------------------------------------------------------- ingesta + cierre
    def load_period(self, source_dir: str | Path, period: str) -> dict:
        self.close.event("automated_process", config.AGENT_ID, "ingest", period, {})
        return ingest_mod.ingest(self.data, Path(source_dir), period)

    def _records(self, period: str) -> dict:
        rows = self.data.readonly_query("SELECT * FROM records WHERE period=? AND kind='ledger' AND status='valid' ORDER BY row", (period,))
        out: dict = {}
        for r in rows:
            out.setdefault((r["country"], r["category"]), []).append(r)
        return out

    def _prepare(self, period: str, version: int, comments: list[str] | None = None, based_on: int | None = None) -> dict:
        rep = FinancialCloseAgent(self.data, self.close).close_period(period)
        if comments:
            rep["revision"] = report_mod.response_to_comments(rep, comments, self._records(period))
        md = report_mod.render(rep, version, "pending_review")
        rid = self.close.run("INSERT INTO reports(period,version,status,content,content_hash,markdown,created_at,based_on_review) VALUES(?,?,?,?,?,?,?,?)",
                             (period, version, "pending_review", json.dumps(rep, ensure_ascii=False), rep["content_hash"], clean(md), now(), based_on))
        self.close.event("automated_process", config.AGENT_ID, "report_created", f"{period}:v{version}", {"report_id": rid, "hash": rep["content_hash"]})
        self.close.message("review_request", config.REVIEWER_ID, rid, f"Cierre {period} v{version}: pendiente de tu revisión",
                           "El informe está listo para revisión. No se distribuirá hasta que lo apruebes.\n\n" + "\n".join(rep["summary"]))
        return self.get(rid)

    def run_close(self, period: str, actor: str = config.AGENT_ID) -> dict:
        """Genera la v1 del periodo. Idempotente: si ya hay informe del periodo, devuelve el vigente."""
        cur = self.latest(period)
        if cur:
            return cur
        return self._prepare(period, 1)

    def run_scheduled(self, period: str, when, source_dir=None) -> dict:
        if self.close.one("SELECT 1 AS x FROM schedule_runs WHERE period=?", (period,)):
            return {"ran": False, "period": period, "reason": "periodo ya lanzado"}
        self.close.event("automated_process", "scheduler", "scheduled_run", period, {"due": when.isoformat()})
        if source_dir:
            self.load_period(source_dir, period)
        rep = self.run_close(period)
        self.close.run("INSERT INTO schedule_runs(period,started_at,report_id) VALUES(?,?,?)", (period, now(), rep["id"]))
        return {"ran": True, "period": period, "report_id": rep["id"]}

    # --------------------------------------------------------------- consulta
    def latest(self, period: str) -> dict | None:
        r = self.close.one("SELECT id FROM reports WHERE period=? ORDER BY version DESC LIMIT 1", (period,))
        return self.get(r["id"]) if r else None

    def get(self, report_id: int) -> dict:
        r = self.close.one("SELECT * FROM reports WHERE id=?", (report_id,))
        if not r:
            raise WorkflowError("informe no encontrado", 404)
        r["content"] = json.loads(r["content"])
        r["reviews"] = self.close.q("SELECT * FROM reviews WHERE report_id=? ORDER BY id", (report_id,))
        return r

    def list_reports(self) -> list[dict]:
        return self.close.q("SELECT id,period,version,status,content_hash,created_at,decided_at,distributed_at FROM reports ORDER BY period DESC, version DESC")

    def can_view(self, report: dict, staff: dict) -> bool:
        """Pendiente o rechazado: solo el revisor. Aprobado/distribuido: los destinatarios del briefing."""
        if report["status"] in ("pending_review", "rejected"):
            return staff["id"] == config.REVIEWER_ID
        return staff["id"] in config.RECIPIENT_IDS

    def figure(self, report_id: int, figure_id: str) -> dict:
        f = self.get(report_id)["content"]["figures"].get(figure_id)
        if not f:
            raise WorkflowError("cifra no encontrada", 404)
        recs = []
        for s in f["sources"]:
            row = self.data.readonly_query("SELECT file,row,entry_id,date,country,category,currency,amount,description,source_ref,metric,status FROM records WHERE file=? AND row=?", (s["file"], s["row"]))
            recs += row
        f = dict(f)
        f["records"] = recs
        return f

    # --------------------------------------------------------------- revisión
    def review(self, report_id: int, staff: dict, decision: str, comment: str = "") -> dict:
        if staff["id"] != config.REVIEWER_ID:
            raise WorkflowError("solo el revisor designado (Felipe Guerrero) puede aprobar o rechazar", 403)
        rep = self.get(report_id)
        if rep["status"] != "pending_review":
            raise WorkflowError(f"el informe está en estado «{rep['status']}»; solo se revisa uno pendiente", 409)
        if decision not in ("approve", "reject"):
            raise WorkflowError("decisión inválida: approve | reject")
        comment = clean(comment or "").strip()
        if decision == "reject" and not comment:
            raise WorkflowError("un rechazo requiere comentarios")
        rid = self.close.run("INSERT INTO reviews(report_id,staff_id,decision,comment,ts) VALUES(?,?,?,?,?)", (report_id, staff["id"], decision, comment, now()))
        self.close.event("user", staff["id"], f"review_{decision}", f"{rep['period']}:v{rep['version']}", {"report_id": report_id, "comment_chars": len(comment)})
        if decision == "approve":
            self.close.run("UPDATE reports SET status='approved', decided_at=? WHERE id=?", (now(), report_id))
            return self.distribute(report_id)
        self.close.run("UPDATE reports SET status='rejected', decided_at=? WHERE id=?", (now(), report_id))
        comments = [c.strip() for c in comment.replace("\r", "").split("\n") if c.strip()]
        return self._prepare(rep["period"], rep["version"] + 1, comments, rid)

    # --------------------------------------------------------------- distribución
    def distribute(self, report_id: int) -> dict:
        rep = self.get(report_id)
        if rep["status"] == "distributed":
            return rep                                    # idempotente: no se reenvía
        if rep["status"] != "approved":
            raise WorkflowError("no se distribuye sin aprobación", 409)
        for sid in config.RECIPIENT_IDS:
            self.close.message("distribution", sid, report_id, f"Cierre financiero {rep['period']} (v{rep['version']}, aprobado por Operaciones)", rep["markdown"])
        self.close.run("UPDATE reports SET status='distributed', distributed_at=? WHERE id=?", (now(), report_id))
        self.close.event("automated_process", config.AGENT_ID, "distributed", f"{rep['period']}:v{rep['version']}", {"recipients": len(config.RECIPIENT_IDS)})
        return self.get(report_id)
