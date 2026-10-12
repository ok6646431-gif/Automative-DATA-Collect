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
                    "identity_gate": {
                        "enabled": True,
                        "mode": "VERIFIED_CURRENT_ENTITY_OR_SITE",
                        "current_entity_names": ["테스트회사"],
                        "verified_sites": [{"site_name": "테스트회사 제1공장", "address": "테스트로 1"}],
                    },
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
                    "identity_gate": {
                        "enabled": True,
                        "mode": "VERIFIED_CURRENT_ENTITY_OR_SITE",
                        "current_entity_names": ["테스트회사"],
                        "verified_sites": [{"site_name": "테스트회사 제1공장", "address": "테스트로 1"}],
                    },
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
                    "identity_gate": {
                        "enabled": True,
                        "mode": "VERIFIED_CURRENT_ENTITY_OR_SITE",
                        "current_entity_names": ["테스트회사"],
                        "verified_sites": [{"site_name": "테스트회사 제1공장", "address": "테스트로 1"}],
                    },
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
                    "identity_gate": {
                        "enabled": True,
                        "mode": "VERIFIED_CURRENT_ENTITY_OR_SITE",
                        "current_entity_names": ["테스트회사"],
                        "verified_sites": [{"site_name": "테스트회사 제1공장", "address": "테스트로 1"}],
                    },
                    }
                }
            })
            write_json(root / "output/SOOSIRO_WATER/status.json", {
                "source_key": "SOOSIRO_WATER",
                "status": "NO_DATA_CONFIRMED",
                "annual_rows": 0,
                "fact_codes": 1,
                "fact_code_list": ["FACT1"],
                "annual_years": [2024],
                "address_seeded_fact_codes": ["FACT1"],
                "fact_list_query_success": True,
                "annual_fact_requests_success": 1,
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

    def test_cleansys_complete_registry_miss_is_resolved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "request.json", {
                "sources": {
                    "CLEANSYS_AIR": {
                        "start_year": 2024,
                        "end_year": 2024,
                        "search_terms": ["테스트회사"],
                    "identity_gate": {
                        "enabled": True,
                        "mode": "VERIFIED_CURRENT_ENTITY_OR_SITE",
                        "current_entity_names": ["테스트회사"],
                        "verified_sites": [{"site_name": "테스트회사 제1공장", "address": "테스트로 1"}],
                    },
                    }
                }
            })
            write_json(root / "output/CLEANSYS_AIR/status.json", {
                "source_key": "CLEANSYS_AIR",
                "status": "NO_FACILITY_MATCH_CONFIRMED",
                "registry_scan_complete": True,
                "index_selectable_option_count": 900,
                "candidate_count": 0,
                "annual_rows": 0,
                "errors": [],
                "tls_verification": True,
            })
            (root / "output/CLEANSYS_AIR/annual_rows.jsonl").write_text("", encoding="utf-8")
            result = evaluate(root / "output", root / "request.json")
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["period_audit"])
            self.assertTrue(all(
                row["completeness_state"] == "NO_FACILITY_MATCH_CONFIRMED"
                for row in result["period_audit"]
            ))

    def test_soosiro_complete_registry_and_term_miss_is_resolved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "request.json", {
                "sources": {
                    "SOOSIRO_WATER": {
                        "annual_years": [2024],
                        "daily_years": [],
                        "search_terms": ["테스트회사"],
                    "identity_gate": {
                        "enabled": True,
                        "mode": "VERIFIED_CURRENT_ENTITY_OR_SITE",
                        "current_entity_names": ["테스트회사"],
                        "verified_sites": [{"site_name": "테스트회사 제1공장", "address": "테스트로 1"}],
                    },
                    }
                }
            })
            write_json(root / "output/SOOSIRO_WATER/status.json", {
                "source_key": "SOOSIRO_WATER",
                "status": "NO_FACILITY_MATCH_CONFIRMED",
                "registry_scan_complete": True,
                "fact_list_rows": 1000,
                "fact_list_query_success": True,
                "annual_rows": 0,
                "fact_codes": 0,
                "address_seeded_fact_codes": [],
                "registry_seeded_fact_codes": [],
                "annual_term_requests_success": 1,
                "errors": 0,
            })
            write_json(root / "output/SOOSIRO_WATER/fact_candidates.json", [])
            raw = root / "output/SOOSIRO_WATER/raw_annual/2024_테스트회사.json"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text('{"list":[]}', encoding="utf-8")
            (root / "output/SOOSIRO_WATER/annual_rows.jsonl").write_text("", encoding="utf-8")
            (root / "output/SOOSIRO_WATER/daily_rows.jsonl").write_text("", encoding="utf-8")
            result = evaluate(root / "output", root / "request.json")
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["period_audit"])
            self.assertTrue(all(
                row["completeness_state"] == "NO_FACILITY_MATCH_CONFIRMED"
                for row in result["period_audit"]
            ))


    def test_unconfirmed_name_only_empty_result_is_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "request.json", {"sources": {"PRTR": {"start_year": 2024, "end_year": 2024, "search_terms": ["테스트회사"]}}})
            write_json(root / "output/PRTR/status.json", {
                "source_key": "PRTR", "status": "NO_MATCH", "rows": 0, "errors": 0,
            })
            result = evaluate(root / "output", root / "request.json")
            self.assertEqual(result["status"], "REVIEW_REQUIRED")
            self.assertIn("UNACCEPTED_SOURCE_STATUS", [x["issue_type"] for x in result["blocking_issues"]])

    def test_data_found_with_errors_is_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "request.json", {"sources": {"PRTR": {"start_year": 2024, "end_year": 2024, "search_terms": ["테스트회사"]}}})
            write_json(root / "output/PRTR/status.json", {
                "source_key": "PRTR", "status": "DATA_FOUND", "rows": 1, "detail_ok": 1, "errors": 1,
            })
            result = evaluate(root / "output", root / "request.json")
            self.assertEqual(result["status"], "REVIEW_REQUIRED")
            self.assertIn("COLLECTOR_ERRORS_REPORTED", [x["issue_type"] for x in result["blocking_issues"]])

    def test_registry_miss_without_verified_identity_is_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "request.json", {"sources": {
                "CLEANSYS_AIR": {"start_year": 2024, "end_year": 2024, "search_terms": ["테스트회사"]}
            }})
            write_json(root / "output/CLEANSYS_AIR/status.json", {
                "source_key": "CLEANSYS_AIR",
                "status": "NO_FACILITY_MATCH_CONFIRMED",
                "registry_scan_complete": True,
                "index_selectable_option_count": 923,
                "candidate_count": 0,
                "candidate_query_attempts": 0,
                "errors": [],
            })
            result = evaluate(root / "output", root / "request.json")
            self.assertEqual(result["status"], "REVIEW_REQUIRED")
            self.assertIn("UNVERIFIED_REGISTRY_MISS_IDENTITY", [x["issue_type"] for x in result["blocking_issues"]])

    def test_full_collection_requires_corporate_documents_status(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "request.json", {"sources": {}})
            result = evaluate(root / "output", root / "request.json", require_all_sources=True)
            self.assertEqual(result["status"], "REVIEW_REQUIRED")
            self.assertIn("CORP_DOCS", [x["source"] for x in result["blocking_issues"]])



    def test_corporate_document_digest_and_file_presence_are_required(self):
        import csv
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "request.json", {"sources": {}})
            file_path = root / "output/CORP_DOCS/report.pdf"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"%PDF-1.4 test report fixture")
            digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
            write_json(root / "output/CORP_DOCS/status.json", {
                "source_key": "CORP_DOCS",
                "status": "DATA_FOUND",
                "discovery_status": "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE",
                "documents_declared": 1,
                "downloaded": 1,
                "failed": 0,
                "skipped": 0,
            })
            with (root / "output/CORP_DOCS/document_index.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as file:
                writer = csv.DictWriter(file, fieldnames=[
                    "document_id", "stored_path", "collection_status", "bytes", "sha256"
                ])
                writer.writeheader()
                writer.writerow({
                    "document_id": "REPORT2024",
                    "stored_path": "output/CORP_DOCS/report.pdf",
                    "collection_status": "DOWNLOADED",
                    "bytes": file_path.stat().st_size,
                    "sha256": digest,
                })
            good = evaluate(root / "output", root / "request.json")
            self.assertEqual(good["status"], "PASS")
            file_path.write_bytes(b"%PDF-1.4 changed report fixture")
            corrupted = evaluate(root / "output", root / "request.json")
            self.assertEqual(corrupted["status"], "REVIEW_REQUIRED")
            self.assertIn("DOCUMENT_DIGEST_MISMATCH",
                          [x["issue_type"] for x in corrupted["blocking_issues"]])
            file_path.unlink()
            missing = evaluate(root / "output", root / "request.json")
            self.assertIn("DOCUMENT_FILE_MISSING",
                          [x["issue_type"] for x in missing["blocking_issues"]])

    def test_corporate_document_claim_without_index_is_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "request.json", {"sources": {}})
            write_json(root / "output/CORP_DOCS/status.json", {
                "source_key": "CORP_DOCS", "status": "DATA_FOUND",
                "discovery_status": "COMPLETE",
                "documents_declared": 1, "downloaded": 1, "failed": 0, "skipped": 0,
            })
            outcome = evaluate(root / "output", root / "request.json")
            self.assertEqual(outcome["status"], "REVIEW_REQUIRED")
            self.assertIn("DOCUMENT_INDEX_MISSING",
                          [x["issue_type"] for x in outcome["blocking_issues"]])


if __name__ == "__main__":
    unittest.main()
