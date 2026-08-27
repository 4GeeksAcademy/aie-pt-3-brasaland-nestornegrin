"""TinyDB database initialization."""

from pathlib import Path

from tinydb import TinyDB

DATABASE_PATH = Path(__file__).resolve().parent.parent / "suppliers.json"


def get_database() -> TinyDB:
    return TinyDB(DATABASE_PATH, indent=2)