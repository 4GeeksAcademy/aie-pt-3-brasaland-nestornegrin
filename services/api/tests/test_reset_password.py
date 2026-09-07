"""POST /auth/reset-password."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch


def _get_reset_token(client, email: str) -> str:
    """Dispara /auth/forgot-password e intercepta el token real que se
    habría enviado por email, para poder usarlo en la prueba."""
    captured: dict[str, str] = {}

    def _capture(_to_email: str, token: str) -> None:
        captured["token"] = token

    with patch("app.auth.routes.send_password_reset_email", side_effect=_capture):
        client.post("/auth/forgot-password", json={"email": email})
    return captured["token"]


def test_reset_password_happy_path_changes_the_password(client, register_user):
    register_user(email="reset@example.com", password="OldPass123")
    token = _get_reset_token(client, "reset@example.com")

    response = client.post("/auth/reset-password", json={"token": token, "new_password": "NewPass456"})

    assert response.status_code == 200
    old_login = client.post("/auth/login", json={"email": "reset@example.com", "password": "OldPass123"})
    new_login = client.post("/auth/login", json={"email": "reset@example.com", "password": "NewPass456"})
    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_reset_password_token_cannot_be_used_twice(client, register_user):
    register_user(email="reuse@example.com", password="OldPass123")
    token = _get_reset_token(client, "reuse@example.com")
    client.post("/auth/reset-password", json={"token": token, "new_password": "NewPass456"})

    response = client.post("/auth/reset-password", json={"token": token, "new_password": "OtraVez789"})

    assert response.status_code == 400


def test_reset_password_invalid_token_returns_400(client):
    response = client.post("/auth/reset-password", json={"token": "token-que-nunca-existio", "new_password": "NewPass456"})

    assert response.status_code == 400


def test_reset_password_expired_token_returns_400(client, register_user):
    import app.main as main_module
    from app.auth.security import generate_password_reset_token, hash_password_reset_token

    user = register_user(email="expiredreset@example.com", password="OldPass123")
    raw_token = generate_password_reset_token()
    expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    main_module.password_reset_repository.create(user["id"], hash_password_reset_token(raw_token), expired_at)

    response = client.post("/auth/reset-password", json={"token": raw_token, "new_password": "NewPass456"})

    assert response.status_code == 400
