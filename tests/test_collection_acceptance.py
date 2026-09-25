import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator"))

from collection_acceptance import evaluate


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class CollectionAcceptanceTests(unittest.TestCase):
    def test_cleansys_discovery_miss_is_not_no_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = {
                "sources": {
                    "CLEANSYS_AIR": {
                        "start_year": 2024,
                        "end_year": 2024,
                        "search_terms": ["테스트회사"],
                    }
                }
            }
            write_json(root / "request.json", request)
            write_json(root / "output/CLEANSYS_AIR/status.json", {
                "source_key": "CLEANSYS_AIR",
                "status": "DISCOVERY_UNRESOLVED",
                "candidate_count": 0,
                "candidate_query_attempts": 0,
                "candidate_query_success": 0,
                "annual_rows": 0,
                "errors": [],
            })
            (root / "output/CLEANSYS_AIR/annual_rows.jsonl").write_text("", encoding="utf-8")

            result = evaluate(root / "output", root / "request.json")
            self.assertEqual(result["status"], "REVIEW_REQUIRED")
            self.assertTrue(any(
                x["issue_type"] == "SOURCE_ID_DISCOVERY_UNRESOLVED"
                for x in result["blocking_issues"]
            ))

    def test_cleansys_id_bound_empty_query_can_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "request.json", {
                "sources": {
                    "CLEANSYS_AIR": {
                        "start_year": 2024,
                        "end_year": 2024,
                        "search_terms": ["테스트회사"],
                    }
                }
            })
            write_json(root / "output/CLEANSYS_AIR/status.json", {
                "source_key": "CLEANSYS_AIR",
                "status": "NO_DATA_CONFIRMED",
                "candidate_count": 1,
                "candidate_query_attempts": 1,
                "candidate_query_success": 1,
                "annual_rows": 0,
                "errors": [],
                "tls_verification": True,
            })
            (root / "output/CLEANSYS_AIR/annual_rows.jsonl").write_text("", encoding="utf-8")

            result = evaluate(root / "output", root / "request.json")
            self.assertEqual(result["status"], "PASS")

    def test_soosiro_name_only_empty_search_is_not_no_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "request.json", {
                "sources": {
                    "SOOSIRO_WATER": {
                        "annual_years": [2024],
                        "daily_years": [],
                        "search_terms": ["테스트회사"],
                    }
                }
            })
            write_json(root / "output/SOOSIRO_WATER/status.json", {
                "source_key": "SOOSIRO_WATER",
                "status": "DISCOVERY_UNRESOLVED",
                "annual_rows": 0,
                "fact_codes": 0,
                "address_seeded_fact_codes": [],
                "errors": 0,
            })
            write_json(root / "output/SOOSIRO_WATER/fact_candidates.json", [])
            raw = root / "output/SOOSIRO_WATER/raw_annual/2024_테스트회사.json"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text('{"list":[]}', encoding="utf-8")
            (root / "output/SOOSIRO_WATER/annual_rows.jsonl").write_text("", encoding="utf-8")
            (root / "output/SOOSIRO_WATER/daily_rows.jsonl").write_text("", encoding="utf-8")

            result = evaluate(root / "output", root / "request.json")
            self.assertEqual(result["status"], "REVIEW_REQUIRED")
            self.assertTrue(any(
                x["issue_type"] == "SOURCE_ID_DISCOVERY_UNRESOLVED"
                for x in result["blocking_issues"]
            ))

    def test_soosiro_address_seeded_id_bound_empty_query_can_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "request.json", {
                "sources": {
                    "SOOSIRO_WATER": {
                        "annual_years": [2024],
                        "daily_years": [],
                        "search_terms": ["테스트회사"],
                    }
                }
            })
            write_json(root / "output/SOOSIRO_WATER/status.json", {
                "source_key": "SOOSIRO_WATER",
                "status": "NO_DATA_CONFIRMED",
                "annual_rows": 0,
                "fact_codes": 1,
                "fact_code_list": ["FACT1"],
                "address_seeded_fact_codes": ["FACT1"],
                "fact_list_query_success": True,
                "errors": 0,
            })
            write_json(root / "output/SOOSIRO_WATER/fact_candidates.json", [{
                "FACT_CODE": "FACT1",
                "FACT_NAME": "테스트회사",
                "FACT_ADDR": "테스트로 1",
            }])
            raw = root / "output/SOOSIRO_WATER/raw_annual/2024_테스트회사.json"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text('{"list":[]}', encoding="utf-8")
            (root / "output/SOOSIRO_WATER/annual_rows.jsonl").write_text("", encoding="utf-8")
            (root / "output/SOOSIRO_WATER/daily_rows.jsonl").write_text("", encoding="utf-8")

            result = evaluate(root / "output", root / "request.json")
            self.assertEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
