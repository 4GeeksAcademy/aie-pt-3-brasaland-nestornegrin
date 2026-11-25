"""Fixtures compartidos para la batería de pruebas de la API de autenticación.

Las variables de entorno se fijan ANTES de importar app.main, porque
app/auth/security.py exige JWT_SECRET_KEY en el momento de importarse.

Los repositorios de auth (user_repository, profile_repository,
password_reset_repository) son singletons creados una vez al importar
app.main, apuntando a los ficheros TinyDB reales del proyecto. Para que cada
test arranque desde un estado limpio sin tocar esos ficheros ni depender del
orden de ejecución, el fixture autouse `_clean_database` trunca las tablas
en memoria de TinyDB antes de cada test.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Los tests escriben usuarios, incidencias y proveedores: se redirigen a una
# carpeta temporal (BRASALAND_DATA_DIR, ver app/database.py) para no tocar ni
# ensuciar los ficheros TinyDB de desarrollo. Se fuerza (no setdefault) para
# que ningún valor heredado del entorno rompa el aislamiento.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="brasaland-tests-")
os.environ["BRASALAND_DATA_DIR"] = _TEST_DATA_DIR
atexit.register(shutil.rmtree, _TEST_DATA_DIR, ignore_errors=True)

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-pytest-do-not-use-in-prod")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("RESEND_API_KEY", "re_test_placeholder")
os.environ.setdefault("EMAIL_FROM", "Brasaland <onboarding@resend.dev>")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")
os.environ.setdefault("CHAT_DB_PATH", ":memory:")

API_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = API_DIR.parent.parent
for path in (REPO_ROOT, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import app.main as main_module  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

DEFAULT_PASSWORD = "ValidPass123"


@pytest.fixture(autouse=True)
def _clean_database():
    main_module.internal_report_repository.truncate()
    main_module.federated_repository.truncate()
    main_module.audit_repository.truncate()
    main_module.user_repository._database.truncate()
    main_module.profile_repository._database.truncate()
    main_module.password_reset_repository._database.truncate()
    from app import security as app_security
    app_security.reset_rate_limits()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(main_module.app, raise_server_exceptions=False)


@pytest.fixture
def register_user(client: TestClient):
    """Registra un usuario y devuelve el UserResponse (dict) de la API."""

    def _register(email: str = "user@example.com", password: str = DEFAULT_PASSWORD, name: str = "Test User"):
        response = client.post("/auth/register", json={"email": email, "password": password, "name": name})
        assert response.status_code == 201, response.text
        return response.json()

    return _register


@pytest.fixture
def auth_headers(client: TestClient, register_user):
    """Registra (si hace falta) e inicia sesión, devolviendo el header Authorization listo para usar."""

    def _headers(email: str = "user@example.com", password: str = DEFAULT_PASSWORD, register: bool = True):
        if register:
            register_user(email=email, password=password)
        response = client.post("/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _headers


def make_access_user(client: TestClient, email: str, role: str = "employee", department: str | None = None,
                     password: str = DEFAULT_PASSWORD) -> dict:
    """Crea un usuario con el rol y el departamento indicados (por CÓDIGO, como en el BRIEFING) y devuelve sus
    cabeceras Authorization. Se crea por el repositorio (no por la API) para fijar los dos ejes de forma independiente."""
    from app.auth.security import hash_password

    catalog = main_module.access_catalog
    user = main_module.user_repository.get_by_email(email)
    if user is None:
        user = main_module.user_repository.create(
            email, hash_password(password), catalog.get_role_by_code(role)["id"],
            catalog.get_department_by_code(department)["id"] if department else None)
        main_module.profile_repository.create(user.id, email.split("@")[0])
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def make_headers(client: TestClient):
    """`make_headers("felipe@x.test", "supervisor", "restaurant_operations")` → {"Authorization": "Bearer …"}."""

    def _make(email: str, role: str = "employee", department: str | None = None):
        return make_access_user(client, email, role, department)

    return _make


@pytest.fixture
def seeded(client: TestClient):
    """Siembra los usuarios y reportes del BRIEFING y devuelve `headers(name)` por persona: felipe, lucia, camila, jake, nicolas."""
    from app.access.seed import seed_demo

    seed_demo(main_module.user_repository, main_module.profile_repository, main_module.access_catalog,
              main_module.internal_report_repository, password=DEFAULT_PASSWORD)
    emails = {"felipe": "felipe.ops@brasaland.example", "lucia": "lucia.procurement@brasaland.example",
              "camila": "camila.marketing@brasaland.example", "jake": "jake.training@brasaland.example",
              "nicolas": "nicolas.admin@brasaland.example"}

    def headers(name: str) -> dict:
        response = client.post("/auth/login", json={"email": emails[name], "password": DEFAULT_PASSWORD})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return headers


class StubUser:
    """Usuario falso para tests que sustituyen `get_current_user`: con todas las capacidades (Admin de Tecnología)."""

    def __init__(self, email: str = "stub@brasaland.test", role: str = "admin", department: str | None = "technology") -> None:
        caps = {"employee": ["read", "create"], "supervisor": ["read", "create", "update", "approve"],
                "admin": ["read", "create", "update", "approve", "delete", "administer", "cross_department"]}[role]
        self.id, self.email, self.role, self.department, self.capabilities, self.is_active = 999, email, role, department, caps, True
