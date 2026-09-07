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

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-pytest-do-not-use-in-prod")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("RESEND_API_KEY", "re_test_placeholder")
os.environ.setdefault("EMAIL_FROM", "Brasaland <onboarding@resend.dev>")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")

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
    main_module.user_repository._database.truncate()
    main_module.profile_repository._database.truncate()
    main_module.password_reset_repository._database.truncate()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(main_module.app, raise_server_exceptions=False)


@pytest.fixture
def register_user(client: TestClient):
    """Registra un usuario y devuelve el UserResponse (dict) de la API."""

    def _register(email: str = "user@example.com", password: str = DEFAULT_PASSWORD, name: str = "Test User"):
        response = client.post("/users", json={"email": email, "password": password, "name": name})
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
