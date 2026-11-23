"""Prueba de humo del pipeline `rfp_intake` con el MODELO REAL sobre los 3 PDF de muestra del BRIEFING.

Usa un almacén en memoria: no toca la base de datos ni el servidor. Imprime en Markdown el resultado de cada PDF, listo para
pegar en la descripción del PR. Requiere las variables del modelo de generación (las mismas del asistente RAG).

    uv run python -m scripts.rfp_smoke [ruta.pdf ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from data.pipelines.rfp_intake import InMemoryRfpStore, process_ticket

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rfp"


def main(paths: list[str]) -> int:
    pdfs = [Path(p) for p in paths] or sorted(FIXTURES.glob("brasaland-request-*.pdf"))
    store = InMemoryRfpStore()
    for ticket_id, pdf in enumerate(pdfs, start=1):
        store.add(ticket_id, str(pdf), pdf.name)
        outcome = process_ticket(ticket_id, store)
        t = store.get_ticket(ticket_id)
        print(f"\n## {pdf.name} → **{t['status']}** ({outcome})")
        if t["status"] == "descartado":
            print(f"- Motivo: {t['discard_reason']}")
            continue
        if t["status"] != "analisis_completo":
            print(f"- Error: {t['processing_error']}")
            continue
        m = t["metadata"]
        print(f"- Cliente: {m['client_name']} · {m['location']} · {m['service_type']}\n- Alcance: {m['scope']}\n"
              f"- Fecha límite: {m['deadline']} · Presupuesto: {m['budget_range'] or 'no indicado'}\n"
              f"- Legibilidad: {t['readability']['word_count']} palabras, ~{t['readability']['est_tokens']} tokens, complejidad {t['readability']['complexity']}")
        for w in t["handoff"]["workstreams"]:
            print(f"\n### {w['department']} — {w['owner']}")
            for a in w["key_aspects"]:
                print(f"- **{a['aspect']}**: {a['detail']}")
            for ask in w["asks"]:
                print(f"- _Pedir_: {ask}")
            for q in w["open_questions"]:
                print(f"- _Pregunta abierta_: {q}")
        ceo = t["handoff"]["approvals"]["ceo"]
        print(f"\n- Aprobación CEO (>50.000 USD/año): {ceo['required']}")
        print(f"\n<details><summary>handoff JSON</summary>\n\n```json\n{json.dumps(t['handoff'], ensure_ascii=False, indent=2)}\n```\n</details>")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
