"""Inspección de la memoria del agente.

    python -m services.agent.memory list          recuerdos activos
    python -m services.agent.memory events        registro de auditoría (solo-añadir)
    python -m services.agent.memory consolidate   limpieza a demanda (caducidad, duplicados, topes)
"""
from __future__ import annotations

import argparse
import json

from .store import SqliteMemoryStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m services.agent.memory", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["list", "events", "consolidate"])
    parser.add_argument("--conversation", help="filtra los eventos por conversación")
    args = parser.parse_args(argv)
    store = SqliteMemoryStore()
    if args.command == "list":
        for memory in store.active_memories():
            print(f"[{memory['location']} · {memory['category']}] {memory['fact']}  (aprobado por {memory['approved_by']}, "
                  f"caduca {memory['expires_at']})")
    elif args.command == "events":
        for event in store.events(conversation_id=args.conversation):
            print(f"{event['seq']:>4} {event['ts']} {event['event']:<32} {event['actor']:<22} "
                  f"{json.dumps(event['detail'], ensure_ascii=False) if event['detail'] else ''}")
    else:
        print(json.dumps(store.consolidate().to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
