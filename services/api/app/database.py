"""TinyDB database initialization."""

from pathlib import Path

from tinydb import TinyDB

DATABASE_PATH = Path(__file__).resolve().parent.parent / "suppliers.json"
USERS_DATABASE_PATH = Path(__file__).resolve().parent.parent / "users.json"
PROFILES_DATABASE_PATH = Path(__file__).resolve().parent.parent / "profiles.json"
INCIDENTS_DATABASE_PATH = Path(__file__).resolve().parent.parent / "incidents.json"
PASSWORD_RESETS_DATABASE_PATH = Path(__file__).resolve().parent.parent / "password_resets.json"


def get_database() -> TinyDB:
    return TinyDB(DATABASE_PATH, indent=2)


# --- Supabase (SQLModel/Postgres) - inventory ---
# Kept in this same module alongside the TinyDB setup above: the app
# maintains two simultaneous DB connections on purpose (auth stays in
# TinyDB, inventory/orders move to Supabase).
import os

from dotenv import load_dotenv
from sqlmodel import Session, create_engine

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, echo=False)


def get_db():
    """Yields one SQLModel session per request. No global session state."""
    with Session(engine) as session:
        yield session
