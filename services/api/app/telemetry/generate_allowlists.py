"""Genera app/telemetry/allowlists.py desde docs/telemetry/event-schemas.json.

Uso (desde services/api):  python -m app.telemetry.generate_allowlists

La tabla no se escribe a mano: así el backend, el cliente y el plan comparten
una única fuente (mismo patrón que uis/backoffice/scripts/gen-telemetry-schema.py).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "docs" / "telemetry" / "event-schemas.json"
TARGET = Path(__file__).resolve().parent / "allowlists.py"


def main() -> None:
    schema = json.loads(SOURCE.read_text(encoding="utf-8"))
    version = schema["x-catalogSummary"]["schemaVersion"]
    lines = []
    for name, event in schema["definitions"]["events"].items():
        props = event["properties"]["properties"]
        allowed = list(props.get("properties", {}).keys())
        required = props.get("required", [])
        lines.append(f'    "{name}": EventAllowlist(allowed={tuple(allowed)!r}, required={tuple(required)!r}),')
    body = (
        '"""ARCHIVO GENERADO por app/telemetry/generate_allowlists.py — no editar a mano.\n'
        'Fuente: docs/telemetry/event-schemas.json"""\n'
        "from __future__ import annotations\n\n"
        "from typing import NamedTuple\n\n"
        f'SCHEMA_VERSION = "{version}"\n\n\n'
        "class EventAllowlist(NamedTuple):\n"
        "    allowed: tuple[str, ...]\n"
        "    required: tuple[str, ...]\n\n\n"
        "EVENT_ALLOWLISTS: dict[str, EventAllowlist] = {\n" + "\n".join(lines) + "\n}\n"
    )
    TARGET.write_text(body, encoding="utf-8")
    print(f"ok: {len(lines)} eventos, esquema {version}")


if __name__ == "__main__":
    main()
