"""TinyDB database initialization."""

import os
from pathlib import Path

from tinydb import TinyDB

# Carpeta de los ficheros TinyDB. Por defecto es services/api (comportamiento
# de siempre); BRASALAND_DATA_DIR permite apuntar a otra carpeta, p. ej. para
# medir con un volumen grande de datos sin tocar los datos de desarrollo.
DATA_DIR = Path(os.environ.get("BRASALAND_DATA_DIR") or Path(__file__).resolve().parent.parent)

DATABASE_PATH = DATA_DIR / "suppliers.json"
USERS_DATABASE_PATH = DATA_DIR / "users.json"
PROFILES_DATABASE_PATH = DATA_DIR / "profiles.json"
INCIDENTS_DATABASE_PATH = DATA_DIR / "incidents.json"
PASSWORD_RESETS_DATABASE_PATH = DATA_DIR / "password_resets.json"


def get_database() -> TinyDB:
    return TinyDB(DATABASE_PATH, indent=2)


# --- Supabase (SQLModel/Postgres) - inventory ---
# Kept in this same module alongside the TinyDB setup above: the app
# maintains two simultaneous DB connections on purpose (auth stays in
# TinyDB, inventory/orders move to Supabase).
from dotenv import load_dotenv
from sqlmodel import Session, create_engine

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, echo=False)


def get_db():
    """Yields one SQLModel session per request. No global session state."""
    with Session(engine) as session:
        yield session
