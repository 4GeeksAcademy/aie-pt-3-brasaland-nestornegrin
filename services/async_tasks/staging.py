"""Aparcamiento del CSV subido.

Regla del patrón productor/consumidor: los mensajes son ligeros. La API NO mete el contenido del CSV en la
cola: lo escribe aquí y encola solo el identificador (`<uuid>.csv`); el worker lo recupera por su cuenta.
"""
from __future__ import annotations

import logging
import os
import re
import uuid

from services.async_tasks import config

logger = logging.getLogger(__name__)

# Solo identificadores generados por `stage_upload`: impide que un mensaje manipulado lea otra ruta (../).
_UPLOAD_ID = re.compile(r"^[0-9a-f]{32}\.csv$")


def stage_upload(content: bytes) -> str:
    """Guarda el CSV de forma atómica (temporal + rename) y devuelve su identificador."""
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    upload_id = f"{uuid.uuid4().hex}.csv"
    target = config.UPLOAD_DIR / upload_id
    temporary = target.with_suffix(".csv.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, target)
    return upload_id


def read_upload_text(upload_id: str) -> str:
    """Lee el CSV aparcado (UTF-8, con o sin BOM). Lanza FileNotFoundError / ValueError si no se puede."""
    if not _UPLOAD_ID.match(upload_id):
        raise ValueError(f"Identificador de fichero no válido: {upload_id!r}")
    return (config.UPLOAD_DIR / upload_id).read_text(encoding="utf-8-sig")


def delete_upload(upload_id: str) -> None:
    """Borra el CSV aparcado. Nunca lanza: limpiar no debe convertir un éxito (o un fallo ya registrado) en otro error."""
    if not _UPLOAD_ID.match(upload_id):
        return
    try:
        (config.UPLOAD_DIR / upload_id).unlink(missing_ok=True)
    except OSError:
        logger.warning("No se pudo borrar el fichero aparcado %s", upload_id, exc_info=True)
