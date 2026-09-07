"""POST /auth/forgot-password."""

from unittest.mock import patch


def test_forgot_password_existing_email_returns_200_and_sends_the_email(client, register_user):
    register_user(email="forgot@example.com", password="ValidPass123")

    with patch("app.auth.routes.send_password_reset_email") as mock_send:
        response = client.post("/auth/forgot-password", json={"email": "forgot@example.com"})

    assert response.status_code == 200
    mock_send.assert_called_once()
    assert mock_send.call_args[0][0] == "forgot@example.com"


def test_forgot_password_nonexistent_email_returns_the_identical_200(client, register_user):
    register_user(email="real@example.com", password="ValidPass123")

    with patch("app.auth.routes.send_password_reset_email"):
        real = client.post("/auth/forgot-password", json={"email": "real@example.com"})
        fake = client.post("/auth/forgot-password", json={"email": "fantasma@example.com"})

    assert real.status_code == fake.status_code == 200
    assert real.json() == fake.json()


def test_forgot_password_does_not_send_any_email_for_a_nonexistent_user(client):
    with patch("app.auth.routes.send_password_reset_email") as mock_send:
        client.post("/auth/forgot-password", json={"email": "nadie@example.com"})

    mock_send.assert_not_called()


def test_forgot_password_still_returns_200_when_the_email_provider_fails(client, register_user):
    """Un fallo de Resend (servicio externo) nunca debe convertirse en un 500
    ni delatar que el envío falló -- ver services/api/app/auth/routes.py."""
    register_user(email="failmail@example.com", password="ValidPass123")

    with patch("app.auth.routes.send_password_reset_email", side_effect=RuntimeError("Resend caído")):
        response = client.post("/auth/forgot-password", json={"email": "failmail@example.com"})

    assert response.status_code == 200
