"""`python -m services.agent.guardrails summary [--json]` → cuántas veces disparó cada guardrail (lee el JSONL)."""
from __future__ import annotations

import argparse
import json

from .monitor import KINDS, log_path, read_log, summarize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m services.agent.guardrails")
    sub = parser.add_subparsers(dest="command", required=True)
    summary = sub.add_parser("summary", help="resumen de bloqueos y redirecciones por guardrail y tipo de fallo")
    summary.add_argument("--json", action="store_true")
    summary.add_argument("--log", help="archivo JSONL (por defecto data/logs/agent-guardrails.jsonl)")
    args = parser.parse_args(argv)
    data = summarize(read_log(args.log))
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"Registro: {args.log or log_path()}\nEventos: {data['total']}")
    print("Por tipo de fallo: " + ", ".join(f"{kind}={data['by_failure_type'][kind]}" for kind in KINDS))
    for title, key in (("Por guardrail", "by_guardrail"), ("Por motivo", "by_reason"), ("Por acción", "by_action")):
        print(f"\n{title}:")
        for name, count in data[key].items():
            print(f"  {count:>4}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
