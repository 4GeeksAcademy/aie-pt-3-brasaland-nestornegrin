"""Autenticación federada (ticket feature/federated-auth) contra la API REAL, con un Google SIMULADO (sin red ni credenciales).

Reglas del BRIEFING que se verifican aquí:
  · el login federado SOLO entra en cuentas ya vinculadas y NUNCA crea una cuenta;
  · vincular solo se puede desde una sesión ya iniciada;
  · una identidad de Google no puede estar en dos usuarios;
  · desvincular avisa/rechaza si es el único método de acceso;
  · vinculación, desvinculación y login federado (éxito y rechazo) quedan auditados;
  · OAuth valida `state` (un solo uso, atado al flujo y al usuario) y `redirect_uri` (lista blanca exacta).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from jose import jwt

import app.main as main_module
from app.auth.security import JWT_ALGORITHM, JWT_SECRET_KEY, hash_password
from app.federated.oauth import ExternalIdentity, OAuthError
from app.federated.routes import get_oauth_provider
from app.federated.seed import UNKNOWN_IDENTITY, USERS_SEED, seed_federated_demo
from conftest import DEFAULT_PASSWORD, make_access_user

REDIRECT = "http://localhost:3000/auth/callback/google"
CAMILA, GUEST = "camila.points@brasaland.example", "guest.unlinked@brasaland.example"

# `code` que devolvería Google → identidad. «code-unknown» es el fixture del login rechazado.
GOOGLE_IDENTITIES = {
    "code-camila": ("google-sub-camila-001", CAMILA),
    "code-guest": ("google-sub-guest-777", GUEST),
    "code-unknown": (UNKNOWN_IDENTITY["provider_user_id"], "nadie@gmail.example"),
    "code-other": ("google-sub-other-555", "otra@gmail.example"),
}


class FakeGoogle:
    name = "google"

    def is_configured(self) -> bool:
        return True

    def authorization_url(self, state: str, redirect_uri: str) -> str:
        return f"https://accounts.example/auth?state={state}&redirect_uri={redirect_uri}"

    def exchange_code(self, code: str, redirect_uri: str) -> ExternalIdentity:
        if code not in GOOGLE_IDENTITIES:
            raise OAuthError("código inválido")
        sub, email = GOOGLE_IDENTITIES[code]
        return ExternalIdentity("google", sub, email, True)


@pytest.fixture(autouse=True)
def google(monkeypatch):
    monkeypatch.setenv("OAUTH_REDIRECT_URI", REDIRECT)
    monkeypatch.setenv("OAUTH_ALLOWED_REDIRECT_URIS", "http://localhost:3000/other/callback")
    monkeypatch.delenv("FEDERATED_AUTH_ENABLED", raising=False)
    main_module.app.dependency_overrides[get_oauth_provider] = lambda: FakeGoogle()
    yield
    main_module.app.dependency_overrides.pop(get_oauth_provider, None)


@pytest.fixture
def seeded_clients(client):
    seed_federated_demo(main_module.user_repository, main_module.profile_repository, main_module.federated_repository, password=DEFAULT_PASSWORD)


def password_login(client, email: str) -> dict:
    response = client.post("/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def state_from(response) -> str:
    assert response.status_code == 200, response.text
    return parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]


def start_login(client, redirect_uri: str | None = None):
    return client.post("/auth/federated/google/login/start", json={"redirect_uri": redirect_uri} if redirect_uri else {})


def start_link(client, headers, redirect_uri: str | None = None):
    return client.post("/auth/federated/google/link/start", headers=headers, json={"redirect_uri": redirect_uri} if redirect_uri else {})


def login_with(client, code: str, redirect_uri: str = REDIRECT):
    state = state_from(start_login(client, redirect_uri))
    return client.post("/auth/federated/google/login/complete", json={"code": code, "state": state, "redirect_uri": redirect_uri})


def link_with(client, headers, code: str, redirect_uri: str = REDIRECT):
    state = state_from(start_link(client, headers, redirect_uri))
    return client.post("/auth/federated/google/link/complete", headers=headers, json={"code": code, "state": state, "redirect_uri": redirect_uri})


def audit(event: str | None = None):
    return main_module.audit_repository.list(event=event)


def user_count() -> int:
    return len(main_module.user_repository._database.all())


# ===================================================================== 1 · el login federado NO crea cuentas
def test_login_con_google_no_vinculado_se_rechaza_y_no_crea_cuenta(client, seeded_clients):
    before = user_count()
    response = login_with(client, "code-unknown")
    assert response.status_code == 403
    assert response.headers["X-Federated-Error"] == "not_linked"
    assert "Regístrate primero" in response.json()["detail"]  # mensaje claro que invita a registrarse
    assert "access_token" not in response.text
    assert user_count() == before  # ninguna cuenta nueva (ni con puntos a cero)
    assert main_module.user_repository.get_by_email("nadie@gmail.example") is None
    assert main_module.profile_repository._database.all().__len__() == before


def test_el_rechazo_queda_auditado_sin_usuario(client, seeded_clients):
    login_with(client, "code-unknown")
    (record,) = audit("federated_login_rejected")
    assert (record.user_id, record.provider, record.provider_user_id) == (None, "google", UNKNOWN_IDENTITY["provider_user_id"])
    assert record.timestamp <= datetime.now(timezone.utc)


def test_login_federado_con_cuenta_vinculada_entra_y_se_audita(client, seeded_clients):
    response = login_with(client, "code-camila")
    assert response.status_code == 200
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert client.get("/auth/me", headers=headers).json()["email"] == CAMILA
    (record,) = audit("federated_login_success")
    assert (record.user_id, record.provider_user_id) == (main_module.user_repository.get_by_email(CAMILA).id, "google-sub-camila-001")


def test_la_sesion_federada_tiene_la_misma_caducidad_que_la_tradicional(client, seeded_clients):
    federated = login_with(client, "code-camila").json()["access_token"]
    traditional = password_login(client, CAMILA)["Authorization"].split()[1]
    f, t = (jwt.decode(x, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM]) for x in (federated, traditional))
    assert set(f) == set(t) == {"sub", "exp"}
    assert abs(f["exp"] - t["exp"]) <= 5
    assert f["exp"] - datetime.now(timezone.utc).timestamp() <= 30 * 60 + 5  # ACCESS_TOKEN_EXPIRE_MINUTES


def test_la_sesion_federada_se_revoca_igual_que_la_tradicional(client, seeded_clients):
    token = {"Authorization": f"Bearer {login_with(client, 'code-camila').json()['access_token']}"}
    admin = make_access_user(client, "admin@example.com", "admin", "technology")
    camila_id = main_module.user_repository.get_by_email(CAMILA).id
    assert client.put(f"/users/{camila_id}", headers=admin, json={"is_active": False}).status_code == 200
    assert client.get("/auth/me", headers=token).status_code == 401  # cuenta desactivada: la sesión federada deja de valer
    rejected = login_with(client, "code-camila")
    assert rejected.status_code == 403 and rejected.headers["X-Federated-Error"] == "inactive"
    assert audit("federated_login_rejected")[-1].user_id == camila_id


# ===================================================================== 2 · vincular SOLO desde una sesión autenticada
def test_vincular_exige_sesion_iniciada(client, seeded_clients):
    assert client.post("/auth/federated/google/link/start", json={}).status_code == 401
    assert client.post("/auth/federated/google/link/complete", json={"code": "code-guest", "state": "x", "redirect_uri": REDIRECT}).status_code == 401
    assert client.get("/auth/federated").status_code == 401
    assert client.delete("/auth/federated/google").status_code == 401
    assert client.post("/auth/federated/google/link/start", json={}, headers={"Authorization": "Bearer basura"}).status_code == 401


def test_el_login_no_puede_usarse_para_vincular_ni_al_reves(client, seeded_clients):
    guest = password_login(client, GUEST)
    login_state = state_from(start_login(client))
    # un `state` de LOGIN no sirve para vincular…
    assert client.post("/auth/federated/google/link/complete", headers=guest, json={"code": "code-guest", "state": login_state, "redirect_uri": REDIRECT}).status_code == 400
    # …ni uno de VINCULAR para entrar
    link_state = state_from(start_link(client, guest))
    assert client.post("/auth/federated/google/login/complete", json={"code": "code-camila", "state": link_state, "redirect_uri": REDIRECT}).status_code == 400
    assert main_module.federated_repository.find("google", "google-sub-guest-777") is None


def test_vincular_desde_el_perfil_confirma_el_proveedor_y_se_audita(client, seeded_clients):
    guest = password_login(client, GUEST)
    before = client.get("/auth/federated", headers=guest).json()
    assert before["providers"] == [{"provider": "google", "linked": False, "email_at_link_time": None, "linked_at": None}]
    response = link_with(client, guest, "code-guest")
    assert response.status_code == 200
    body = response.json()
    assert body["account"]["linked"] is True and body["account"]["provider"] == "google"
    assert GUEST in body["message"]  # confirma qué cuenta quedó asociada
    assert body["accounts"]["access_methods"] == 2  # contraseña + Google
    (record,) = audit("federated_link")
    assert (record.user_id, record.provider_user_id) == (main_module.user_repository.get_by_email(GUEST).id, "google-sub-guest-777")
    assert login_with(client, "code-guest").status_code == 200  # y a partir de ahí Google sirve para entrar


def test_se_guarda_solo_el_vinculo_sin_tokens(client, seeded_clients):
    link_with(client, password_login(client, GUEST), "code-guest")
    row = main_module.federated_repository._identities.all()[-1]
    assert set(row) == {"user_id", "provider", "provider_user_id", "email_at_link_time", "linked_at"}
    assert set(audit()[0].model_dump()) == {"id", "event", "timestamp", "user_id", "provider", "provider_user_id", "ip"}


# ===================================================================== 3 · una identidad NO puede estar en dos cuentas
def test_una_identidad_de_google_no_se_puede_vincular_a_dos_usuarios(client, seeded_clients):
    guest = password_login(client, GUEST)
    taken = link_with(client, guest, "code-camila")  # el `sub` de Camila ya es suyo
    assert taken.status_code == 409
    assert "otro usuario" in taken.json()["detail"]
    assert main_module.federated_repository.find("google", "google-sub-camila-001").user_id == main_module.user_repository.get_by_email(CAMILA).id
    assert main_module.federated_repository.for_user(main_module.user_repository.get_by_email(GUEST).id) == []
    assert audit("federated_link") == []  # no se audita un vínculo que no existió


def test_un_usuario_no_acumula_dos_cuentas_del_mismo_proveedor(client, seeded_clients):
    guest = password_login(client, GUEST)
    assert link_with(client, guest, "code-guest").status_code == 200
    assert link_with(client, guest, "code-other").status_code == 409


def test_la_unicidad_se_garantiza_en_el_repositorio(seeded_clients):
    from app.federated.repository import IdentityAlreadyLinked

    guest = main_module.user_repository.get_by_email(GUEST)
    with pytest.raises(IdentityAlreadyLinked):
        main_module.federated_repository.link(guest.id, "google", "google-sub-camila-001", GUEST)


# ===================================================================== 4 · desvincular y el «único método de acceso»
def test_desvincular_funciona_se_audita_y_deja_de_servir_para_entrar(client, seeded_clients):
    camila = password_login(client, CAMILA)
    response = client.delete("/auth/federated/google", headers=camila)
    assert response.status_code == 200
    assert response.json()["accounts"]["providers"][0]["linked"] is False
    (record,) = audit("federated_unlink")
    assert (record.user_id, record.provider_user_id) == (main_module.user_repository.get_by_email(CAMILA).id, "google-sub-camila-001")
    assert login_with(client, "code-camila").status_code == 403  # ya no está vinculada → rechazado


def test_no_se_puede_desvincular_el_unico_metodo_de_acceso(client, seeded_clients):
    only_google = main_module.user_repository.create("solo.google@brasaland.example", "")  # sin contraseña
    main_module.profile_repository.create(only_google.id, "Solo Google")
    main_module.federated_repository.link(only_google.id, "google", "google-sub-solo-1", "solo.google@brasaland.example")
    token = {"Authorization": f"Bearer {login_with_sub(client, 'google-sub-solo-1')}"}
    accounts = client.get("/auth/federated", headers=token).json()
    assert (accounts["has_password"], accounts["access_methods"]) == (False, 1)  # la interfaz usa esto para avisar
    refused = client.delete("/auth/federated/google", headers=token)
    assert refused.status_code == 409 and "único método" in refused.json()["detail"]
    assert main_module.federated_repository.find("google", "google-sub-solo-1") is not None
    assert audit("federated_unlink") == []


def login_with_sub(client, sub: str) -> str:
    GOOGLE_IDENTITIES["code-dynamic"] = (sub, "x@gmail.example")
    return login_with(client, "code-dynamic").json()["access_token"]


def test_una_cuenta_solo_federada_no_entra_por_contrasena_ni_rompe_el_login(client, seeded_clients):
    main_module.user_repository.create("solo.google@brasaland.example", "")
    for password in ("", "cualquiera123", DEFAULT_PASSWORD):
        response = client.post("/auth/login", json={"email": "solo.google@brasaland.example", "password": password})
        assert response.status_code in (401, 422), response.text  # nunca un 500


def test_cambiar_contrasena_sin_tener_una_da_un_mensaje_claro(client, seeded_clients):
    only_google = main_module.user_repository.create("solo.google@brasaland.example", "")
    main_module.federated_repository.link(only_google.id, "google", "google-sub-solo-2", "solo.google@brasaland.example")
    token = {"Authorization": f"Bearer {login_with_sub(client, 'google-sub-solo-2')}"}
    response = client.post("/auth/change-password", headers=token, json={"current_password": "ValidPass123", "new_password": "OtraClave456"})
    assert response.status_code == 400 and "no tiene contraseña" in response.json()["detail"]


def test_desvincular_algo_que_no_esta_vinculado_es_404(client, seeded_clients):
    assert client.delete("/auth/federated/google", headers=password_login(client, GUEST)).status_code == 404


def test_eliminar_a_un_usuario_libera_su_identidad(client, seeded_clients):
    admin = make_access_user(client, "admin@example.com", "admin", "technology")
    camila_id = main_module.user_repository.get_by_email(CAMILA).id
    assert client.delete(f"/users/{camila_id}", headers=admin).status_code == 204
    assert main_module.federated_repository.find("google", "google-sub-camila-001") is None  # sin vínculos huérfanos
    assert login_with(client, "code-camila").status_code == 403


# ===================================================================== 5 · OAuth: `state`
def test_el_state_es_de_un_solo_uso(client, seeded_clients):
    state = state_from(start_login(client))
    payload = {"code": "code-camila", "state": state, "redirect_uri": REDIRECT}
    assert client.post("/auth/federated/google/login/complete", json=payload).status_code == 200
    replay = client.post("/auth/federated/google/login/complete", json=payload)
    assert replay.status_code == 400  # repetir el callback no sirve


@pytest.mark.parametrize("state", ["inventado", "x" * 40, "../../etc"])
def test_un_state_desconocido_se_rechaza(client, seeded_clients, state):
    response = client.post("/auth/federated/google/login/complete", json={"code": "code-camila", "state": state, "redirect_uri": REDIRECT})
    assert response.status_code == 400
    assert audit("federated_login_success") == []


def test_el_state_de_un_usuario_no_sirve_a_otro(client, seeded_clients):
    guest = password_login(client, GUEST)
    attacker = make_access_user(client, "atacante@example.com", "employee", None)
    state = state_from(start_link(client, guest))
    # el atacante intenta completar el vínculo con el `state` que se emitió para otra sesión
    stolen = client.post("/auth/federated/google/link/complete", headers=attacker, json={"code": "code-other", "state": state, "redirect_uri": REDIRECT})
    assert stolen.status_code == 400
    assert main_module.federated_repository.find("google", "google-sub-other-555") is None


def test_un_state_caducado_se_rechaza(client, seeded_clients):
    state = state_from(start_login(client))
    row = main_module.federated_repository._states.all()[0]
    main_module.federated_repository._states.update({"expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}, doc_ids=[row.doc_id])
    assert client.post("/auth/federated/google/login/complete", json={"code": "code-camila", "state": state, "redirect_uri": REDIRECT}).status_code == 400


# ===================================================================== 6 · OAuth: `redirect_uri` (lista blanca exacta)
@pytest.mark.parametrize("uri", ["http://evil.example/auth/callback/google", REDIRECT + "/", REDIRECT + "/extra", REDIRECT.replace("http", "https"),
                                 "http://localhost:3000/auth/callback/google?x=1", "javascript:alert(1)"])
def test_un_redirect_uri_fuera_de_la_lista_blanca_se_rechaza_al_iniciar(client, seeded_clients, uri):
    assert start_login(client, uri).status_code == 400
    assert start_link(client, password_login(client, GUEST), uri).status_code == 400
    assert main_module.federated_repository._states.all() == []  # ni siquiera se emitió un state


def test_el_callback_con_otro_redirect_uri_se_rechaza(client, seeded_clients):
    state = state_from(start_login(client, REDIRECT))
    # otro URI de la lista blanca, pero distinto al del flujo: se rechaza
    other = client.post("/auth/federated/google/login/complete", json={"code": "code-camila", "state": state, "redirect_uri": "http://localhost:3000/other/callback"})
    assert other.status_code == 400
    state = state_from(start_login(client, REDIRECT))
    evil = client.post("/auth/federated/google/login/complete", json={"code": "code-camila", "state": state, "redirect_uri": "http://evil.example/cb"})
    assert evil.status_code == 400


def test_un_segundo_redirect_uri_de_la_lista_blanca_es_valido(client, seeded_clients):
    assert login_with(client, "code-camila", "http://localhost:3000/other/callback").status_code == 200


def test_sin_redirect_uri_configurado_nada_es_valido(client, seeded_clients, monkeypatch):
    monkeypatch.delenv("OAUTH_REDIRECT_URI")
    monkeypatch.delenv("OAUTH_ALLOWED_REDIRECT_URIS")
    assert start_login(client).status_code == 400


# ===================================================================== 7 · disponibilidad (tablets compartidas) y proveedores
def test_el_interruptor_desactiva_el_login_federado_en_dispositivos_compartidos(client, seeded_clients, monkeypatch):
    monkeypatch.setenv("FEDERATED_AUTH_ENABLED", "false")
    assert client.get("/auth/federated/providers").json() == {"enabled": False, "providers": [{"provider": "google", "configured": False}]}
    assert start_login(client).status_code == 403
    assert client.post("/auth/federated/google/login/complete", json={"code": "code-camila", "state": "x", "redirect_uri": REDIRECT}).status_code == 403


def test_el_listado_publico_de_proveedores(client):
    body = client.get("/auth/federated/providers").json()
    assert body["enabled"] is True and body["providers"][0]["provider"] == "google"


def test_un_proveedor_no_soportado_es_404(client, seeded_clients):
    main_module.app.dependency_overrides.pop(get_oauth_provider)
    assert client.post("/auth/federated/apple/login/start", json={}).status_code == 404
    main_module.app.dependency_overrides[get_oauth_provider] = lambda: FakeGoogle()


def test_google_real_sin_credenciales_responde_503_claro(client, seeded_clients, monkeypatch):
    main_module.app.dependency_overrides.pop(get_oauth_provider)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    response = start_login(client)
    assert response.status_code == 503 and "no está configurado" in response.json()["detail"]
    main_module.app.dependency_overrides[get_oauth_provider] = lambda: FakeGoogle()


def test_la_url_real_de_google_lleva_state_y_redirect_uri(monkeypatch):
    from app.federated.oauth import GoogleProvider

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
    query = parse_qs(urlparse(GoogleProvider().authorization_url("abc123", REDIRECT)).query)
    assert query["state"] == ["abc123"] and query["redirect_uri"] == [REDIRECT] and query["response_type"] == ["code"]
    assert query["client_id"] == ["cid.apps.googleusercontent.com"] and "client_secret" not in query


# ===================================================================== 8 · auditoría consultable solo por Admin
def test_la_auditoria_solo_la_consulta_un_admin(client, seeded_clients):
    login_with(client, "code-unknown")
    login_with(client, "code-camila")
    admin = make_access_user(client, "admin@example.com", "admin", "technology")
    events = client.get("/audit/events", headers=admin).json()
    assert {e["event"] for e in events} == {"federated_login_rejected", "federated_login_success"}
    assert client.get("/audit/events?event=federated_login_rejected", headers=admin).json()[0]["user_id"] is None
    employee = make_access_user(client, "emp@example.com", "employee", "marketing")
    assert client.get("/audit/events", headers=employee).status_code == 403
    assert client.get("/audit/events").status_code == 401


# ===================================================================== 9 · datos semilla
def test_la_semilla_crea_un_cliente_vinculado_y_otro_sin_vincular(client):
    assert seed_federated_demo(main_module.user_repository, main_module.profile_repository, main_module.federated_repository, password=DEFAULT_PASSWORD) == 2
    assert seed_federated_demo(main_module.user_repository, main_module.profile_repository, main_module.federated_repository, password=DEFAULT_PASSWORD) == 0  # idempotente
    camila = main_module.user_repository.get_by_email(USERS_SEED[0]["email"])
    guest = main_module.user_repository.get_by_email(USERS_SEED[1]["email"])
    assert [i.provider_user_id for i in main_module.federated_repository.for_user(camila.id)] == ["google-sub-camila-001"]
    assert main_module.federated_repository.for_user(guest.id) == []
    assert (camila.role, camila.department) == ("employee", None)
