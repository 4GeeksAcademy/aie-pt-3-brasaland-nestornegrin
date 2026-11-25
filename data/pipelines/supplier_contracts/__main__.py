"""CLI de demostración:  python -m data.pipelines.supplier_contracts seed | alerts | ask "pregunta" | brief BR-S05"""
from __future__ import annotations

import sys
from datetime import date

from .engine import SupplierEngine


def main(argv: list[str]) -> int:
    engine = SupplierEngine()
    cmd = argv[0] if argv else "help"
    if cmd == "seed":
        print(engine.seed(date.today()))
    elif cmd == "alerts":
        for a in engine.alerts.scan(engine.load_date or date.today()):
            print(f"[{a['kind']}] {a['message']}")
    elif cmd == "ask" and len(argv) > 1:
        print(engine.ask(" ".join(argv[1:])).answer)
    elif cmd == "brief" and len(argv) > 1:
        print(engine.brief(argv[1]).answer)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
