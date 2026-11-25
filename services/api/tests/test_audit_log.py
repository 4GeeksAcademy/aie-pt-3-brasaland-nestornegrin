"""Audit log (ticket feature/audit-log) — pruebas de aceptación contra la API REAL.

Cubre los cinco criterios de evaluación: (1) una entrada no se puede modificar ni borrar, (2) toda acción sensible del inventario queda
registrada con actor, acción, recurso y fecha, (3) los agentes y procesos se distinguen de las personas, (4) el visor filtra y respeta
rol y departamento, (5) la alteración manual rompe la cadena y se detecta.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest
import app.main as main_module
from app.audit.catalog import AUDITED_ROUTES, EXEMPT_ROUTES
from app.audit.log import AuditLog
from app.audit.recorder import record_process
from conftest import DEFAULT_PASSWORD, make_access_user

SUPPLIER = {"name": "Nuevo", "categories": ["Carnes"], "country": "CO", "rate": 3, "status": "Activo"}


def entries(**match):
    rows = list(main_module.audit_log.iter_entries())
    return [e for e in rows if all(getattr(e, k) == v for k, v in match.items())]


def raw_lines() -> list[str]:
    return main_module.audit_log._path.read_text().splitlines()


def write_lines(lines: list[str]) -> None:
    main_module.audit_log._path.write_text("\n".join(lines) + "\n")


# ===================================================================== 1 · append-only: no hay forma de modificar ni borrar
def test_la_clase_solo_expone_anadir_y_leer():
    public = {name for name in dir(AuditLog) if not name.startswith("_")}
    assert public == {"append", "iter_entries", "query", "facets", "verify"}  # ni update, ni delete, ni truncate


def test_la_api_no_ofrece_ninguna_ruta_que_modifique_o_borre(client, seeded):
    nicolas = seeded("nicolas")
    paths = main_module.app.openapi()["paths"]
    audit_paths = {p: set(ops) for p, ops in paths.items() if p.startswith("/audit-log")}
    assert audit_paths and all(ops == {"get"} for ops in audit_paths.values()), audit_paths
    for method in ("post", "put", "patch", "delete"):
        for url in ("/audit-log", "/audit-log/1", "/audit-log/verify"):
            assert getattr(client, method)(url, headers=nicolas).status_code in (404, 405), (method, url)


def test_un_admin_tampoco_puede_borrar_ni_editar_una_entrada_por_la_api(client, seeded):
    nicolas = seeded("nicolas")
    first = entries()[0]
    assert client.delete(f"/audit-log/{first.id}", headers=nicolas).status_code in (404, 405)
    assert client.patch(f"/audit-log/{first.id}", headers=nicolas, json={"outcome": "success"}).status_code in (404, 405)
    assert entries()[0] == first


# ===================================================================== 2 · inventario completo de acciones sensibles
def _mutating_routes() -> set[tuple[str, str]]:
    found = set()
    for path, operations in main_module.app.openapi()["paths"].items():
        for method in operations:
            if method.upper() != "GET":
                found.add((method.upper(), path))
    return found


def test_toda_ruta_que_modifica_datos_esta_inventariada(client):
    missing = {route for route in _mutating_routes() if route not in AUDITED_ROUTES and route not in EXEMPT_ROUTES}
    assert not missing, f"Rutas que modifican datos sin auditar (añádelas a app/audit/catalog.py): {sorted(missing)}"


def test_el_inventario_no_apunta_a_rutas_que_no_existen(client):
    existing = {(m.upper(), p) for p, ops in main_module.app.openapi()["paths"].items() for m in ops}
    assert {route for route in AUDITED_ROUTES if route not in existing} == set()


def test_las_acciones_sensibles_quedan_con_actor_accion_recurso_y_fecha(client, seeded, monkeypatch):
    monkeypatch.setattr(main_module.task_results, "load_latest", lambda: None)  # sin Redis en la prueba
    lucia, nicolas, felipe = seeded("lucia"), seeded("nicolas"), seeded("felipe")
    before = datetime.now(timezone.utc) - timedelta(seconds=2)
    sid = client.post("/api/suppliers", headers=lucia, json=SUPPLIER).json()["id"]
    client.patch(f"/api/suppliers/{sid}/rate", headers=lucia, json={"rate": 4})
    client.patch(f"/api/suppliers/{sid}/status?confirm=true", headers=lucia, json={"status": "Suspendido"})
    client.delete(f"/api/suppliers/{sid}?confirm=true", headers=nicolas)
    camila = main_module.user_repository.get_by_email("camila.marketing@brasaland.example")
    client.patch(f"/users/{camila.id}/assignment", headers=nicolas, json={"role_id": main_module.access_catalog.get_role_by_code("supervisor")["id"]})
    client.post("/internal-reports", headers=felipe, json={"title": "t", "body": "b"})
    client.get("/api/incidents/results/export", headers=felipe)

    lucia_id = str(main_module.user_repository.get_by_email("lucia.procurement@brasaland.example").id)
    created = entries(action="supplier.create")[0]
    assert (created.actor_type, created.actor_id, created.resource_type, created.resource_id, created.outcome) == ("user", lucia_id, "supplier", str(sid), "success")
    assert created.actor_label == "lucia.procurement@brasaland.example" and created.actor_role == "supervisor"
    assert created.department == "procurement" and created.origin and created.timestamp >= before
    assert entries(action="supplier.rate_change")[0].details["rate"]["to"] == 4
    assert entries(action="supplier.status_change")[0].details["status"]["to"] == "Suspendido"
    assert entries(action="supplier.delete")[0].actor_id == str(main_module.user_repository.get_by_email("nicolas.admin@brasaland.example").id)
    change = entries(action="user.assignment_change")[0]
    assert (change.resource_id, change.details["role"]) == (str(camila.id), {"from": "employee", "to": "supervisor"})
    assert entries(action="internal_report.create")[0].department == "restaurant_operations"
    assert entries(action="incident.export")  # la salida de datos también se audita


def test_los_eventos_de_autenticacion_quedan_registrados(client, seeded):
    seeded("camila")
    client.post("/auth/login", json={"email": "camila.marketing@brasaland.example", "password": "incorrecta-123"})
    client.post("/auth/forgot-password", json={"email": "camila.marketing@brasaland.example"})
    camila = {"Authorization": "Bearer " + client.post("/auth/login", json={"email": "camila.marketing@brasaland.example", "password": DEFAULT_PASSWORD}).json()["access_token"]}
    client.post("/auth/change-password", headers=camila, json={"current_password": DEFAULT_PASSWORD, "new_password": "OtraClave-2026!"})
    logins = entries(action="auth.login")
    assert [e.outcome for e in logins][-2:] == ["failure", "success"]
    failed = [e for e in logins if e.outcome == "failure"][-1]
    assert failed.actor_type == "anonymous" and failed.actor_label == "camila.marketing@brasaland.example" and failed.actor_id.startswith("anon:")
    assert [e for e in logins if e.outcome == "success"][-1].actor_type == "user"
    assert entries(action="auth.password_reset_request") and entries(action="auth.password_change")[0].actor_type == "user"


def test_los_cambios_de_permisos_y_roles_quedan_registrados(client, seeded):
    nicolas = seeded("nicolas")
    client.post("/departments", headers=nicolas, json={"code": "legal", "name": "Legal"})
    assert entries(action="department.create")
    user = client.post("/users", headers=nicolas, json={"email": "nuevo@brasaland.example", "password": "ValidPass123"}).json()
    assert entries(action="user.create")[0].resource_id == str(user["id"])


def test_el_log_no_guarda_contrasenas_ni_tokens(client, seeded):
    seeded("camila")
    client.post("/auth/login", json={"email": "camila.marketing@brasaland.example", "password": "SuperSecreta-999"})
    client.post("/auth/reset-password", json={"token": "token-secreto-abc", "new_password": "OtraSuperSecreta-1"})
    content = main_module.audit_log._path.read_text()
    assert "SuperSecreta" not in content and "token-secreto" not in content and "Bearer" not in content


def test_una_denegacion_403_queda_registrada_aunque_la_ruta_no_este_en_el_inventario(client, seeded):
    felipe = seeded("felipe")
    response = client.get("/api/suppliers", headers=felipe)
    assert response.status_code == 403
    denied = entries(action="access.denied")[-1]
    assert (denied.outcome, denied.category, denied.details["http_status"]) == ("denied", "access", 403)
    assert denied.actor_label == "felipe.ops@brasaland.example" and denied.details["denied_reason"]


def test_una_accion_denegada_del_inventario_se_registra_como_denegada(client, seeded):
    felipe = seeded("felipe")
    assert client.post("/api/suppliers", headers=felipe, json=SUPPLIER).status_code == 403
    assert entries(action="supplier.create")[-1].outcome == "denied"
    assert client.post("/api/suppliers", json=SUPPLIER).status_code == 401  # sin sesión
    assert entries(action="supplier.create")[-1].actor_type == "anonymous"


# ===================================================================== 3 · agentes y procesos ≠ personas
def test_las_acciones_de_un_agente_se_distinguen_de_las_de_una_persona(client, seeded):
    agente, felipe = seeded("agente"), seeded("felipe")
    client.post("/api/incidents", headers=agente, json={"local": "Medellín Centro", "description": "Fuga", "severity": "alta"})
    client.post("/api/incidents", headers=felipe, json={"local": "Medellín Centro", "description": "Fuga", "severity": "alta"})
    actors = [e.actor_type for e in entries(action="incident.create")]
    assert actors == ["agent", "user"]
    assert main_module.user_repository.get_by_email("agente.operaciones@brasaland.example").account_type == "agent"


def test_el_tipo_de_cuenta_lo_fija_el_servidor_no_el_cliente(client, seeded):
    felipe = seeded("felipe")
    client.post("/api/incidents", headers={**felipe, "X-Actor-Type": "agent", "X-Actor": "user:999"}, json={"local": "Medellín Centro", "description": "Fuga", "severity": "alta"})
    assert entries(action="incident.create")[-1].actor_type == "user"


def test_un_proceso_del_sistema_queda_como_system_con_su_pid(client):
    record_process(main_module.audit_log, "celery-worker", "process.task", resource_type="incident_analysis", resource_id="task-1",
                   department="restaurant_operations", details={"task": "analyze_incidents_csv"})
    (entry,) = entries(actor_type="system")
    assert (entry.actor_id, entry.channel, entry.category, entry.action) == ("celery-worker", "process", "process", "process.task")
    assert entry.origin.startswith("process:celery-worker:")


def test_una_tarea_de_celery_se_audita_como_proceso_en_el_mismo_registro(client):
    from services.async_tasks import audit as task_audit

    task_audit.record_task("process.task", task_id="abc-123", outcome="success", details={"task": "analyze_incidents_csv"})
    (entry,) = entries(actor_type="system")
    assert (entry.resource_id, entry.outcome, entry.channel, entry.department) == ("abc-123", "success", "process", "restaurant_operations")
    assert main_module.audit_log.verify().valid  # el worker escribe en la MISMA cadena que la API


# ===================================================================== 4 · visor: filtros, alcance por rol y departamento, paginación
def _populate(client, seeded):
    lucia, felipe, nicolas = seeded("lucia"), seeded("felipe"), seeded("nicolas")
    client.post("/api/suppliers", headers=lucia, json=SUPPLIER)
    client.post("/api/incidents", headers=felipe, json={"local": "Medellín Centro", "description": "Fuga", "severity": "alta"})
    return lucia, felipe, nicolas


def test_el_admin_de_tecnologia_ve_todo_incluidos_los_eventos_de_seguridad(client, seeded):
    _, _, nicolas = _populate(client, seeded)
    page = client.get("/audit-log?limit=200", headers=nicolas).json()
    categories = {e["category"] for e in page["items"]}
    assert {"auth", "data"} <= categories and page["total"] == len(page["items"])


def test_un_supervisor_solo_ve_datos_de_su_departamento(client, seeded):
    lucia, felipe, _ = _populate(client, seeded)
    seen = client.get("/audit-log?limit=200", headers=lucia).json()["items"]
    assert seen and {e["category"] for e in seen} == {"data"}  # nada de logins ni cambios de permisos
    assert {e["department"] or e["actor_department"] for e in seen} == {"procurement"}
    ops = client.get("/audit-log?limit=200", headers=felipe).json()["items"]
    assert {e["department"] or e["actor_department"] for e in ops} == {"restaurant_operations"}


def test_un_admin_de_otro_departamento_no_ve_todo(client, seeded):
    _populate(client, seeded)
    admin_procurement = make_access_user(client, "admin.compras@brasaland.example", "admin", "procurement")
    seen = client.get("/audit-log?limit=200", headers=admin_procurement).json()["items"]
    assert seen and {e["category"] for e in seen} == {"data"}
    assert {e["department"] or e["actor_department"] for e in seen} == {"procurement"}
    assert client.get("/audit-log/verify", headers=admin_procurement).status_code == 403  # verificar es de la plataforma


def test_un_empleado_y_un_usuario_sin_departamento_no_acceden_al_visor(client, seeded):
    camila = seeded("camila")
    assert client.get("/audit-log", headers=camila).status_code == 403
    assert client.get("/audit-log/facets", headers=camila).status_code == 403
    no_dept = make_access_user(client, "sin.depto@brasaland.example", "supervisor", None)
    assert client.get("/audit-log", headers=no_dept).status_code == 403
    assert client.get("/audit-log").status_code == 401


def test_el_filtro_por_departamento_no_amplia_el_alcance(client, seeded):
    lucia, _, _ = _populate(client, seeded)
    assert client.get("/audit-log?department=restaurant_operations", headers=lucia).json()["items"] == []


def test_los_filtros_por_actor_accion_recurso_tipo_y_fecha(client, seeded):
    lucia, felipe, nicolas = _populate(client, seeded)
    lucia_id = main_module.user_repository.get_by_email("lucia.procurement@brasaland.example").id

    def ask(query: str):
        return client.get(f"/audit-log?{query}&limit=200", headers=nicolas).json()["items"]

    assert {e["actor_id"] for e in ask("actor=lucia.procurement")} == {str(lucia_id)}
    assert {e["action"] for e in ask("action=supplier.create")} == {"supplier.create"}
    assert {e["resource_type"] for e in ask("resource_type=incident")} == {"incident"}
    assert {e["outcome"] for e in ask("outcome=denied")} <= {"denied"}
    assert ask("actor_type=agent") == []
    assert ask("category=data&action=incident.create")
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    assert ask(f"date_from={future}") == [] and ask(f"date_to={past}") == []
    assert ask(f"date_from={past}&date_to={future}")
    assert client.get("/audit-log?outcome=cualquiera", headers=nicolas).status_code == 400  # filtro inválido (validación de la API)


def test_la_paginacion_recorre_todo_sin_repetir_y_limita_el_tamano(client, seeded):
    nicolas = seeded("nicolas")
    for _ in range(12):
        client.post("/auth/login", json={"email": "nadie@x.test", "password": "xxxxxxxx"})
    seen, cursor, pages = [], None, 0
    while True:
        url = "/audit-log?limit=5" + (f"&before_seq={cursor}" if cursor else "")
        page = client.get(url, headers=nicolas).json()
        assert len(page["items"]) <= 5
        seen += [e["seq"] for e in page["items"]]
        pages += 1
        cursor = page["next_before_seq"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) and seen == sorted(seen, reverse=True) and pages >= 3
    assert client.get("/audit-log?limit=5000", headers=nicolas).status_code == 400  # tope de página


def test_las_facetas_no_revelan_acciones_fuera_del_alcance(client, seeded):
    lucia, _, nicolas = _populate(client, seeded)
    mine = client.get("/audit-log/facets", headers=lucia).json()
    assert "auth.login" not in mine["actions"] and "incident.create" not in mine["actions"] and mine["can_view_security"] is False
    assert "auth.login" in client.get("/audit-log/facets", headers=nicolas).json()["actions"]


def test_consultar_el_visor_tambien_queda_auditado(client, seeded):
    nicolas = seeded("nicolas")
    client.get("/audit-log?action=supplier.create", headers=nicolas)
    view = entries(action="audit.view")[-1]
    assert view.category == "audit" and view.actor_label == "nicolas.admin@brasaland.example"


# ===================================================================== 5 · evidencia de alteración
def _fill(client, seeded):
    lucia = seeded("lucia")
    for _ in range(5):
        client.post("/api/suppliers", headers=lucia, json=SUPPLIER)
    assert main_module.audit_log.verify().valid


def test_una_cadena_intacta_verifica(client, seeded):
    _fill(client, seeded)
    result = main_module.audit_log.verify()
    assert result.valid and result.entries == len(raw_lines()) and result.broken_at_seq is None and len(result.head_hash) == 64
    nicolas = seeded("nicolas")
    assert client.get("/audit-log/verify", headers=nicolas).json()["valid"] is True


def test_editar_el_contenido_de_una_entrada_rompe_la_cadena(client, seeded):
    _fill(client, seeded)
    lines = raw_lines()
    row = json.loads(lines[3])
    row["actor_id"] = "999"  # alguien se «borra» de un cambio
    lines[3] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    write_lines(lines)
    result = main_module.audit_log.verify()
    assert (result.valid, result.broken_at_seq) == (False, row["seq"]) and "alterado" in result.reason


def test_borrar_una_entrada_intermedia_rompe_la_cadena(client, seeded):
    _fill(client, seeded)
    lines = raw_lines()
    del lines[2]
    write_lines(lines)
    result = main_module.audit_log.verify()
    assert result.valid is False and result.broken_at_seq == 4


def test_reordenar_entradas_rompe_la_cadena(client, seeded):
    _fill(client, seeded)
    lines = raw_lines()
    lines[2], lines[3] = lines[3], lines[2]
    write_lines(lines)
    assert main_module.audit_log.verify().valid is False


def test_recortar_el_final_se_detecta_por_la_cabeza_firmada(client, seeded):
    _fill(client, seeded)
    write_lines(raw_lines()[:-2])  # la cadena restante es coherente, pero ya no coincide con la cabeza
    result = main_module.audit_log.verify()
    assert result.valid is False and "cabeza" in result.reason


def test_borrar_el_fichero_entero_se_detecta(client, seeded):
    _fill(client, seeded)
    main_module.audit_log._path.write_text("")
    assert main_module.audit_log.verify().valid is False


def test_sin_la_clave_no_se_puede_forjar_una_cadena_valida(client, seeded, tmp_path):
    """Un atacante con el fichero pero SIN la clave recalcula los hashes con SHA-256 plano: el HMAC lo delata."""
    import hashlib
    _fill(client, seeded)
    lines, prev, forged = raw_lines(), "0" * 64, []
    for line in lines:
        row = json.loads(line)
        row.pop("hash")
        row["actor_id"] = "999" if row["seq"] == 2 else row["actor_id"]
        row["prev_hash"] = prev
        canonical = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        prev = hashlib.sha256(f"{row['prev_hash']}|{canonical}".encode()).hexdigest()
        row["hash"] = prev
        forged.append(json.dumps(row, sort_keys=True, separators=(",", ":")))
    write_lines(forged)
    assert main_module.audit_log.verify().valid is False


def test_el_visor_sigue_funcionando_pero_verify_avisa_tras_una_alteracion(client, seeded):
    _fill(client, seeded)
    lines = raw_lines()
    row = json.loads(lines[1]); row["action"] = "supplier.nada"
    lines[1] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    write_lines(lines)
    nicolas = seeded("nicolas")
    assert client.get("/audit-log/verify", headers=nicolas).json()["valid"] is False


def test_no_se_escribe_sobre_un_final_corrupto(client, seeded):
    _fill(client, seeded)
    with main_module.audit_log._path.open("a") as handle:
        handle.write("{esto no es json\n")
    from app.audit.log import AuditIntegrityError
    with pytest.raises(AuditIntegrityError):
        main_module.audit_log.append(actor_type="system", actor_id="x", action="a", category="process", resource_type="r", origin="o")


def test_escrituras_concurrentes_mantienen_una_cadena_valida(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl", tmp_path / "head.json", key="clave-de-prueba")

    def worker(n: int) -> None:
        for i in range(20):
            log.append(actor_type="system", actor_id=f"w{n}", action="process.task", category="process", resource_type="t", origin="process:test:1", channel="process")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    result = log.verify()
    assert result.valid and result.entries == 120


def test_la_clave_distinta_no_valida_la_cadena_de_otra(tmp_path):
    a = AuditLog(tmp_path / "a.jsonl", key="clave-1")
    a.append(actor_type="system", actor_id="x", action="process.task", category="process", resource_type="t", origin="o")
    assert AuditLog(tmp_path / "a.jsonl", key="clave-2").verify().valid is False
