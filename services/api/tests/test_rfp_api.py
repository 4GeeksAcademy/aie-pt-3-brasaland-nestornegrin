"""API de RFPs (Hito 9 · Partes 1 y 2) sobre SQLite en memoria y un modelo simulado.

TestClient ejecuta las BackgroundTasks al terminar la petición, así que tras el POST el pipeline ya corrió.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tests" / "pipelines"))
from rfp_support import PDF_FORMAL, PDF_INFORMAL, PDF_INVALID, ScriptedRfpModel  # noqa: E402
from rfp_response_support import BAD_SLA, ScriptedResponseModel  # noqa: E402

from app.auth.dependencies import get_current_user  # noqa: E402
from app.database import get_db  # noqa: E402
from app.rfp import models  # noqa: E402,F401
from app.rfp import repository  # noqa: E402
from app.rfp.repository import SqlRfpStore  # noqa: E402
from app.rfp.routes import create_router  # noqa: E402


class CombinedModel:
    """Un solo modelo simulado para las dos partes: los prompts de la Parte 2 van al guion de la Parte 2."""

    def __init__(self):
        self.part1, self.part2 = ScriptedRfpModel(), ScriptedResponseModel()

    @property
    def overrides(self):
        return self.part1.overrides

    def __call__(self, messages):
        system = messages[0]["content"]
        part2 = system.startswith(("Eres el agente GENERADOR", "Eres el agente EVALUADOR"))
        return (self.part2 if part2 else self.part1)(messages)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RFP_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("RFP_AUTO_GENERATE", "0")  # los tests de la Parte 1 se detienen en analisis_completo; los de la Parte 2 lo activan
    # SQLite en archivo (una conexión por hilo): los workers del grafo corren en paralelo y una conexión compartida no es segura.
    engine = create_engine(f"sqlite:///{tmp_path / 'rfp.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    model = CombinedModel()
    app = FastAPI()
    app.include_router(create_router(store_factory=lambda: SqlRfpStore(lambda: Session(engine)), llm=model))
    app.dependency_overrides[get_current_user] = lambda: {"email": "camila@brasaland.test"}
    app.dependency_overrides[get_db] = lambda: Session(engine)
    return TestClient(app), engine, model, tmp_path


def upload(client, pdf: Path, name: str | None = None):
    return client.post("/rfp/tickets", files={"file": (name or pdf.name, pdf.read_bytes(), "application/pdf")})


def test_upload_returns_202_saves_pdf_under_raw_and_persists_everything_in_the_database(env):
    client, engine, _, tmp = env
    response = upload(client, PDF_FORMAL)
    assert response.status_code == 202 and response.json() == {"ticket_id": 1, "status": "analizando"}
    saved = list((tmp / "raw").glob("*.pdf"))
    assert len(saved) == 1 and saved[0].read_bytes().startswith(b"%PDF-")
    detail = client.get("/rfp/tickets/1").json()
    assert detail["status"] == "analisis_completo" and detail["rfp_id"] == "SBR-2026-0417" and detail["processing"] == "idle"
    assert detail["metadata"]["client_name"] == "Sunset Bay Resorts, LLC" and detail["metadata"]["budget_usd_max"] == 75000
    assert detail["readability"]["word_count"] > 100
    assert [s["department_id"] for s in detail["sections"]] == ["marketing", "operaciones", "procurement", "training"]
    assert {s["department_id"]: s["owner"] for s in detail["sections"]}["training"] == "Jake Morrison"
    assert detail["handoff"]["ticket_id"] == 1 and detail["handoff"]["ready_for_part_2"] is True
    with Session(engine) as s:  # persistido en tablas, no en archivos
        assert repository.get_metadata(s, 1).client_name == "Sunset Bay Resorts, LLC"
        assert len(repository.get_sections(s, 1)) == 4 and repository.get_sections(s, 1)[0].approval_status == "pendiente"
        assert repository.get_ticket(s, 1).uploaded_by == "camila@brasaland.test"


def test_informal_is_accepted_and_invalid_is_discarded_through_the_api(env):
    client, _, _, _ = env
    assert upload(client, PDF_INFORMAL).status_code == 202
    assert upload(client, PDF_INVALID).status_code == 202
    ok, bad = client.get("/rfp/tickets/1").json(), client.get("/rfp/tickets/2").json()
    assert ok["status"] == "analisis_completo" and [s["department_id"] for s in ok["sections"]] == ["marketing", "operaciones", "procurement"]
    assert bad["status"] == "descartado" and "Faltan" in bad["discard_reason"] and bad["sections"] == [] and bad["handoff"] is None
    listing = client.get("/rfp/tickets").json()
    assert [t["ticket_id"] for t in listing] == [2, 1] and listing[1]["client_name"] == "Andes Tech Solutions"


@pytest.mark.parametrize("name,content,status", [
    ("rfp.txt", b"%PDF-1.4 x", 415), ("rfp.pdf", b"", 400), ("rfp.pdf", b"esto no es pdf", 415), ("rfp.pdf", b"%PDF-" + b"0" * (10 * 1024 * 1024 + 1), 413)])
def test_invalid_uploads_are_rejected_before_creating_a_ticket(env, name, content, status):
    client, engine, _, tmp = env
    assert client.post("/rfp/tickets", files={"file": (name, content, "application/pdf")}).status_code == status
    assert client.get("/rfp/tickets").json() == [] and not list((tmp / "raw").glob("*"))


def test_hostile_filename_cannot_escape_the_raw_directory(env):
    client, _, _, tmp = env
    assert upload(client, PDF_FORMAL, "../../etc/pass wd.pdf").status_code == 202
    saved = list((tmp / "raw").iterdir())
    assert len(saved) == 1 and saved[0].parent == tmp / "raw" and ".." not in saved[0].name


def test_unknown_ticket_is_404(env):
    client, *_ = env
    assert client.get("/rfp/tickets/99").status_code == 404 and client.post("/rfp/tickets/99/reprocess").status_code == 404


def test_failed_ticket_is_visible_as_failed_and_can_be_reprocessed(env):
    client, _, model, _ = env
    model.overrides["orchestrator"] = lambda m: (_ for _ in ()).throw(RuntimeError("caída del proveedor"))
    upload(client, PDF_FORMAL)
    failed = client.get("/rfp/tickets/1").json()
    assert failed["status"] == "analizando" and failed["processing"] == "failed" and "caída del proveedor" in failed["processing_error"]
    del model.overrides["orchestrator"]
    assert client.post("/rfp/tickets/1/reprocess").status_code == 202
    done = client.get("/rfp/tickets/1").json()
    assert done["status"] == "analisis_completo" and done["processing_error"] is None and done["attempts"] == 2
    assert client.post("/rfp/tickets/1/reprocess").status_code == 409  # ya completo


def test_a_ticket_whose_heartbeat_stopped_is_shown_as_stalled_and_a_running_one_cannot_be_restarted(env):
    client, engine, _, _ = env
    with Session(engine) as s:
        t = repository.create_ticket(s, raw_pdf_path=str(PDF_FORMAL), original_filename="x.pdf", uploaded_by=None)
        assert client.get(f"/rfp/tickets/{t.ticket_id}").json()["processing"] == "running"
        assert client.post(f"/rfp/tickets/{t.ticket_id}/reprocess").status_code == 409
        t.heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        s.add(t)
        s.commit()
    assert client.get("/rfp/tickets/1").json()["processing"] == "stalled"
    assert client.post("/rfp/tickets/1/reprocess").status_code == 202  # el proceso murió: se puede reintentar
    assert client.get("/rfp/tickets/1").json()["status"] == "analisis_completo"


def test_false_negative_is_reopened_with_force_only_for_discarded_tickets(env):
    client, _, model, _ = env
    upload(client, PDF_INVALID)
    assert client.post("/rfp/tickets/1/reprocess?force=true").status_code == 202  # el simulador responde con el plan vacío → solo marketing
    forced = client.get("/rfp/tickets/1").json()
    assert forced["status"] == "analisis_completo" and forced["classification"]["forced_by_user"] is True
    upload(client, PDF_INFORMAL)
    assert client.post("/rfp/tickets/2/reprocess?force=true").status_code == 409  # ya completo



# ---------------------------------------------------------------------------------------------- Parte 2


def test_generation_chains_after_intake_and_the_detail_shows_drafts_and_evaluations(env, monkeypatch):
    client, engine, _, _ = env
    monkeypatch.setenv("RFP_AUTO_GENERATE", "1")
    upload(client, PDF_FORMAL)
    d = client.get("/rfp/tickets/1").json()
    assert d["status"] == "en_evaluación" and d["processing"] == "idle" and d["response_completed_at"]
    assert d["progress"] == {"total": 4, "passed": 4, "needs_review": 0, "working": 0, "errors": 0}
    marketing = d["sections"][0]
    assert marketing["generation_status"] == "paso" and marketing["draft_content"] and marketing["needs_human_review"] is False
    assert marketing["evaluation_results"]["overall_pass"] is True and set(marketing["evaluation_results"]) >= {"readability", "relevance", "compliance"}
    assert d["part3_handoff"]["all_sections_passed"] is True and d["part3_handoff"]["ready_for_part_3"] is True
    assert client.get("/rfp/tickets").json()[0]["progress"]["passed"] == 4
    with Session(engine) as s:  # los borradores y evaluaciones viven en PostgreSQL/SQLModel
        assert all(r.draft_content and r.evaluation_results for r in repository.get_sections(s, 1))


def test_generate_endpoint_is_gated_by_the_ticket_state(env):
    client, _, _, _ = env
    upload(client, PDF_INVALID)
    assert client.post("/rfp/tickets/1/generate").status_code == 409  # descartado
    upload(client, PDF_FORMAL)
    assert client.get("/rfp/tickets/2").json()["status"] == "analisis_completo"
    assert client.post("/rfp/tickets/2/generate").status_code == 202
    assert client.get("/rfp/tickets/2").json()["status"] == "en_evaluación"
    assert client.post("/rfp/tickets/2/generate").status_code == 409  # ya evaluado: hace falta regenerate=true
    assert client.post("/rfp/tickets/2/generate?regenerate=true").status_code == 202
    assert client.post("/rfp/tickets/99/generate").status_code == 404


def test_exhausted_iterations_end_in_needs_human_review_with_last_draft_and_feedback(env, monkeypatch):
    client, _, model, _ = env
    monkeypatch.setenv("RFP_MAX_ITERATIONS", "2")
    upload(client, PDF_FORMAL)
    from rfp_response_support import GOOD
    model.part2.drafts["operaciones"] = [GOOD["operaciones"].format(client="Sunset Bay Resorts, LLC") + BAD_SLA] * 2
    assert client.post("/rfp/tickets/1/generate").status_code == 202
    d = client.get("/rfp/tickets/1").json()
    assert d["status"] == "needs_human_review"
    ops = next(s for s in d["sections"] if s["department_id"] == "operaciones")
    assert ops["needs_human_review"] is True and ops["iterations"] == 2 and "5 días hábiles" in ops["draft_content"]
    assert ops["evaluation_results"]["compliance"]["pass"] is False and "setup-sla-breach" in ops["evaluation_results"]["compliance"]["rule_ids"]
    assert "setup-sla-breach" in ops["evaluation_results"]["feedback_for_generator"] and len(ops["evaluation_history"]) == 2
    assert d["progress"]["needs_review"] == 1 and d["progress"]["passed"] == 3
    assert d["part3_handoff"]["needs_human_review"] == ["operaciones"] and d["part3_handoff"]["all_sections_passed"] is False
    assert client.post("/rfp/tickets/1/generate").status_code == 409
    assert client.post("/rfp/tickets/1/generate?regenerate=true").status_code == 202
    assert client.get("/rfp/tickets/1").json()["status"] == "en_evaluación"  # el modelo ya no falla: todas pasan


def test_failed_generation_is_visible_and_resumes_only_what_failed(env):
    client, _, model, _ = env
    upload(client, PDF_FORMAL)
    model.part2.generator_hook = lambda dept: (_ for _ in ()).throw(RuntimeError("caída del proveedor")) if dept == "training" else None
    assert client.post("/rfp/tickets/1/generate").status_code == 202
    failed = client.get("/rfp/tickets/1").json()
    assert failed["status"] in ("generando_borrador", "en_evaluación") and failed["processing"] == "failed"
    assert "training" in failed["processing_error"] and failed["progress"]["errors"] == 1 and failed["progress"]["passed"] == 3
    model.part2.generator_hook = None
    before = len(model.part2.agent_calls("generator"))
    assert client.post("/rfp/tickets/1/generate").status_code == 202  # reanuda
    done = client.get("/rfp/tickets/1").json()
    assert done["processing"] == "idle" and done["progress"]["passed"] == 4 and done["part3_handoff"]["all_sections_passed"] is True
    assert len(model.part2.agent_calls("generator")) - before == 1  # solo se rehízo training


def test_part1_reprocess_is_closed_once_part2_has_started(env):
    client, _, _, _ = env
    upload(client, PDF_FORMAL)
    client.post("/rfp/tickets/1/generate")
    assert client.post("/rfp/tickets/1/reprocess").status_code == 409


def test_a_generation_that_stopped_beating_is_stalled(env):
    client, engine, _, _ = env
    upload(client, PDF_FORMAL)
    with Session(engine) as s:
        t = repository.get_ticket(s, 1)
        t.status, t.heartbeat_at, t.response_completed_at = "generando_borrador", datetime.now(timezone.utc) - timedelta(minutes=30), None
        s.add(t)
        s.commit()
    assert client.get("/rfp/tickets/1").json()["processing"] == "stalled"


def test_ensure_columns_adds_the_part2_columns_to_a_table_created_by_part1(tmp_path):
    from sqlalchemy import inspect, text
    from app.rfp.schema_sync import ensure_columns
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE rfp_tickets (ticket_id INTEGER PRIMARY KEY, status VARCHAR)"))
    added = ensure_columns(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("rfp_tickets")}
    assert {"part3_handoff", "response_completed_at"} <= cols and any("part3_handoff" in a for a in added)
    assert ensure_columns(engine) == []  # idempotente
