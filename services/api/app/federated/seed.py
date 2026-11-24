"""Datos semilla de la autenticación federada (BRIEFING §6): un cliente CON Google vinculado y otro SIN vincular."""

from __future__ import annotations

import os

from app.auth.security import hash_password

DEFAULT_DEV_PASSWORD = "Brasaland-Dev-2026!"  # solo desarrollo: nunca en producción

USERS_SEED = [
    {"email": "camila.points@brasaland.example", "name": "Camila Ospina", "has_password": True,
     "linked_providers": [{"provider": "google", "provider_user_id": "google-sub-camila-001"}]},
    {"email": "guest.unlinked@brasaland.example", "name": "Unlinked Guest", "has_password": True, "linked_providers": []},
]
UNKNOWN_IDENTITY = {"provider": "google", "provider_user_id": "google-sub-unknown-999"}  # fixture del login rechazado


def seed_federated_demo(user_repository, profile_repository, federated_repository, password: str | None = None) -> int:
    """Idempotente. Los clientes nacen como Empleado sin departamento (igual que el registro público)."""
    password = password or os.environ.get("SEED_USER_PASSWORD") or DEFAULT_DEV_PASSWORD
    created = 0
    for item in USERS_SEED:
        user = user_repository.get_by_email(item["email"])
        if user is None:
            user = user_repository.create(item["email"], hash_password(password) if item["has_password"] else "")
            profile_repository.create(user.id, item["name"], "", "")
            created += 1
        for link in item["linked_providers"]:
            if federated_repository.find(link["provider"], link["provider_user_id"]) is None:
                federated_repository.link(user.id, link["provider"], link["provider_user_id"], item["email"])
    return created
