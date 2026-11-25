"""Ticket security-hardening: cada prueba demuestra el ANTES (falla sobre `main`) y el DESPUÉS (pasa con la corrección).
Informe y evidencia: docs/security/security-hardening-audit.md, docs/security/evidence/hardening-*.txt."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from jose import jwt

import app.main as main_module
from conftest import make_access_user
from app import security as limits
from app.auth import security as auth_security

PASSWORD = "ValidPass123"


@pytest.fixture(autouse=True)
def _limits():
    limits.reset_rate_limits()
    yield
    limits.reset_rate_limits()


def from_ip(client: TestClient, ip: str) -> TestClient:
    """Mismo cliente de pruebas, pero la petición llega desde otra IP (para probar límites por IP/cuenta)."""
    other = TestClient(client.app, client=(ip, 50000))
    return other


def register(client, email: str, password: str = PASSWORD):
    return client.post("/auth/register", json={"email": email, "password": password, "name": "T"})


def login_token(client, email: str, password: str = PASSWORD) -> str:
    return client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def user_id(client, token: str) -> int:
    return next(u for u in range(1, 200) if client.get(f"/users/{u}", headers=bearer(token)).status_code == 200)


# ---------------------------------------------------------------- V1 · tokens vivos tras cambiar/restablecer la contraseña
def test_v1_un_token_robado_deja_de_valer_al_cambiar_la_contraseña(client):
    register(client, "v1@example.com")
    stolen = login_token(client, "v1@example.com")
    assert client.get("/auth/me", headers=bearer(stolen)).status_code == 200
    changed = client.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "NuevaClave456"}, headers=bearer(stolen))
    assert changed.status_code == 200
    assert client.get("/auth/me", headers=bearer(stolen)).status_code == 401  # antes: 200
    fresh = changed.json()["access_token"]  # la sesión legítima continúa con el token nuevo
    assert client.get("/auth/me", headers=bearer(fresh)).status_code == 200


def test_v1_un_token_robado_deja_de_valer_al_restablecer_la_contraseña(client):
    from datetime import datetime, timedelta, timezone

    created = register(client, "v1b@example.com").json()
    stolen = login_token(client, "v1b@example.com")
    raw = auth_security.generate_password_reset_token()
    main_module.password_reset_repository.create(created["id"], auth_security.hash_password_reset_token(raw), datetime.now(timezone.utc) + timedelta(minutes=5))
    assert client.post("/auth/reset-password", json={"token": raw, "new_password": "Restablecida789"}).status_code == 200
    assert client.get("/auth/me", headers=bearer(stolen)).status_code == 401


def test_v1_un_token_sin_huella_de_contraseña_no_se_acepta(client):
    created = register(client, "v1c@example.com").json()
    legacy = auth_security.create_access_token(created["id"])  # formato antiguo: sin `pwf`
    assert client.get("/auth/me", headers=bearer(legacy)).status_code == 401


def test_v1_el_websocket_del_chat_tambien_rechaza_el_token_revocado(client):
    from app.auth.ws import authenticate_ws_token

    register(client, "v1d@example.com")
    stolen = login_token(client, "v1d@example.com")
    assert authenticate_ws_token(stolen) is not None
    client.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "NuevaClave456"}, headers=bearer(stolen))
    assert authenticate_ws_token(stolen) is None


# ---------------------------------------------------------------- V2 · cambio de email sin reautenticar
def test_v2_cambiar_el_propio_email_exige_la_contraseña_actual(client):
    register(client, "v2@example.com")
    token = login_token(client, "v2@example.com")
    uid = user_id(client, token)
    sin = client.put(f"/users/{uid}", json={"email": "atacante@evil.example"}, headers=bearer(token))
    assert sin.status_code == 403  # antes: 200 (toma de cuenta con solo el token)
    mala = client.put(f"/users/{uid}", json={"email": "atacante@evil.example", "current_password": "no-es-esta-1"}, headers=bearer(token))
    assert mala.status_code == 403
    assert client.post("/auth/login", json={"email": "atacante@evil.example", "password": PASSWORD}).status_code == 401
    bien = client.put(f"/users/{uid}", json={"email": "nuevo@example.com", "current_password": PASSWORD}, headers=bearer(token))
    assert bien.status_code == 200 and bien.json()["email"] == "nuevo@example.com"


def test_v2_la_contraseña_de_confirmacion_nunca_se_guarda(client):
    register(client, "v2b@example.com")
    token = login_token(client, "v2b@example.com")
    uid = user_id(client, token)
    client.put(f"/users/{uid}", json={"email": "v2b-nuevo@example.com", "current_password": PASSWORD}, headers=bearer(token))
    stored = main_module.user_repository._database.get(doc_id=uid)
    assert "current_password" not in stored and PASSWORD not in str(stored)


def test_v2_adivinar_la_contraseña_via_cambio_de_email_tambien_se_limita(client):
    register(client, "v2c@example.com")
    token = login_token(client, "v2c@example.com")
    uid = user_id(client, token)
    codes = [client.put(f"/users/{uid}", json={"email": "x@evil.example", "current_password": f"mala-clave-{i}"}, headers=bearer(token)).status_code for i in range(8)]
    assert codes[:5] == [403] * 5 and 429 in codes[5:]


def test_v2_un_admin_puede_corregir_el_email_de_otro_usuario_sin_su_contraseña(client):
    created = register(client, "v2d@example.com").json()
    admin = make_access_user(client, "boss2@example.com", "admin", "technology")  # el Admin se crea por el catálogo de roles (Roles y permisos)
    assert client.put(f"/users/{created['id']}", json={"email": "corregido@example.com"}, headers=admin).status_code == 200


# ---------------------------------------------------------------- V3 · contraseña sin tope de longitud
def test_v3_una_contraseña_gigante_se_rechaza_como_dato_invalido_no_con_500(client):
    huge = "A1" + "a" * 100_000  # cabe en el cuerpo permitido, pero ninguna contraseña real mide tanto
    assert register(client, "v3@example.com", huge).status_code == 400  # validación (la API responde 400); antes: 500
    assert register(client, "v3-bis@example.com", "A1" + "a" * 5_000_000).status_code == 413  # y 5 MB ni se leen (V6)
    assert client.post("/auth/login", json={"email": "v3@example.com", "password": huge}).status_code == 400
    assert client.post("/auth/change-password", json={"current_password": huge, "new_password": "NuevaClave456"}).status_code == 401


def test_v3_verify_password_no_lanza_con_entradas_absurdas():
    hashed = auth_security.hash_password(PASSWORD)
    assert auth_security.verify_password("x" * 100_000, hashed) is False
    assert auth_security.verify_password(PASSWORD, "esto-no-es-un-hash") is False
    assert auth_security.verify_password(PASSWORD, hashed) is True


# ---------------------------------------------------------------- V4 · bloqueo de la cuenta de otro (DoS)
def test_v4_un_atacante_no_puede_bloquear_a_la_victima_desde_otra_ip(client):
    register(client, "victima@example.com")
    attacker, owner = from_ip(client, "203.0.113.7"), from_ip(client, "198.51.100.9")
    for _ in range(8):
        attacker.post("/auth/login", json={"email": "victima@example.com", "password": "adivinando"})
    assert attacker.post("/auth/login", json={"email": "victima@example.com", "password": PASSWORD}).status_code == 429  # el atacante sí queda bloqueado
    assert owner.post("/auth/login", json={"email": "victima@example.com", "password": PASSWORD}).status_code == 200  # antes: 429


def test_v4_la_fuerza_bruta_distribuida_sigue_frenada_por_el_tope_global_de_la_cuenta(client):
    register(client, "objetivo@example.com")
    codes = [from_ip(client, f"192.0.2.{i}").post("/auth/login", json={"email": "objetivo@example.com", "password": "mala"}).status_code for i in range(1, 60)]
    assert 429 in codes  # 50 fallos desde 50 IPs distintas agotan el tope global por cuenta


# ---------------------------------------------------------------- V5 · rate limiting en endpoints sensibles
def test_v5a_change_password_limita_los_intentos_con_contraseña_actual_erronea(client):
    register(client, "v5a@example.com")
    token = login_token(client, "v5a@example.com")
    codes = [client.post("/auth/change-password", json={"current_password": f"mala-{i}-xx", "new_password": "OtraClave789"}, headers=bearer(token)).status_code for i in range(8)]
    assert codes[:5] == [400] * 5 and codes[5:] == [429] * 3
    ok = client.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "OtraClave789"}, headers=bearer(token))
    assert ok.status_code == 429  # ni con la buena mientras dura el bloqueo
    assert "retry-after" in {k.lower() for k in ok.headers}


def test_v5b_reset_password_limita_el_canje_de_tokens(client):
    codes = [client.post("/auth/reset-password", json={"token": f"token-{i}", "new_password": "OtraClave789"}).status_code for i in range(14)]
    assert codes[:10] == [400] * 10 and codes[10:] == [429] * 4


def test_v5c_la_ingesta_anonima_de_telemetria_tiene_tope_por_ip(client):
    codes = [client.post("/telemetry/events", json={"events": []}).status_code for _ in range(130)]
    assert codes[:120] == [200] * 120 and 429 in codes[120:]
    assert from_ip(client, "203.0.113.50").post("/telemetry/events", json={"events": []}).status_code == 200  # otra IP no se ve afectada


def test_v5d_las_escrituras_criticas_tienen_tope_por_usuario(client):
    token = make_access_user(client, "writer@example.com", "admin", "procurement")["Authorization"].split()[1]
    body = {"name": "Proveedor", "categories": ["Carnes"], "country": "Colombia", "rate": 1.5, "status": "Activo"}
    responses = [client.post("/api/suppliers", json=body, headers=bearer(token)) for _ in range(34)]
    codes = [r.status_code for r in responses]
    assert codes[:30] == [201] * 30 and codes[30:] == [429] * 4
    for created in responses[:30]:  # solo se borra lo creado aquí: los demás tests comparten el catálogo
        main_module.supplier_repository.delete(str(created.json()["id"]))


def test_v5_los_limites_se_liberan_al_pasar_la_ventana():
    clock = [0.0]
    limiter = limits.RateLimiter(max_events=2, window_seconds=60, clock=lambda: clock[0])
    for _ in range(2):
        limiter.record("k")
    assert limiter.retry_after("k") > 0
    clock[0] = 61
    assert limiter.retry_after("k") == 0


# ---------------------------------------------------------------- V6 · cuerpo de petición sin tope
def test_v6_un_cuerpo_enorme_se_rechaza_con_413_antes_de_leerlo(client):
    huge = b"x" * (limits.MAX_BODY_BYTES + 1)
    assert client.post("/telemetry/events", content=huge, headers={"Content-Type": "application/json"}).status_code == 413  # antes: se leía entero
    assert client.post("/auth/login", content=huge, headers={"Content-Type": "application/json"}).status_code == 413


def test_v6_un_cuerpo_chunked_sin_content_length_tambien_se_corta(client):
    def chunks():
        for _ in range(4):
            yield b"x" * (limits.MAX_BODY_BYTES // 2)

    assert client.post("/telemetry/events", content=chunks(), headers={"Content-Type": "application/json"}).status_code == 413


def test_v6_el_csv_de_analisis_conserva_su_propio_tope_y_los_cuerpos_normales_pasan(client):
    token = make_access_user(client, "csvuser@example.com", "admin", "technology")["Authorization"].split()[1]
    big = b"a,b\n" + b"x" * (main_module.MAX_CSV_BYTES + 10)
    assert client.post("/api/incidents/analyze", headers=bearer(token), files={"file": ("big.csv", big, "text/csv")}).status_code == 413
    assert client.post("/telemetry/events", json={"events": []}).status_code == 200


# ---------------------------------------------------------------- Rotación de secretos (docs/security/secret-rotation.md)
def _forge(secret: str, user_id: int, hashed: str) -> str:
    import datetime as dt

    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": now + dt.timedelta(minutes=5), "pwf": auth_security.password_fingerprint(hashed)},
                      secret, algorithm=auth_security.JWT_ALGORITHM)


def test_rotacion_los_tokens_de_la_clave_anterior_siguen_valiendo_durante_la_transicion(client, monkeypatch):
    created = register(client, "rot@example.com").json()
    hashed = main_module.user_repository.get(created["id"]).hashed_password
    old_secret = "clave-anterior-" + "k" * 40
    old_token = _forge(old_secret, created["id"], hashed)
    assert client.get("/auth/me", headers=bearer(old_token)).status_code == 401  # clave desconocida: no vale
    monkeypatch.setattr(auth_security, "JWT_PREVIOUS_KEYS", [old_secret])  # = JWT_SECRET_KEY_PREVIOUS en el entorno
    assert client.get("/auth/me", headers=bearer(old_token)).status_code == 200  # transición sin cortes
    assert jwt.decode(login_token(client, "rot@example.com"), auth_security.JWT_SECRET_KEY, algorithms=["HS256"])  # lo nuevo se firma con la vigente
    monkeypatch.setattr(auth_security, "JWT_PREVIOUS_KEYS", [])  # fin de la transición: la clave vieja queda revocada
    assert client.get("/auth/me", headers=bearer(old_token)).status_code == 401


def test_rotacion_un_token_caducado_firmado_con_la_clave_anterior_no_se_acepta(client, monkeypatch):
    import datetime as dt

    created = register(client, "rot2@example.com").json()
    hashed = main_module.user_repository.get(created["id"]).hashed_password
    old_secret = "clave-anterior-" + "z" * 40
    monkeypatch.setattr(auth_security, "JWT_PREVIOUS_KEYS", [old_secret])
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    expired = jwt.encode({"sub": str(created["id"]), "exp": past, "pwf": auth_security.password_fingerprint(hashed)}, old_secret, algorithm="HS256")
    assert client.get("/auth/me", headers=bearer(expired)).status_code == 401


def test_rotacion_el_entorno_se_lee_como_lista_separada_por_comas():
    assert auth_security._split_keys(" a , b,, c ") == ["a", "b", "c"] and auth_security._split_keys(None) == []
