"""Datos semilla de DEMO (BRIEFING «Datos semilla»): usuarios, reportes internos. Roles y departamentos se siembran siempre
al crear el catálogo. Los usuarios de demo NO se crean en producción: solo con `python -m app.access.seed` o `SEED_DEMO_DATA=true`.

La contraseña de desarrollo compartida sale de `SEED_USER_PASSWORD` (por defecto, una contraseña de desarrollo conocida).
"""

from __future__ import annotations

import os

DEFAULT_DEV_PASSWORD = "Brasaland-Dev-2026!"

USERS_SEED = [
    {"email": "felipe.ops@brasaland.example", "role": "supervisor", "department": "restaurant_operations", "name": "Felipe Guerrero"},
    {"email": "lucia.procurement@brasaland.example", "role": "supervisor", "department": "procurement", "name": "Lucía Fernández"},
    {"email": "camila.marketing@brasaland.example", "role": "employee", "department": "marketing", "name": "Camila Ospina"},
    {"email": "jake.training@brasaland.example", "role": "employee", "department": "training_quality", "name": "Jake Morrison"},
    {"email": "nicolas.admin@brasaland.example", "role": "admin", "department": "technology", "name": "Nicolás Park"},
]

INTERNAL_REPORTS_SEED = [
    {"department": "restaurant_operations", "title": "Medellín Centro — Friday stockout",
     "body": "Ribeye 86% depleted before close. Shift report attached."},
    {"department": "procurement", "title": "Carnes del Valle rate change",
     "body": "Supplier proposed +8% on beef for Q4. Pending Lucía approval."},
]


def seed_demo(user_repository, profile_repository, catalog, report_repository, password: str | None = None) -> dict[str, int]:
    """Idempotente: no duplica usuarios (por email) ni reportes (por título). Devuelve cuántos creó."""
    from app.auth.security import hash_password

    password = password or os.environ.get("SEED_USER_PASSWORD") or DEFAULT_DEV_PASSWORD
    hashed = hash_password(password)
    created_users = created_reports = 0
    author_id: int | None = None
    for item in USERS_SEED:
        user = user_repository.get_by_email(item["email"])
        if user is None:
            role = catalog.get_role_by_code(item["role"])
            department = catalog.get_department_by_code(item["department"])
            user = user_repository.create(item["email"], hashed, role["id"], department["id"])
            profile_repository.create(user.id, item["name"])
            created_users += 1
        if item["role"] == "admin":
            author_id = user.id
    existing_titles = {r["title"] for r in report_repository.list()}
    for item in INTERNAL_REPORTS_SEED:
        if item["title"] in existing_titles:
            continue
        department = catalog.get_department_by_code(item["department"])
        report_repository.create(department["id"], item["title"], item["body"], author_id or 1)
        created_reports += 1
    return {"users": created_users, "internal_reports": created_reports}


def main() -> int:
    from app.main import access_catalog, internal_report_repository, profile_repository, user_repository

    created = seed_demo(user_repository, profile_repository, access_catalog, internal_report_repository)
    from app.federated.seed import seed_federated_demo
    from app.main import federated_repository

    federated = seed_federated_demo(user_repository, profile_repository, federated_repository)
    print(f"Seed de roles y permisos: {created['users']} usuarios y {created['internal_reports']} reportes internos creados; {federated} clientes de autenticación federada.")
    print("Contraseña de desarrollo compartida: la de SEED_USER_PASSWORD (o la de desarrollo por defecto documentada).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
