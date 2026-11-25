"""CONTRATO del mensaje de la cola para el email de restablecimiento de contraseña.

El worker necesita, para actuar solo: a quién escribir, el enlace/token y una clave de idempotencia. Pero el mensaje viaja y
se guarda en Redis, y el token de restablecimiento es una credencial de un solo uso: por eso NO va en claro. El mensaje es:

    {"idempotency_key": "password-reset:42", "sealed": "<Fernet(JSON{to, token})>"}

  · idempotency_key  en claro: es lo único que el worker y las herramientas de operación necesitan ver.
  · sealed           destinatario + token cifrados (Fernet = AES-128-CBC + HMAC). La clave se deriva de `TASK_PAYLOAD_KEY`
                     (o, si no existe, de `JWT_SECRET_KEY`); API y worker deben compartirla. El mensaje caduca (`MAX_AGE`):
                     pasado el plazo se rechaza sin reintentos, porque el token ya no valdría.
Nada de esto aparece en los logs, en el resultado de la tarea ni en la DLQ.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

MAX_AGE_SECONDS = 3600  # el token de restablecimiento caduca antes (PASSWORD_RESET_TOKEN_EXPIRE_MINUTES)


class InvalidMessage(Exception):
    """Mensaje ilegible o caducado: no tiene sentido reintentarlo (se reintenta lo transitorio, no lo imposible)."""


@dataclass(frozen=True)
class PasswordResetMessage:
    idempotency_key: str
    to_email: str
    token: str


def _fernet() -> Fernet:
    secret = os.environ.get("TASK_PAYLOAD_KEY") or os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("Falta TASK_PAYLOAD_KEY (o JWT_SECRET_KEY) para cifrar los mensajes de la cola.")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"brasaland-task-payload|{secret}".encode()).digest()))


def seal(to_email: str, token: str) -> str:
    return _fernet().encrypt(json.dumps({"to": to_email, "token": token}).encode()).decode()


def unseal(sealed: str) -> tuple[str, str]:
    try:
        data = json.loads(_fernet().decrypt(sealed.encode(), ttl=MAX_AGE_SECONDS))
        return str(data["to"]), str(data["token"])
    except (InvalidToken, ValueError, KeyError, TypeError) as error:
        raise InvalidMessage("Mensaje ilegible o caducado") from error
