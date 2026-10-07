#!/usr/bin/env python3
"""Genera services/telemetry-schema.ts desde docs/telemetry/event-schemas.json.

Uso (desde uis/backoffice):  python3 scripts/gen-telemetry-schema.py
La tabla de allowlists no se escribe a mano: así plan, JSON y cliente no divergen.
"""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[3]
schema = json.loads((root / "docs/telemetry/event-schemas.json").read_text())
version = schema["x-catalogSummary"]["schemaVersion"]
rows = []
for name, ev in schema["definitions"]["events"].items():
    props = ev["properties"]["properties"]
    allowed = list(props.get("properties", {}).keys())
    required = props.get("required", [])
    rows.append(f'  {name}: {{ allowed: {json.dumps(allowed)}, required: {json.dumps(required)} }},')
out = (
    "// ARCHIVO GENERADO por scripts/gen-telemetry-schema.py — no editar a mano.\n"
    "// Fuente: docs/telemetry/event-schemas.json\n\n"
    f'export const SCHEMA_VERSION = "{version}";\n\n'
    "export type EventAllowlist = { allowed: readonly string[]; required: readonly string[] };\n\n"
    "export const EVENT_ALLOWLISTS: Record<string, EventAllowlist> = {\n" + "\n".join(rows) + "\n};\n"
)
(root / "uis/backoffice/services/telemetry-schema.ts").write_text(out)
print("ok", len(rows), "eventos; versión en JSON:", version)
