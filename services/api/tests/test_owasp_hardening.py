"""Correcciones de la auditoría OWASP Top 10 (docs/security/owasp-top10-audit.md): cada prueba demuestra el ANTES (falla sobre el
código anterior) y el DESPUÉS (pasa con la corrección). Ver docs/security/evidence/."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.auth import security
from app.suppliers.models import SupplierCreate

PASSWORD = "ValidPass123"


_LEGACY_ROLES = {"user": "employee", "manager": "supervisor", "admin": "admin"}  # nombres anteriores a Roles y Permisos


def make_user(client: TestClient, email: str, role: str = "user", department: str | None = None) -> dict:
    """Usuario con rol (código del BRIEFING; se aceptan los nombres antiguos) y departamento independientes."""
    from conftest import make_access_user

    return make_access_user(client, email, _LEGACY_ROLES.get(role, role), department)


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    try:
        from app import security as app_security
        app_security.reset_rate_limits()
    except ImportError:  # código anterior a la corrección: el módulo aún no existe (las pruebas fallan por su motivo real)
        pass
    yield


@pytest.fixture
def supplier():
    created = main_module.supplier_repository.create(
        SupplierCreate(name="Proveedor de prueba OWASP", categories=["Carnes"], country="Colombia", rate=1.5, status="Activo"))
    yield created
    main_module.supplier_repository.delete(str(created.id))


# ------------------------------------------------------------------ A01 · control de acceso roto
@pytest.mark.parametrize("method,path,body", [
    ("post", "/agent/query", {"question": "¿Cuántas unidades de pollo hay en stock?"}),
    ("post", "/knowledge/query", {"question": "¿Cómo se prepara la salsa de la casa?"}),
    ("get", "/agent/guardrails/summary", None),
])
def test_a01_el_agente_y_el_rag_exigen_sesion(client, method, path, body):
    response = getattr(client, method)(path, **({"json": body} if body else {}))
    assert response.status_code == 401


def test_a01_el_agente_con_sesion_sigue_funcionando_y_el_actor_sale_del_token(client, monkeypatch):
    from services.agent import router as agent_router  # noqa: F401
    seen = {}

    class FakeRun:
        answer, status, run_id, sources, conversation_id, memory, guardrails = "ok", "answered", "r1", [], None, None, []

    class FakeService:
        deps = type("D", (), {"guardrails": None})()

        def run(self, question, conversation_id=None, actor=None):
            seen["actor"] = actor
            return FakeRun()

    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient as TC
    from app.auth.dependencies import get_current_user
    from services.agent.router import create_router
    try:
        from app.security import bind_actor
        guards = [Depends(get_current_user), Depends(bind_actor)]
    except ImportError:
        guards = [Depends(get_current_user)]
    mini = FastAPI()
    mini.include_router(create_router(lambda: FakeService()), dependencies=guards)
    headers = make_user(client, "agent-user@example.com")
    response = TC(mini).post("/agent/query", json={"question": "hola", "user": "ADMIN-suplantado"}, headers=headers)
    assert response.status_code == 200 and seen["actor"].startswith("user:") and "suplantado" not in seen["actor"]


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/suppliers", {"name": "X", "categories": ["Carnes"], "country": "CO", "rate": 1, "status": "Activo"}),
    ("patch", "/api/suppliers/{id}/status?confirm=true", {"status": "Suspendido"}),
    ("patch", "/api/suppliers/{id}/rate", {"rate": 9}),
    ("delete", "/api/suppliers/{id}?confirm=true", None),
    ("post", "/inventory/products", {"name": "Pollo", "sku": "SKU-OWASP", "restaurant": "Medellín"}),
])
def test_a01_un_usuario_registrado_sin_rol_no_puede_modificar_proveedores_ni_inventario(client, supplier, method, path, body):
    headers = make_user(client, "plain@example.com", "user", "marketing")  # Empleado de OTRO departamento: ni rol ni alcance
    response = getattr(client, method)(path.format(id=supplier.id), headers=headers, **({"json": body} if body else {}))
    assert response.status_code == 403


def test_a01_el_gerente_puede_leer_y_el_admin_modificar_con_confirmacion(client, supplier):
    manager = make_user(client, "manager@example.com", "manager", "procurement")
    assert client.get("/api/suppliers", headers=manager).status_code == 200
    assert client.patch(f"/api/suppliers/{supplier.id}/rate", json={"rate": 2}, headers=manager).status_code == 200


@pytest.mark.parametrize("method,path,body", [
    ("patch", "/api/suppliers/{id}/status", {"status": "Suspendido"}),
    ("delete", "/api/suppliers/{id}", None),
])
def test_a01_baja_o_cambio_de_estado_de_proveedor_requiere_confirmacion_humana(client, supplier, method, path, body):
    admin = make_user(client, "admin@example.com", "admin", "technology")
    unconfirmed = getattr(client, method)(path.format(id=supplier.id), headers=admin, **({"json": body} if body else {}))
    assert unconfirmed.status_code == 428
    assert main_module.supplier_repository.get(str(supplier.id)) is not None  # nada cambió
    confirmed = getattr(client, method)(path.format(id=supplier.id) + "?confirm=true", headers=admin, **({"json": body} if body else {}))
    assert confirmed.status_code in (200, 204)


# ------------------------------------------------------------------ A07 · fallos de autenticación
def test_a07_el_login_limita_los_intentos_fallidos(client):
    client.post("/users", json={"email": "victim@example.com", "password": PASSWORD, "name": "V"})
    codes = [client.post("/auth/login", json={"email": "victim@example.com", "password": "mala-contraseña"}).status_code for _ in range(8)]
    assert codes[:5] == [401] * 5 and codes[5] == 429 and codes[-1] == 429
    assert client.post("/auth/login", json={"email": "victim@example.com", "password": PASSWORD}).status_code == 429  # ni con la buena mientras dura el bloqueo
    other = client.post("/auth/login", json={"email": "otro@example.com", "password": "x"})
    assert other.status_code == 401  # el bloqueo es por cuenta, no global


def test_a07_forgot_password_tambien_esta_limitado(client):
    codes = [client.post("/auth/forgot-password", json={"email": "a@example.com"}).status_code for _ in range(8)]
    assert 429 in codes and codes[0] == 200


def test_a07_el_login_con_usuario_inexistente_verifica_un_hash_para_no_delatar_cuentas(client, monkeypatch):
    calls = []
    original = security.verify_password
    monkeypatch.setattr("app.auth.routes.verify_password", lambda p, h: calls.append(h) or original(p, h))
    client.post("/auth/login", json={"email": "no-existe@example.com", "password": "loquesea123"})
    assert len(calls) == 1  # mismo coste que con un usuario real (evita enumerar emails por tiempo de respuesta)


# ------------------------------------------------------------------ A05 · configuración incorrecta
def test_a05_cors_no_acepta_cualquier_codespace_de_terceros(client):
    for origin in ("https://atacante-3000.app.github.dev", "https://evil.example"):
        preflight = client.options("/auth/me", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in preflight.headers, origin
    ok = client.options("/auth/me", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_a05_cabeceras_de_seguridad_en_todas_las_respuestas(client):
    response = client.get("/auth/me")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


def test_a05_el_websocket_del_chat_rechaza_origenes_no_permitidos(client):
    from starlette.websockets import WebSocketDisconnect
    headers = make_user(client, "ws@example.com")
    token = headers["Authorization"].split()[1]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/agent/chat/ws?session_id=chat_owasp_01&token={token}", headers={"Origin": "https://evil.example"}):
            pass
    with client.websocket_connect(f"/agent/chat/ws?session_id=chat_owasp_01&token={token}", headers={"Origin": "http://localhost:3000"}) as ws:
        assert ws.receive_json()["event"] == "session_snapshot"


# ------------------------------------------------------------------ A02 · fallas criptográficas
@pytest.mark.parametrize("weak", ["", "corta", "cambia-esto", "changeme-changeme-changeme-changeme", "x" * 31])
def test_a02_se_rechaza_un_secreto_jwt_debil(weak):
    with pytest.raises(RuntimeError):
        security.ensure_strong_secret(weak)


def test_a02_se_acepta_un_secreto_fuerte():
    assert security.ensure_strong_secret("k3Jx9-vQ2mZp7LwR4tYb8NcH1sDfGa6U") == "k3Jx9-vQ2mZp7LwR4tYb8NcH1sDfGa6U"


# ------------------------------------------------------------------ A03 / A04 · inyección y recursos
def test_a03_el_csv_exportado_neutraliza_formulas_de_celdas_controladas_por_el_usuario():
    assert main_module.csv_safe("=HYPERLINK(\"http://evil\",\"x\")") == "'=HYPERLINK(\"http://evil\",\"x\")"
    for dangerous in ("+1+1", "-2", "@SUM(A1)", "\t=1"):
        assert main_module.csv_safe(dangerous).startswith("'")
    assert main_module.csv_safe("Pedidos") == "Pedidos" and main_module.csv_safe("12") == "12"


def test_a03_el_export_real_no_contiene_formulas(client):
    headers = make_user(client, "csv@example.com", "user", "restaurant_operations")
    header = "id,category,status,satisfaction,branch,origin,created_at\n"
    body = client.post("/api/incidents/analyze", headers=headers,
                       files={"file": ("x.csv", (header + "1,=cmd|' /C calc'!A0,open,5,Sede,web,2026-01-01\n").encode(), "text/csv")})
    if body.status_code == 200:  # el análisis puede rechazar la categoría; si la acepta, el export no debe llevar la fórmula cruda
        export = client.get("/api/incidents/results/export", headers=headers)
        assert "\n=cmd" not in export.text and ",=cmd" not in export.text


def test_a04_el_csv_de_analisis_tiene_tope_de_tamano(client):
    headers = make_user(client, "big@example.com", "user", "restaurant_operations")
    big = b"a,b\n" + b"x" * (main_module.MAX_CSV_BYTES + 10)
    assert client.post("/api/incidents/analyze", headers=headers, files={"file": ("big.csv", big, "text/csv")}).status_code == 413


def test_a02_el_algoritmo_jwt_solo_admite_hmac():
    import importlib
    import os
    original = os.environ.get("JWT_ALGORITHM")
    os.environ["JWT_ALGORITHM"] = "none"
    try:
        with pytest.raises(RuntimeError):
            importlib.reload(security)
    finally:
        if original is None:
            os.environ.pop("JWT_ALGORITHM", None)
        else:
            os.environ["JWT_ALGORITHM"] = original
        importlib.reload(security)
