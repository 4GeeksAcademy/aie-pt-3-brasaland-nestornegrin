"""Roles y Permisos (ticket feature/roles-permissions) — pruebas de aceptación de Legal contra la API REAL (llamadas HTTP directas,
sin pasar por la interfaz). Fuente de verdad: brasaland-BRIEFING.es.md (roles, departamentos, usuarios semilla y matriz de acceso).

Personas sembradas: Felipe (supervisor · Operaciones), Lucía (supervisor · Compras) — mismo rol, distinto departamento —,
Camila (empleado · Marketing), Jake (empleado · Formación y calidad) y Nicolás (admin · Tecnología).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

import app.main as main_module
from app.access.catalog import AccessCatalog
from app.access.models import DEPARTMENTS_SEED, ROLES_SEED
from app.auth.dependencies import get_current_user
from app.auth.repository import UserRepository
from conftest import make_access_user

REPORT_OPS = "Medellín Centro — Friday stockout"
REPORT_PROCUREMENT = "Carnes del Valle rate change"


def _report_id(client, headers, title: str) -> str:
    rows = client.get("/internal-reports", headers=headers).json()
    return next(r["id"] for r in rows if r["title"] == title)


def _user(email: str):
    return main_module.user_repository.get_by_email(email)


# ===================================================================== 1 · tres roles con jerarquía verificable
def test_el_catalogo_siembra_exactamente_los_roles_y_departamentos_del_briefing(client, seeded):
    admin = seeded("nicolas")
    roles = client.get("/roles", headers=admin).json()
    assert [(r["code"], r["name"], r["rank"]) for r in roles] == [(r["code"], r["name"], r["rank"]) for r in ROLES_SEED]
    departments = client.get("/departments", headers=admin).json()
    assert [(d["code"], d["name"]) for d in departments] == [(d["code"], d["name"]) for d in DEPARTMENTS_SEED]


def test_la_jerarquia_de_capacidades_es_estricta_y_verificable(client, seeded):
    roles = client.get("/roles", headers=seeded("nicolas")).json()
    assert len(roles) >= 3
    caps = {r["code"]: set(r["capabilities"]) for r in roles}
    assert caps["employee"] < caps["supervisor"] < caps["admin"]  # cada rango incluye al anterior y añade algo
    assert caps["employee"] == {"read", "create"}
    assert {"update", "approve"} <= caps["supervisor"] - caps["employee"]
    assert {"delete", "administer", "cross_department"} <= caps["admin"] - caps["supervisor"]
    assert "cross_department" not in caps["supervisor"]  # la visibilidad cruzada es del rol Admin


def test_los_usuarios_semilla_tienen_el_rol_y_el_departamento_del_briefing(client, seeded):
    expected = {"felipe.ops@brasaland.example": ("supervisor", "restaurant_operations"),
                "lucia.procurement@brasaland.example": ("supervisor", "procurement"),
                "camila.marketing@brasaland.example": ("employee", "marketing"),
                "jake.training@brasaland.example": ("employee", "training_quality"),
                "nicolas.admin@brasaland.example": ("admin", "technology")}
    for email, (role, department) in expected.items():
        user = _user(email)
        assert (user.role, user.department) == (role, department)


def test_auth_me_devuelve_rol_y_departamento(client, seeded):
    body = client.get("/auth/me", headers=seeded("felipe")).json()
    assert (body["role"], body["department"]) == ("supervisor", "restaurant_operations")
    assert set(body["capabilities"]) == {"read", "create", "update", "approve"}
    admin = client.get("/auth/me", headers=seeded("nicolas")).json()
    assert (admin["role"], admin["department"]) == ("admin", "technology")  # el Admin sigue teniendo departamento


# ===================================================================== 2 · 403 por rol insuficiente (llamada directa)
def test_empleado_en_una_actualizacion_solo_de_supervisor_recibe_403(client, seeded):
    camila = seeded("camila")
    response = client.put(f"/internal-reports/{_report_id(client, seeded('nicolas'), REPORT_OPS)}", headers=camila, json={"title": "x"})
    assert response.status_code == 403
    assert "supervisor" in response.json()["detail"]  # cuerpo explícito: dice qué rol hace falta
    assert response.headers["X-Access-Denied"] == "insufficient_role"


def test_empleado_no_puede_actualizar_aprobar_ni_eliminar_en_su_propio_departamento(client, seeded, make_headers):
    admin = seeded("nicolas")
    own = client.post("/internal-reports", headers=seeded("camila"), json={"title": "Campaña", "body": "Notas de marketing"})
    assert own.status_code == 201  # crear SÍ puede (Empleado: crear y leer su departamento)
    rid = own.json()["id"]
    camila = seeded("camila")
    assert client.get(f"/internal-reports/{rid}", headers=camila).status_code == 200
    assert client.put(f"/internal-reports/{rid}", headers=camila, json={"title": "otro"}).status_code == 403
    assert client.post(f"/internal-reports/{rid}/approve", headers=camila).status_code == 403
    assert client.delete(f"/internal-reports/{rid}", headers=camila).status_code == 403
    assert client.get(f"/internal-reports/{rid}", headers=admin).json()["title"] == "Campaña"  # nada cambió


def test_supervisor_en_endpoints_solo_admin_recibe_403(client, seeded):
    felipe = seeded("felipe")
    assert client.get("/roles", headers=felipe).status_code == 403
    assert client.get("/departments", headers=felipe).status_code == 403
    assert client.get("/users", headers=felipe).status_code == 403
    assert client.post("/roles", headers=felipe, json={"code": "x1", "name": "X", "label": "X", "rank": 9, "capabilities": ["read"]}).status_code == 403
    assert client.put("/roles/1", headers=felipe, json={"name": "Hack"}).status_code == 403
    assert client.post("/departments", headers=felipe, json={"code": "nuevo", "name": "N", "label": "N"}).status_code == 403
    camila = _user("camila.marketing@brasaland.example")
    assert client.patch(f"/users/{camila.id}/assignment", headers=felipe, json={"role_id": 3}).status_code == 403
    assert _user("camila.marketing@brasaland.example").role == "employee"  # no se escaló


def test_un_empleado_tampoco_administra_ni_elimina_usuarios(client, seeded):
    camila = seeded("camila")
    jake = _user("jake.training@brasaland.example")
    assert client.get("/roles", headers=camila).status_code == 403
    assert client.post("/users", headers=camila, json={"email": "nuevo@brasaland.example", "password": "ValidPass123"}).status_code == 403
    assert client.delete(f"/users/{jake.id}", headers=camila).status_code == 403
    assert client.get(f"/users/{jake.id}", headers=camila).status_code == 403  # ver a OTRA persona es administración
    assert client.get(f"/users/{_user('camila.marketing@brasaland.example').id}", headers=camila).status_code == 200  # la propia, sí


def test_no_se_puede_auto_escalar_el_rol_ni_activar_cuentas(client, seeded):
    camila = seeded("camila")
    cid = _user("camila.marketing@brasaland.example").id
    assert client.put(f"/users/{cid}", headers=camila, json={"role": "admin"}).status_code == 400  # campo no permitido (extra=forbid)
    assert client.patch(f"/users/{cid}/assignment", headers=camila, json={"role_id": 3}).status_code == 403
    assert client.put(f"/users/{cid}", headers=camila, json={"is_active": True}).status_code == 403
    assert _user("camila.marketing@brasaland.example").role == "employee"


# ===================================================================== 3 · mismo rol, distinto departamento
def test_felipe_no_puede_leer_el_reporte_de_compras_de_lucia_por_id(client, seeded):
    lucia_report = _report_id(client, seeded("lucia"), REPORT_PROCUREMENT)
    response = client.get(f"/internal-reports/{lucia_report}", headers=seeded("felipe"))
    assert response.status_code == 403
    assert response.headers["X-Access-Denied"] == "department_scope"
    assert "procurement" in response.json()["detail"]
    # …y es simétrico
    felipe_report = _report_id(client, seeded("felipe"), REPORT_OPS)
    assert client.get(f"/internal-reports/{felipe_report}", headers=seeded("lucia")).status_code == 403


def test_mismo_rol_distinto_departamento_no_puede_actualizar_ni_aprobar_ni_crear_fuera_de_su_alcance(client, seeded):
    felipe, lucia = seeded("felipe"), seeded("lucia")
    rid = _report_id(client, lucia, REPORT_PROCUREMENT)
    assert client.put(f"/internal-reports/{rid}", headers=felipe, json={"title": "manipulado"}).status_code == 403
    assert client.post(f"/internal-reports/{rid}/approve", headers=felipe).status_code == 403
    compras = main_module.access_catalog.get_department_by_code("procurement")["id"]
    assert client.post("/internal-reports", headers=felipe, json={"title": "t", "body": "b", "department_id": compras}).status_code == 403
    assert client.get(f"/internal-reports/{rid}", headers=lucia).json()["title"] == REPORT_PROCUREMENT  # intacto


def test_el_listado_departamental_devuelve_solo_el_departamento_del_llamante(client, seeded):
    felipe_rows = client.get("/internal-reports", headers=seeded("felipe")).json()
    assert [r["department"] for r in felipe_rows] == ["restaurant_operations"]  # alcance, no denegación silenciosa
    assert [r["title"] for r in felipe_rows] == [REPORT_OPS]
    lucia_rows = client.get("/internal-reports", headers=seeded("lucia")).json()
    assert [r["title"] for r in lucia_rows] == [REPORT_PROCUREMENT]
    assert client.get("/internal-reports?department=procurement", headers=seeded("felipe")).status_code == 403


def test_los_modulos_existentes_tambien_tienen_alcance_departamental(client, seeded):
    felipe, lucia, camila = seeded("felipe"), seeded("lucia"), seeded("camila")
    # Proveedores y tarifas = Compras; incidencias e inventario = Operaciones
    assert client.get("/api/suppliers", headers=lucia).status_code == 200
    assert client.get("/api/suppliers", headers=felipe).status_code == 403
    assert client.get("/api/incidents", headers=felipe).status_code == 200
    assert client.get("/api/incidents", headers=lucia).status_code == 403
    assert client.get("/api/incidents/summary", headers=camila).status_code == 403
    assert client.post("/api/incidents", headers=camila, json={"title": "t", "description": "d", "category": "Queja", "origin": "branch", "branch": "central"}).status_code == 403
    assert client.get("/telemetry/report", headers=lucia).status_code == 403  # Tecnología
    assert client.get("/reporting/inventory-performance/status", headers=camila).status_code == 403  # Operaciones


def test_supervisor_de_compras_modifica_proveedores_de_su_departamento_y_solo_el_admin_elimina(client, seeded):
    lucia, felipe, admin = seeded("lucia"), seeded("felipe"), seeded("nicolas")
    created = client.post("/api/suppliers", headers=lucia, json={"name": "Nuevo", "categories": ["Carnes"], "country": "CO", "rate": 3, "status": "Activo"})
    assert created.status_code == 201
    sid = created.json()["id"]
    assert client.patch(f"/api/suppliers/{sid}/rate", headers=lucia, json={"rate": 4}).status_code == 200
    assert client.patch(f"/api/suppliers/{sid}/rate", headers=felipe, json={"rate": 9}).status_code == 403  # mismo rol, otro departamento
    assert client.delete(f"/api/suppliers/{sid}?confirm=true", headers=lucia).status_code == 403  # eliminar es del Admin
    assert client.delete(f"/api/suppliers/{sid}?confirm=true", headers=admin).status_code == 204


# ===================================================================== 4 · rol y departamento son ejes independientes
def test_cambiar_solo_el_departamento_no_cambia_el_rol(client, seeded):
    admin, lucia = seeded("nicolas"), _user("lucia.procurement@brasaland.example")
    marketing = main_module.access_catalog.get_department_by_code("marketing")
    response = client.patch(f"/users/{lucia.id}/assignment", headers=admin, json={"department_id": marketing["id"]})
    assert response.status_code == 200
    body = response.json()
    assert (body["department"], body["role"]) == ("marketing", "supervisor")
    assert body["role_id"] == lucia.role_id  # el rol (y su rango) no se movió
    # y ahora Lucía ve Marketing y deja de ver Compras, conservando sus capacidades de Supervisor
    token = main_module.user_repository.get(lucia.id)
    assert (token.role, token.department) == ("supervisor", "marketing")


def test_cambiar_solo_el_rol_no_cambia_el_departamento(client, seeded):
    admin, felipe = seeded("nicolas"), _user("felipe.ops@brasaland.example")
    employee = main_module.access_catalog.get_role_by_code("employee")
    response = client.patch(f"/users/{felipe.id}/assignment", headers=admin, json={"role_id": employee["id"]})
    assert response.status_code == 200
    assert (response.json()["role"], response.json()["department"]) == ("employee", "restaurant_operations")
    assert response.json()["department_id"] == felipe.department_id


def test_degradar_el_rol_quita_capacidades_al_instante_sin_tocar_el_departamento(client, seeded):
    admin, felipe_headers = seeded("nicolas"), seeded("felipe")
    inc = client.post("/api/incidents", headers=felipe_headers, json={"title": "t", "description": "d", "category": "Queja", "origin": "branch", "branch": "central"}).json()
    assert client.patch(f"/api/incidents/{inc['id']}/status", headers=felipe_headers, json={"status": "in_progress"}).status_code == 200
    employee = main_module.access_catalog.get_role_by_code("employee")
    client.patch(f"/users/{_user('felipe.ops@brasaland.example').id}/assignment", headers=admin, json={"role_id": employee["id"]})
    # mismo token, ya como Empleado: puede leer su departamento pero no actualizar
    assert client.get("/api/incidents", headers=felipe_headers).status_code == 200
    assert client.patch(f"/api/incidents/{inc['id']}/status", headers=felipe_headers, json={"status": "resolved"}).status_code == 403


def test_asignacion_valida_ids_y_protege_al_ultimo_admin(client, seeded):
    admin, nicolas = seeded("nicolas"), _user("nicolas.admin@brasaland.example")
    assert client.patch(f"/users/{nicolas.id}/assignment", headers=admin, json={"role_id": 999}).status_code == 422
    assert client.patch(f"/users/{nicolas.id}/assignment", headers=admin, json={"department_id": 999}).status_code == 422
    assert client.patch("/users/9999/assignment", headers=admin, json={"role_id": 1}).status_code == 404
    employee = main_module.access_catalog.get_role_by_code("employee")
    assert client.patch(f"/users/{nicolas.id}/assignment", headers=admin, json={"role_id": employee["id"]}).status_code == 409
    assert client.delete(f"/users/{nicolas.id}", headers=admin).status_code == 409  # tampoco se puede eliminar


# ===================================================================== 5 · Admin: visibilidad cruzada y administración
def test_el_admin_ve_todos_los_departamentos_y_conserva_el_suyo(client, seeded):
    admin = seeded("nicolas")
    rows = client.get("/internal-reports", headers=admin).json()
    assert {r["department"] for r in rows} == {"restaurant_operations", "procurement"}
    assert client.get("/internal-reports?department=procurement", headers=admin).status_code == 200
    rid = _report_id(client, admin, REPORT_PROCUREMENT)
    assert client.get(f"/internal-reports/{rid}", headers=admin).status_code == 200
    assert client.get("/api/suppliers", headers=admin).status_code == 200 and client.get("/api/incidents", headers=admin).status_code == 200
    assert _user("nicolas.admin@brasaland.example").department == "technology"


def test_supervisor_aprueba_en_su_departamento_y_solo_el_admin_elimina(client, seeded):
    lucia, admin = seeded("lucia"), seeded("nicolas")
    rid = _report_id(client, lucia, REPORT_PROCUREMENT)
    assert client.put(f"/internal-reports/{rid}", headers=lucia, json={"body": "Aprobada la tarifa"}).status_code == 200
    approved = client.post(f"/internal-reports/{rid}/approve", headers=lucia)
    assert approved.status_code == 200 and approved.json()["approved_by"] == _user("lucia.procurement@brasaland.example").id
    assert client.delete(f"/internal-reports/{rid}", headers=lucia).status_code == 403
    assert client.delete(f"/internal-reports/{rid}", headers=admin).status_code == 204
    assert client.get(f"/internal-reports/{rid}", headers=admin).status_code == 404


def test_admin_crea_usuarios_con_rol_y_departamento_y_el_registro_publico_nace_sin_privilegios(client, seeded):
    admin = seeded("nicolas")
    roles = {r["code"]: r["id"] for r in client.get("/roles", headers=admin).json()}
    deps = {d["code"]: d["id"] for d in client.get("/departments", headers=admin).json()}
    created = client.post("/users", headers=admin, json={"email": "ashley@brasaland.example", "password": "ValidPass123", "name": "Ashley",
                                                         "role_id": roles["supervisor"], "department_id": deps["people_culture"]})
    assert created.status_code == 201
    ashley = _user("ashley@brasaland.example")
    assert (ashley.role, ashley.department) == ("supervisor", "people_culture")
    assert client.post("/users", json={"email": "x@brasaland.example", "password": "ValidPass123"}).status_code == 401  # ya no es público
    public = client.post("/auth/register", json={"email": "publico@example.com", "password": "ValidPass123"})
    assert public.status_code == 201
    nuevo = _user("publico@example.com")
    assert (nuevo.role, nuevo.department) == ("employee", None)


def test_un_usuario_sin_departamento_recibe_403_explicito_en_datos_departamentales(client, seeded, make_headers):
    sin_depto = make_headers("sin.depto@example.com", "supervisor", None)
    for path in ("/internal-reports", "/api/suppliers", "/api/incidents"):
        response = client.get(path, headers=sin_depto)
        assert response.status_code == 403, path
        assert "departamento" in response.json()["detail"]
    assert client.post("/internal-reports", headers=sin_depto, json={"title": "t", "body": "b"}).status_code == 403


def test_administracion_de_roles_y_departamentos(client, seeded):
    admin = seeded("nicolas")
    dep = client.post("/departments", headers=admin, json={"code": "finance", "name": "Finance", "label": "Finanzas", "responsible": "Ana"})
    assert dep.status_code == 201
    assert client.post("/departments", headers=admin, json={"code": "finance", "name": "F", "label": "F"}).status_code == 409
    assert client.put(f"/departments/{dep.json()['id']}", headers=admin, json={"responsible": "Luis"}).json()["responsible"] == "Luis"
    assert client.get("/departments/999", headers=admin).status_code == 404
    # rol nuevo intermedio (rango 4 no existe aún): debe respetar la jerarquía
    ok = client.post("/roles", headers=admin, json={"code": "director", "name": "Director", "label": "Director", "rank": 4,
                                                    "capabilities": ["read", "create", "update", "approve", "delete", "administer", "cross_department"]})
    assert ok.status_code == 201
    assert client.post("/roles", headers=admin, json={"code": "roto", "name": "R", "label": "R", "rank": 5, "capabilities": ["read"]}).status_code == 422  # rango mayor con menos capacidades
    assert client.post("/roles", headers=admin, json={"code": "dup", "name": "D", "label": "D", "rank": 2, "capabilities": ["read", "create", "update", "approve"]}).status_code == 409  # rango repetido
    assert client.post("/roles", headers=admin, json={"code": "raro", "name": "R", "label": "R", "rank": 6, "capabilities": ["volar"]}).status_code == 422
    renamed = client.put("/roles/1", headers=admin, json={"label": "Colaborador"})
    assert renamed.json()["label"] == "Colaborador" and renamed.json()["rank"] == 1
    assert client.put("/roles/1", headers=admin, json={"rank": 9}).status_code == 400  # el rango no se edita


def test_sin_sesion_todo_es_401_y_con_token_basura_tambien(client):
    for path in ("/roles", "/departments", "/internal-reports", "/users", "/api/suppliers", "/api/incidents"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers={"Authorization": "Bearer basura"}).status_code == 401, path


# ===================================================================== 6 · RFP: rol + departamento que decide
def test_aprobar_una_rfp_exige_ser_supervisor_del_departamento_que_decide(client, seeded):
    # Marketing Employee: ni rol; Supervisor de Operaciones aprobando marketing: departamento ajeno
    assert client.post("/rfp/tickets/1/approvals/marketing", headers=seeded("camila"), json={}).status_code == 403
    assert client.post("/rfp/tickets/1/approvals/marketing", headers=seeded("felipe"), json={}).status_code == 403
    assert client.post("/rfp/tickets/1/approvals/operaciones", headers=seeded("lucia"), json={}).status_code == 403
    # el Supervisor del departamento correcto pasa el control de acceso (después falla por otro motivo: no hay ticket / cuerpo)
    assert client.post("/rfp/tickets/1/approvals/operaciones", headers=seeded("felipe"), json={}).status_code not in (401, 403)


# ===================================================================== 7 · la verificación está CENTRALIZADA
PUBLIC_ROUTES = {("POST", "/auth/login"), ("POST", "/auth/register"), ("POST", "/auth/forgot-password"), ("POST", "/auth/reset-password"),
                 ("POST", "/telemetry/events")}  # login/registro/recuperación y la ingesta anónima de telemetría (sin datos de negocio)


def _dependency_calls(dependant):
    seen = [dependant.call]
    for sub in dependant.dependencies:
        seen.extend(_dependency_calls(sub))
    return seen


def test_toda_ruta_de_negocio_exige_sesion_via_dependencia_salvo_las_publicas(client):
    unprotected = []
    for route in main_module.app.routes:
        if not isinstance(route, APIRoute):
            continue
        calls = _dependency_calls(route.dependant)
        if get_current_user in calls:
            continue
        if any((m, route.path) in PUBLIC_ROUTES for m in route.methods):
            continue
        unprotected.append((sorted(route.methods), route.path))
    # El OpenAPI/docs de FastAPI no son APIRoute con dependant propio de negocio
    assert unprotected == [], f"Rutas sin la dependencia de sesión/permisos: {unprotected}"


def test_ninguna_ruta_decide_permisos_por_su_cuenta():
    """La lógica de acceso vive solo en app/access/permissions.py: ni `current_user.role ==` ni `UserRole.X` en las rutas."""
    root = Path(main_module.__file__).resolve().parent
    offenders = []
    for path in list(root.rglob("*.py")) + list((root.parent.parent / "reporting").rglob("*.py")):
        rel = path.relative_to(root.parent.parent) if root.parent.parent in path.parents else path
        if "access" in path.parts and path.name in ("permissions.py", "models.py", "seed.py", "catalog.py"):
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"\.role\s*(==|!=|in\b)|UserRole\.|\.rank\s*[<>=]", text) and path.name not in ("models.py",):
            offenders.append(str(rel))
    assert offenders == [], f"Comprobaciones de rol fuera de la dependencia central: {offenders}"


# ===================================================================== 8 · migración de cuentas anteriores
def test_las_cuentas_con_el_rol_plano_anterior_se_migran(tmp_path):
    from tinydb import TinyDB

    path = tmp_path / "users.json"
    legacy = TinyDB(path)
    for email, role in (("a@x.com", "user"), ("b@x.com", "manager"), ("c@x.com", "admin")):
        legacy.insert({"email": email, "hashed_password": "h", "is_active": True, "role": role, "created_at": "2026-01-01T00:00:00+00:00"})
    legacy.close()
    repository = UserRepository(path, AccessCatalog(tmp_path / "access.json"))
    got = {u.email: (u.role, u.department) for u in repository.list()}
    assert got == {"a@x.com": ("employee", None), "b@x.com": ("supervisor", None), "c@x.com": ("admin", None)}
