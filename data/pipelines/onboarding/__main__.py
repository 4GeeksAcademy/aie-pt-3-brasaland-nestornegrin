"""CLI: `python -m data.pipelines.onboarding seed|sweep|board`. Usa las bases definidas por ONBOARDING_DB / ONBOARDING_CHECKPOINT_DB."""
from __future__ import annotations

import json
import sys

from .runner import OnboardingEngine
from .seed import seed


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "board"
    engine = OnboardingEngine()
    if command == "seed":
        print(json.dumps(seed(engine), ensure_ascii=False, indent=2))
    elif command == "sweep":
        print(json.dumps(engine.sweep(), ensure_ascii=False, indent=2))
    elif command == "board":
        for row in engine.board():
            print(f"{row['name']:<18} {row['site']:<9} etapa {row['current_stage']} · {row['current_stage_title']:<28} espera: {row['waiting_on']} {'· BLOQUEADA' if row['blocked'] else ''}")
    else:
        print("Uso: python -m data.pipelines.onboarding [seed|sweep|board]")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
