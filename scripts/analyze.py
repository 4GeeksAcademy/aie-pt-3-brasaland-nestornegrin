#!/usr/bin/env python3
"""Validate and summarize Brasaland post-sale incident CSV files."""

from __future__ import annotations

import argparse
import csv
import io
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from packages.shared.incident_validation import (  # noqa: E402
    ALLOWED_CATEGORIES,
    ALLOWED_CSV_STATUSES as ALLOWED_STATUSES,
    REQUIRED_CSV_FIELDS as REQUIRED_FIELDS,
    VALID_CSV_FIELDS as VALID_FIELDS,
    validate_incident_row as _validate_row,
)

OPTIONAL_FIELDS = ("satisfaction_score",)


@dataclass(frozen=True)
class AnalysisResult:
    total_processed: int
    valid_records: int
    invalid_records: int
    by_category: dict[str, int]
    by_status: dict[str, int]
    average_closed_satisfaction: float | None
    invalid_reasons: dict[str, int]

    def export_rows(self) -> list[tuple[str, str, str]]:
        rows = [
            ("total_processed", "", str(self.total_processed)),
            ("valid_records", "", str(self.valid_records)),
            ("invalid_records", "", str(self.invalid_records)),
        ]
        rows.extend(("category_count", key, str(value)) for key, value in self.by_category.items())
        rows.extend(("status_count", key, str(value)) for key, value in self.by_status.items())
        if self.average_closed_satisfaction is not None:
            rows.append(("average_closed_satisfaction", "", f"{self.average_closed_satisfaction:.2f}"))
        rows.extend(("invalid_reason", key, str(value)) for key, value in self.invalid_reasons.items())
        return rows


def analyze_rows(rows: Iterable[dict[str, str | None]]) -> AnalysisResult:
    total_processed = 0
    valid_records = 0
    categories: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    invalid_reasons: Counter[str] = Counter()
    closed_scores: list[int] = []

    for row in rows:
        total_processed += 1
        reasons = _validate_row(row)
        if reasons:
            invalid_reasons.update(reasons)
            continue
        valid_records += 1
        categories[row["category"].strip()] += 1  # type: ignore[union-attr]
        statuses[row["status"].strip()] += 1  # type: ignore[union-attr]
        score = (row.get("satisfaction_score") or "").strip()
        if row["status"].strip() == "Cerrado" and score:
            closed_scores.append(int(score))

    average = sum(closed_scores) / len(closed_scores) if closed_scores else None
    return AnalysisResult(
        total_processed=total_processed,
        valid_records=valid_records,
        invalid_records=total_processed - valid_records,
        by_category={category: categories[category] for category in ALLOWED_CATEGORIES},
        by_status={status: statuses[status] for status in ALLOWED_STATUSES},
        average_closed_satisfaction=average,
        invalid_reasons=dict(invalid_reasons),
    )


def analyze_csv(path: str | Path) -> AnalysisResult:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return analyze_csv_text(handle.read())


def analyze_csv_text(content: str) -> AnalysisResult:
    if not content.strip():
        raise ValueError("El fichero CSV está vacío")
    reader = csv.DictReader(io.StringIO(content, newline=""))
    if reader.fieldnames is None:
        raise ValueError("El fichero CSV no contiene una cabecera")
    fields = {field.strip() for field in reader.fieldnames if field}
    missing = set(REQUIRED_FIELDS) - fields
    unknown = fields - VALID_FIELDS
    if missing:
        raise ValueError(f"Faltan columnas obligatorias: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"Columnas no permitidas: {', '.join(sorted(unknown))}")
    return analyze_rows(reader)


def write_results(result: AnalysisResult, path: str | Path = "results.csv") -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("metric", "dimension", "value"))
        writer.writerows(result.export_rows())


def print_summary(result: AnalysisResult) -> None:
    print("\n" + "=" * 58)
    print("RESUMEN DE INCIDENCIAS POSTVENTA")
    print("=" * 58)
    print(f"{'Filas procesadas:':30}{result.total_processed:>10}")
    print(f"{'Registros válidos:':30}{result.valid_records:>10}")
    print(f"{'Registros inválidos:':30}{result.invalid_records:>10}")
    print("\nPOR CATEGORÍA (registros válidos)")
    for key, value in result.by_category.items():
        print(f"  {key:27}{value:>10}")
    print("\nPOR ESTADO (registros válidos)")
    for key, value in result.by_status.items():
        print(f"  {key:27}{value:>10}")
    average = "N/D" if result.average_closed_satisfaction is None else f"{result.average_closed_satisfaction:.2f} / 5"
    print(f"\n{'Satisfacción media (Cerrado):':30}{average:>10}")
    print("\nMOTIVOS DE INVALIDACIÓN")
    if result.invalid_reasons:
        for key, value in result.invalid_reasons.items():
            print(f"  {key:27}{value:>10}")
    else:
        print("  Ninguno")
    print("=" * 58)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="Ruta al fichero CSV de incidencias")
    parser.add_argument("--output", type=Path, default=Path("results.csv"), help="Ruta del CSV de resultados")
    args = parser.parse_args()
    try:
        result = analyze_csv(args.csv_path)
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    print_summary(result)
    try:
        answer = input("¿Deseas exportar los resultados a CSV? [s/n] ").strip().lower()
    except EOFError:
        # Entrada no interactiva (p. ej. ejecutado en un script o pipeline):
        # no se puede preguntar, así que se omite la exportación en vez de
        # fallar con un traceback.
        print("Entrada no interactiva: se omite la exportación a CSV.", file=sys.stderr)
        return 0
    if answer == "s":
        try:
            write_results(result, args.output)
        except OSError as error:
            print(f"Error al guardar los resultados en {args.output}: {error}", file=sys.stderr)
            return 1
        print(f"Resultados guardados en {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())