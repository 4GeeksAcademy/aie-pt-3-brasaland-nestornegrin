"""TinyDB database initialization."""

from pathlib import Path

from tinydb import TinyDB

DATABASE_PATH = Path(__file__).resolve().parent.parent / "suppliers.json"
USERS_DATABASE_PATH = Path(__file__).resolve().parent.parent / "users.json"
PROFILES_DATABASE_PATH = Path(__file__).resolve().parent.parent / "profiles.json"
INCIDENTS_DATABASE_PATH = Path(__file__).resolve().parent.parent / "incidents.json"


def get_database() -> TinyDB:
    return TinyDB(DATABASE_PATH, indent=2)