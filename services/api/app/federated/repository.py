"""Persistencia (TinyDB): vínculos, estados OAuth de un solo uso y auditoría."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from tinydb import Query, TinyDB

from .models import FederatedIdentity

STATE_TTL_MINUTES = 10


class IdentityAlreadyLinked(Exception):
    """Esa identidad externa (provider + provider_user_id) ya pertenece a otro usuario."""


class FederatedRepository:
    def __init__(self, path: Path) -> None:
        self._db = TinyDB(path, indent=2)
        self._identities = self._db.table("identities")
        self._states = self._db.table("oauth_states")
        self._lock = Lock()

    # ------------------------------------------------------------------ vínculos
    @staticmethod
    def _record(row) -> FederatedIdentity:
        return FederatedIdentity.model_validate({**row, "id": row.doc_id})

    def link(self, user_id: int, provider: str, provider_user_id: str, email: str) -> FederatedIdentity:
        """Crea el vínculo. La unicidad (provider, provider_user_id) se comprueba y se inserta bajo el mismo cerrojo."""
        with self._lock:
            q = Query()
            existing = self._identities.get((q.provider == provider) & (q.provider_user_id == provider_user_id))
            if existing is not None:
                raise IdentityAlreadyLinked()
            doc_id = self._identities.insert({
                "user_id": user_id, "provider": provider, "provider_user_id": provider_user_id,
                "email_at_link_time": email, "linked_at": datetime.now(timezone.utc).isoformat(),
            })
            return self._record(self._identities.get(doc_id=doc_id))

    def find(self, provider: str, provider_user_id: str) -> FederatedIdentity | None:
        with self._lock:
            q = Query()
            row = self._identities.get((q.provider == provider) & (q.provider_user_id == provider_user_id))
        return self._record(row) if row else None

    def for_user(self, user_id: int) -> list[FederatedIdentity]:
        with self._lock:
            rows = self._identities.search(Query().user_id == user_id)
        return [self._record(r) for r in rows]

    def unlink(self, user_id: int, provider: str) -> FederatedIdentity | None:
        with self._lock:
            q = Query()
            row = self._identities.get((q.user_id == user_id) & (q.provider == provider))
            if row is None:
                return None
            self._identities.remove(doc_ids=[row.doc_id])
        return self._record(row)

    def delete_for_user(self, user_id: int) -> None:
        with self._lock:
            self._identities.remove(Query().user_id == user_id)

    # ------------------------------------------------------------------ `state` de OAuth (CSRF / fijación de sesión)
    def issue_state(self, purpose: str, redirect_uri: str, user_id: int | None) -> str:
        """`state` aleatorio, guardado en servidor, de UN solo uso, con caducidad y atado al flujo (vincular/login),
        al `redirect_uri` y —al vincular— al usuario con sesión: un callback ajeno o repetido no sirve."""
        state = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)
        with self._lock:
            self._states.insert({"state": state, "purpose": purpose, "redirect_uri": redirect_uri,
                                 "user_id": user_id, "expires_at": expires.isoformat()})
        return state

    def consume_state(self, state: str) -> dict | None:
        """Devuelve y BORRA el estado (un solo uso). `None` si no existe, ya se usó o caducó."""
        with self._lock:
            row = self._states.get(Query().state == state)
            if row is None:
                return None
            self._states.remove(doc_ids=[row.doc_id])
            self._states.remove(Query().expires_at < datetime.now(timezone.utc).isoformat())  # limpieza de caducados
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            return None
        return dict(row)

    def truncate(self) -> None:
        with self._lock:
            self._identities.truncate()
            self._states.truncate()
