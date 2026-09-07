"""GET /auth/me."""

from datetime import datetime, timedelta, timezone

from jose import jwt

from app.auth import security


def test_me_happy_path_returns_email_and_role(client, register_user, auth_headers):
    register_user(email="me@example.com", password="ValidPass123", name="Me User")
    headers = auth_headers(email="me@example.com", password="ValidPass123", register=False)

    response = client.get("/auth/me", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "me@example.com"
    assert body["role"] == "user"


def test_me_includes_the_profile_created_at_registration(client, register_user, auth_headers):
    register_user(email="profile@example.com", password="ValidPass123", name="Con Perfil")
    headers = auth_headers(email="profile@example.com", password="ValidPass123", register=False)

    response = client.get("/auth/me", headers=headers)

    assert response.json()["profile"]["name"] == "Con Perfil"


def test_me_without_a_token_returns_401(client):
    response = client.get("/auth/me")

    assert response.status_code == 401


def test_me_with_a_malformed_token_returns_401(client):
    response = client.get("/auth/me", headers={"Authorization": "Bearer esto-no-es-un-jwt"})

    assert response.status_code == 401


def test_me_with_an_expired_token_returns_401(client, register_user):
    user = register_user(email="expired@example.com", password="ValidPass123")
    expired_payload = {"sub": str(user["id"]), "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}
    expired_token = jwt.encode(expired_payload, security.JWT_SECRET_KEY, algorithm=security.JWT_ALGORITHM)

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {expired_token}"})

    assert response.status_code == 401


def test_me_for_a_deactivated_user_returns_401_even_with_a_valid_token(client, register_user):
    import app.main as main_module
    from app.auth.models import UserUpdate

    user = register_user(email="inactive@example.com", password="ValidPass123")
    token = security.create_access_token(user["id"])
    main_module.user_repository.update(user["id"], UserUpdate(is_active=False))

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
