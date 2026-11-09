"""Ejecuta el agente desde la terminal y deja el trace listo para adjuntar al PR.

    python -m services.agent "¿Cuántos puntos necesito para el nivel Oro?"
    python -m services.agent "¿Cuál es la capital de Francia?" --export docs/agent/example-trace-no-information.json

Usa los servicios reales (Qdrant y el modelo de chat configurados en `.env`).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .service import AgentExecutionError, AgentService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m services.agent", description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--export", type=Path, help="copia el trace de la corrida a este archivo JSON")
    args = parser.parse_args(argv)

    service = AgentService()
    try:
        run = service.run(args.question)
    except AgentExecutionError as error:
        print(f"La corrida {error.run_id} falló; el trace quedó en {service.trace_store.path_for(error.run_id)}",
              file=sys.stderr)
        return 1
    print(f"Estado: {run.status}\nRespuesta: {run.answer}\nRuta: {' -> '.join(run.trace['node_order'])}")
    print(f"Trace: {service.trace_store.path_for(run.run_id)}")
    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        args.export.write_text(json.dumps(run.trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Trace exportado a {args.export}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
