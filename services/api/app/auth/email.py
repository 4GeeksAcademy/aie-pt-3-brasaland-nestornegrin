"""Envío de emails transaccionales (Resend) para el flujo de contraseña."""

import os

import resend
from dotenv import load_dotenv

from .security import PASSWORD_RESET_TOKEN_EXPIRE_MINUTES

load_dotenv()

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Brasaland <onboarding@resend.dev>")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3001")


def build_reset_link(token: str) -> str:
    return f"{FRONTEND_URL.rstrip('/')}/reset-password?token={token}"


def send_password_reset_email(to_email: str, token: str, idempotency_key: str | None = None) -> None:
    """Envía el email de restablecimiento con Resend.

    Lanza RuntimeError si falta configuración. La llama el WORKER de la cola (services/async_tasks/email_tasks.py), no la petición HTTP:
    si falla, la tarea se reintenta con backoff y, agotados los reintentos, queda en la dead-letter queue.
    `idempotency_key` viaja a Resend, que descarta un segundo envío con la misma clave (defensa si el worker muere tras enviar).
    """
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY debe estar configurada en el entorno")

    resend.api_key = RESEND_API_KEY
    reset_link = build_reset_link(token)

    options: resend.Emails.SendOptions | None = {"idempotency_key": idempotency_key} if idempotency_key else None
    resend.Emails.send({
        "from": EMAIL_FROM,
        "to": [to_email],
        "subject": "Restablece tu contraseña de Brasaland",
        "html": (
            "<p>Hemos recibido una solicitud para restablecer la contraseña de tu cuenta de Brasaland.</p>"
            f'<p><a href="{reset_link}">Haz clic aquí para elegir una nueva contraseña</a></p>'
            f"<p>Este enlace caduca en {PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutos "
            "y solo puede usarse una vez.</p>"
            "<p>Si no solicitaste este cambio, puedes ignorar este email: tu contraseña actual sigue siendo válida.</p>"
        ),
    }, options)
