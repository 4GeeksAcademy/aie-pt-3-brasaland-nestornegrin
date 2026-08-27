import unittest
from pathlib import Path

from analyze import analyze_csv, analyze_rows


def row(number: int, category: str = "Queja", status: str = "Cerrado", score: str = "4") -> dict[str, str]:
    return {
        "incident_id": f"INC-{number}",
        "customer_name": "Cliente anonimizado",
        "customer_email": f"cliente{number}@example.test",
        "category": category,
        "status": status,
        "created_at": "2026-01-15",
        "satisfaction_score": score,
    }


class AnalyzeTests(unittest.TestCase):
    def test_anonymized_fixture_matches_documented_expectations(self) -> None:
        fixture = Path(__file__).parents[1] / "data" / "raw" / "incidents-COMPANY.csv"
        result = analyze_csv(fixture)
        self.assertEqual((result.total_processed, result.valid_records, result.invalid_records), (100, 90, 10))
        self.assertEqual(result.by_category, {"Queja": 30, "Solicitud": 30, "Fallo operativo": 30})
        self.assertEqual(result.by_status, {"Abierto": 60, "Cerrado": 30, "Descartado": 0})
        self.assertEqual(result.average_closed_satisfaction, 3)

    def test_valid_records_are_aggregated_and_closed_average_is_filtered(self) -> None:
        result = analyze_rows([
            row(1, "Queja", "Cerrado", "5"),
            row(2, "Solicitud", "Abierto", "1"),
            row(3, "Fallo operativo", "Cerrado", "3"),
            row(4, "Queja", "Descartado", ""),
        ])
        self.assertEqual(result.total_processed, 4)
        self.assertEqual(result.valid_records, 4)
        self.assertEqual(result.by_category, {"Queja": 2, "Solicitud": 1, "Fallo operativo": 1})
        self.assertEqual(result.by_status, {"Abierto": 1, "Cerrado": 2, "Descartado": 1})
        self.assertEqual(result.average_closed_satisfaction, 4)

    def test_invalid_records_are_excluded_but_each_reason_is_counted(self) -> None:
        invalid = row(2, "Reclamo", "En revisión", "9")
        invalid["customer_name"] = ""
        result = analyze_rows([row(1), invalid])
        self.assertEqual(result.valid_records, 1)
        self.assertEqual(result.invalid_records, 1)
        self.assertEqual(result.invalid_reasons["missing_field:customer_name"], 1)
        self.assertEqual(result.invalid_reasons["invalid_category"], 1)
        self.assertEqual(result.invalid_reasons["invalid_status"], 1)
        self.assertEqual(result.invalid_reasons["invalid_satisfaction"], 1)


if __name__ == "__main__":
    unittest.main()