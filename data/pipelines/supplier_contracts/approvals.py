"""Aprobación humana. Los agentes REDACTAN comunicaciones a proveedores; ninguna sale sin aprobación del aprobador correcto:
cualquier comunicación → Felipe Guerrero; sobre un contrato con valor anual > USD 200.000 (o su equivalente en COP) → Felipe Y Mariana.
Los agentes no tienen herramienta de aprobar ni de enviar: aquí solo actúan personas del directorio (staff), nunca `agent:*`."""
from __future__ import annotations

import json
from decimal import Decimal

from . import config, tools
from .sensitive import clean
from .store import Store, now


class ApprovalError(Exception):
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.message, self.status_code = message, status_code


class Approvals:
    def __init__(self, store: Store):
        self.store = store

    # ---- quién debe aprobar
    def required_roles(self, supplier_id: str) -> tuple[list[str], Decimal | None]:
        contract = self.store.one("SELECT id FROM contracts WHERE supplier_id=?", (supplier_id,))
        value_usd = None
        if contract:
            row = self.store.one("SELECT params FROM terms WHERE contract_id=? AND kind='annual_value' AND doubtful=0", (contract["id"],))
            if row:
                p = json.loads(row["params"])
                value_usd = tools.to_usd(Decimal(p["amount"]), p["currency"])
        return list(config.required_approvers(value_usd)), value_usd

    # ---- redactar (lo hace el supervisor; nace pendiente)
    def draft(self, supplier_id: str, subject: str, body: str, created_by: str) -> dict:
        if supplier_id not in config.SUPPLIER_BY_ID:
            raise ApprovalError("Proveedor desconocido.", 404)
        roles, value_usd = self.required_roles(supplier_id)
        contract = self.store.one("SELECT id FROM contracts WHERE supplier_id=?", (supplier_id,))
        cid = self.store.run("INSERT INTO communications(supplier_id,contract_id,subject,body,status,required_roles,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
                             (supplier_id, contract["id"] if contract else None, clean(subject), clean(body), "pending_approval", json.dumps(roles), created_by, now()))
        self.store.event("agent" if created_by.startswith("agent:") else "staff", created_by, "communication_drafted", f"communication:{cid}",
                         {"supplier_id": supplier_id, "required_roles": roles, "contract_value_usd": str(value_usd) if value_usd is not None else None})
        return self.get(cid)

    def get(self, cid: int) -> dict:
        row = self.store.one("SELECT * FROM communications WHERE id=?", (cid,))
        if row is None:
            raise ApprovalError("Comunicación no encontrada.", 404)
        row["required_roles"] = json.loads(row["required_roles"])
        row["approvals"] = self.store.q("SELECT role, staff_id, decision, comment, ts FROM approvals WHERE communication_id=? ORDER BY id", (cid,))
        approved = {a["role"] for a in row["approvals"] if a["decision"] == "approve"}
        row["missing_roles"] = [r for r in row["required_roles"] if r not in approved] if row["status"] == "pending_approval" else []
        return row

    def listing(self) -> list[dict]:
        return [self.get(r["id"]) for r in self.store.q("SELECT id FROM communications ORDER BY id DESC")]

    # ---- decidir (solo personas con el rol exigido)
    def decide(self, cid: int, staff: dict | None, decision: str, comment: str | None = None) -> dict:
        if staff is None:
            raise ApprovalError("Solo las personas del directorio de Operaciones pueden aprobar o rechazar.")
        if str(staff["id"]).startswith("agent:"):
            raise ApprovalError("Un agente no puede aprobar.")
        comm = self.get(cid)
        if comm["status"] != "pending_approval":
            raise ApprovalError(f"La comunicación ya está «{comm['status']}».", 409)
        if staff["role"] not in comm["required_roles"]:
            raise ApprovalError("No eres uno de los aprobadores exigidos para esta comunicación.")
        if any(a["role"] == staff["role"] for a in comm["approvals"]):
            raise ApprovalError("Tu aprobación ya está registrada.", 409)
        self.store.run("INSERT INTO approvals(communication_id,role,staff_id,decision,comment,ts) VALUES(?,?,?,?,?,?)",
                       (cid, staff["role"], staff["id"], decision, clean(comment or ""), now()))
        self.store.event("staff", staff["id"], f"communication_{decision}", f"communication:{cid}", {"role": staff["role"]})
        fresh = self.get(cid)
        if decision == "reject":
            self.store.run("UPDATE communications SET status='rejected', decided_at=? WHERE id=?", (now(), cid))
        elif not fresh["missing_roles"]:
            self.store.run("UPDATE communications SET status='approved', decided_at=? WHERE id=?", (now(), cid))
            self.store.event("system", "system:approvals", "communication_fully_approved", f"communication:{cid}", {"roles": fresh["required_roles"]})
        return self.get(cid)

    # ---- enviar: solo una persona del rol Operaciones, y solo si está aprobada por TODOS los aprobadores exigidos
    def send(self, cid: int, staff: dict | None) -> dict:
        if staff is None or str(staff["id"]).startswith("agent:") or staff["role"] != config.ROLE_OPS_DIRECTOR:
            raise ApprovalError("Solo el Director de Operaciones puede dar la orden de envío.")
        comm = self.get(cid)
        if comm["status"] != "approved":
            raise ApprovalError(f"No se puede enviar: la comunicación está «{comm['status']}» y debe estar aprobada por {', '.join(comm['required_roles'])}.", 409)
        self.store.run("UPDATE communications SET status='sent', sent_at=? WHERE id=?", (now(), cid))
        # El envío real (correo al proveedor) lo haría aquí la integración de salida; en este proyecto queda registrado, sin salir nada.
        self.store.event("staff", staff["id"], "communication_sent", f"communication:{cid}", {"supplier_id": comm["supplier_id"], "channel": "registrado (sin integración de correo)"})
        return self.get(cid)
