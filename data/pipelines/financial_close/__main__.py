"""CLI / worker del cierre.
  python -m data.pipelines.financial_close demo [--dir DIR]      genera CSV de ejemplo, ingesta y prepara el informe (v1, pendiente)
  python -m data.pipelines.financial_close run --period 2026-10 --source DIR
  python -m data.pipelines.financial_close worker [--source DIR]  proceso en segundo plano: cada minuto comprueba si toca (3.er día hábil, 06:00 Medellín)
"""
from __future__ import annotations

import argparse
import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import config, generate, schedule
from .store import CloseStore, DataStore
from .workflow import CloseEngine


def _engine() -> CloseEngine:
    return CloseEngine(DataStore(config.DEFAULT_DATA_DB), CloseStore(config.DEFAULT_CLOSE_DB))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="financial_close")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo"); d.add_argument("--dir", default=str(config.DEFAULT_FILES_DIR))
    r = sub.add_parser("run"); r.add_argument("--period", required=True); r.add_argument("--source", required=True)
    w = sub.add_parser("worker"); w.add_argument("--source", default=str(config.DEFAULT_FILES_DIR)); w.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    eng = _engine()
    if a.cmd == "demo":
        info = generate.generate(Path(a.dir), date.today())
        eng.load_period(a.dir, info["period"])
        rep = eng.run_close(info["period"])
        print(f"periodo {info['period']}: informe v{rep['version']} #{rep['id']} ({rep['status']}) — pendiente de Felipe Guerrero")
    elif a.cmd == "run":
        eng.load_period(a.source, a.period)
        rep = eng.run_close(a.period)
        print(f"informe v{rep['version']} #{rep['id']} ({rep['status']})")
    else:
        while True:
            print(schedule.tick(eng, datetime.now(timezone.utc), a.source), flush=True)
            if a.once:
                break
            time.sleep(60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
