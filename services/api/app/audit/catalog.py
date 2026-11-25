"""INVENTARIO de acciones sensibles auditadas. Es la fuente única: el middleware lo usa para registrar y
`tests/test_audit_log.py` comprueba que NINGUNA ruta que modifique datos queda fuera (o exenta con motivo).

Cada entrada: (método, ruta) → AuditSpec. `department` es el departamento DUEÑO del recurso (reparte la visibilidad del visor).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.access.permissions import OPS, PROCUREMENT


@dataclass(frozen=True)
class AuditSpec:
    action: str
    category: str  # auth · access · federated · audit · process · data
    resource_type: str
    department: str | None = None
    id_from_body: str | None = None  # clave del JSON de respuesta que trae el id del recurso creado


def _s(action, category, resource_type, department=None, id_from_body=None) -> AuditSpec:
    return AuditSpec(action, category, resource_type, department, id_from_body)


_SUPPLIERS = {
    ("POST", "{p}"): _s("supplier.create", "data", "supplier", PROCUREMENT, "id"),
    ("DELETE", "{p}/{{supplier_id}}"): _s("supplier.delete", "data", "supplier", PROCUREMENT),
    ("PATCH", "{p}/{{supplier_id}}/rate"): _s("supplier.rate_change", "data", "supplier", PROCUREMENT),
    ("PATCH", "{p}/{{supplier_id}}/status"): _s("supplier.status_change", "data", "supplier", PROCUREMENT),
}

AUDITED_ROUTES: dict[tuple[str, str], AuditSpec] = {
    # ---- autenticación (sesiones y credenciales)
    ("POST", "/auth/login"): _s("auth.login", "auth", "session"),
    ("POST", "/auth/register"): _s("auth.register", "auth", "user", None, "id"),
    ("POST", "/auth/forgot-password"): _s("auth.password_reset_request", "auth", "user"),
    ("POST", "/auth/reset-password"): _s("auth.password_reset", "auth", "user"),
    ("POST", "/auth/change-password"): _s("auth.password_change", "auth", "user"),
    # ---- autenticación federada
    ("POST", "/auth/federated/{provider}/link/start"): _s("federated.link_start", "federated", "federated_identity"),
    ("POST", "/auth/federated/{provider}/link/complete"): _s("federated.link", "federated", "federated_identity"),
    ("DELETE", "/auth/federated/{provider}"): _s("federated.unlink", "federated", "federated_identity"),
    ("POST", "/auth/federated/{provider}/login/start"): _s("federated.login_start", "federated", "session"),
    ("POST", "/auth/federated/{provider}/login/complete"): _s("federated.login", "federated", "session"),
    # ---- usuarios, roles y permisos (cambios de permisos)
    ("POST", "/users"): _s("user.create", "access", "user", None, "id"),
    ("PUT", "/users/{user_id}"): _s("user.update", "access", "user"),
    ("DELETE", "/users/{user_id}"): _s("user.delete", "access", "user"),
    ("PATCH", "/users/{user_id}/assignment"): _s("user.assignment_change", "access", "user"),
    ("PUT", "/profiles/me"): _s("profile.update", "access", "profile"),
    ("POST", "/roles"): _s("role.create", "access", "role", None, "id"),
    ("PUT", "/roles/{role_id}"): _s("role.update", "access", "role"),
    ("POST", "/departments"): _s("department.create", "access", "department", None, "id"),
    ("PUT", "/departments/{department_id}"): _s("department.update", "access", "department"),
    # ---- datos de negocio
    ("POST", "/internal-reports"): _s("internal_report.create", "data", "internal_report", None, "id"),
    ("PUT", "/internal-reports/{report_id}"): _s("internal_report.update", "data", "internal_report"),
    ("DELETE", "/internal-reports/{report_id}"): _s("internal_report.delete", "data", "internal_report"),
    ("POST", "/internal-reports/{report_id}/approve"): _s("internal_report.approve", "data", "internal_report"),
    **{(m, p.format(p="/api/suppliers")): s for (m, p), s in _SUPPLIERS.items()},
    **{(m, p.format(p="/suppliers")): s for (m, p), s in _SUPPLIERS.items()},
    ("POST", "/api/incidents"): _s("incident.create", "data", "incident", OPS, "id"),
    ("PATCH", "/api/incidents/{incident_id}/status"): _s("incident.status_change", "data", "incident", OPS),
    ("POST", "/api/incidents/analyze"): _s("incident.analyze", "data", "incident_analysis", OPS, "task_id"),
    ("GET", "/api/incidents/results/export"): _s("incident.export", "data", "incident_analysis", OPS),  # salida de datos
    ("POST", "/inventory/products"): _s("inventory.product_create", "data", "product", OPS, "id"),
    ("POST", "/inventory/orders/inbound"): _s("inventory.inbound", "data", "inventory_order", OPS, "id"),
    ("POST", "/inventory/orders/outbound"): _s("inventory.outbound", "data", "inventory_order", OPS, "id"),
    ("POST", "/rfp/tickets"): _s("rfp.ticket_create", "data", "rfp_ticket", None, "id"),
    ("POST", "/rfp/tickets/{ticket_id}/approval/start"): _s("rfp.approval_start", "data", "rfp_ticket"),
    ("POST", "/rfp/tickets/{ticket_id}/approval/retry"): _s("rfp.approval_retry", "data", "rfp_ticket"),
    ("POST", "/rfp/tickets/{ticket_id}/approvals/{department_id}"): _s("rfp.approval_decision", "data", "rfp_ticket"),
    ("POST", "/rfp/tickets/{ticket_id}/generate"): _s("rfp.generate", "data", "rfp_ticket"),
    ("POST", "/rfp/tickets/{ticket_id}/reprocess"): _s("rfp.reprocess", "data", "rfp_ticket"),
    ("POST", "/reporting/inventory-performance/runs"): _s("reporting.run", "data", "report_run", OPS, "run_id"),
    # ---- proveedores y contratos (supervisor + especialistas; la aprobación humana de comunicaciones queda aquí con su actor)
    ("POST", "/supplier-contracts/seed"): _s("supplier_contracts.seed", "data", "supplier_contracts_dataset", OPS),
    ("POST", "/supplier-contracts/alerts/scan"): _s("supplier_contracts.alerts_scan", "data", "supplier_alert", OPS),
    ("POST", "/supplier-contracts/ask"): _s("supplier_contracts.ask", "data", "supplier_agent_session", OPS),
    ("POST", "/supplier-contracts/brief"): _s("supplier_contracts.brief", "data", "renegotiation_brief", OPS),
    ("POST", "/supplier-contracts/notices"): _s("supplier_contracts.notice_record", "data", "supplier_notice", OPS, "id"),
    ("POST", "/supplier-contracts/communications/{communication_id}/decision"): _s("supplier_contracts.communication_decision", "data", "supplier_communication", OPS),
    ("POST", "/supplier-contracts/communications/{communication_id}/send"): _s("supplier_contracts.communication_send", "data", "supplier_communication", OPS),
    ("GET", "/supplier-contracts/audit/events"): _s("supplier_contracts.audit_view", "audit", "supplier_agent_events", OPS),
    ("GET", "/supplier-contracts/audit/messages"): _s("supplier_contracts.audit_messages_view", "audit", "supplier_agent_messages", OPS),
    # ---- uso del agente de IA y telemetría de plataforma
    ("POST", "/agent/query"): _s("agent.query", "data", "agent_session", OPS),
    ("POST", "/knowledge/query"): _s("knowledge.query", "data", "knowledge_base"),
    ("POST", "/telemetry/events"): _s("telemetry.ingest", "process", "telemetry_event"),
    # ---- el propio visor del audit log queda auditado (quién mira qué)
    ("GET", "/audit-log"): _s("audit.view", "audit", "audit_log"),
    ("GET", "/audit-log/verify"): _s("audit.verify", "audit", "audit_log"),
}

# Rutas que modifican datos y que NO se registran como acción: solo estas, y con motivo.
EXEMPT_ROUTES: dict[tuple[str, str], str] = {}

AUDITED_ACTIONS = sorted({spec.action for spec in AUDITED_ROUTES.values()} | {"access.denied", "process.task"})
