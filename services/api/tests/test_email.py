"""Pruebas del envío de email de restablecimiento — sin llamar nunca a la
API real de Resend."""

from unittest.mock import patch

import pytest

from app.auth import email as email_module


def test_build_reset_link_includes_the_token_and_the_frontend_url():
    link = email_module.build_reset_link("token-de-prueba")
    assert "token-de-prueba" in link
    assert link.startswith(email_module.FRONTEND_URL)


def test_send_password_reset_email_calls_resend_with_the_right_recipient_and_token():
    with (
        patch("app.auth.email.resend") as mock_resend,
        patch.object(email_module, "RESEND_API_KEY", "re_fake_para_tests"),
    ):
        email_module.send_password_reset_email("destinatario@example.com", "el-token")

    mock_resend.Emails.send.assert_called_once()
    payload = mock_resend.Emails.send.call_args[0][0]
    assert payload["to"] == ["destinatario@example.com"]
    assert "el-token" in payload["html"]


def test_send_password_reset_email_raises_when_the_api_key_is_missing():
    with patch.object(email_module, "RESEND_API_KEY", None):
        with pytest.raises(RuntimeError):
            email_module.send_password_reset_email("x@example.com", "un-token")
