"""Reprocesa un ticket de RFP desde la terminal (útil si el servidor murió a mitad del pipeline).

    cd services/api && uv run python -m scripts.rfp_reprocess <ticket_id> [--force]

Usa la misma base de datos (DATABASE_URL) y el mismo pipeline que la API: no duplica lógica.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "services" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def main(argv: list[str]) -> int:
    ids = [a for a in argv if a.isdigit()]
    if len(ids) != 1:
        print(__doc__)
        return 2
    from sqlmodel import Session

    from app.database import engine
    from app.rfp.repository import SqlRfpStore
    from data.pipelines.rfp_intake import process_ticket

    outcome = process_ticket(int(ids[0]), SqlRfpStore(lambda: Session(engine)), force="--force" in argv)
    print(f"Ticket {ids[0]}: {outcome}")
    return 0 if outcome != "fallo" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
