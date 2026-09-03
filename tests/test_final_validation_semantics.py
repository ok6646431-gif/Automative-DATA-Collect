import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
import package_run
import postprocess


def write_csv(path, rows, fields):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)


class FinalValidationSemanticsTests(unittest.TestCase):
    def test_declared_empty_chemical_backfill_audit_is_not_corruption(self):
        status = {"source_id_backfill_attempts": 0}
        self.assertTrue(
            package_run.declared_empty_row_stream(
                "CHEM_STATS", Path("source_id_backfill_attempts.jsonl"), status
            )
        )

    def test_legacy_lot_address_bridges_only_with_official_name_and_public_corroboration(self):
        profile = {
            "company_display_name": "테스트타이어(주)",
            "aliases": [{"term": "테스트타이어"}],
            "site_candidates": [{
                "candidate_id": "GS",
                "site_name_raw": "테스트타이어 곡성공장",
                "address_raw": "전남광주통합특별시 곡성군 입면 금호길 85-63",
                "identity_status": "CONFIRMED",
                "verification_state": "VERIFIED",
            }],
        }
        candidates = [
            {
                "source_key": "ENVINFO", "source_site_id": "E1",
                "source_site_name_raw": "테스트타이어(주) 곡성공장",
                "source_address_raw": "전라남도 곡성군 입면 송전리 39-5",
                "years": ["2024"], "raw_ref": "env",
            },
            {
                "source_key": "PRTR", "source_site_id": "P1",
                "source_site_name_raw": "테스트타이어(주) 곡성공장",
                "source_address_raw": "전남광주통합특별시 곡성군 입면 금호길 85-63",
                "years": ["2024"], "raw_ref": "prtr",
            },
        ]
        _, sites, identities, validations = postprocess.resolve_identity(candidates, profile)
        by_source = {r["source_key"]: r for r in identities}
        self.assertEqual(by_source["ENVINFO"]["match_status"], "CONFIRMED")
        self.assertEqual(
            by_source["ENVINFO"]["match_basis"],
            "OFFICIAL_SITE_NAME_LEGACY_ADDRESS_CROSS_SOURCE",
        )
        self.assertEqual(by_source["ENVINFO"]["canonical_site_id"], by_source["PRTR"]["canonical_site_id"])
        self.assertFalse(any(v.get("object_key") == "ENVINFO:E1" for v in validations))
        self.assertFalse(any(s.get("identity_status") == "NEW_SITE_CANDIDATE" for s in sites))

    def test_verified_no_match_is_not_short_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for source in postprocess.SOURCES:
                (root / source).mkdir(parents=True)
                (root / source / "status.json").write_text(
                    json.dumps({"source_key": source, "status": "NO_DATA"}), encoding="utf-8"
                )
            (root / "CLEANSYS_AIR" / "status.json").write_text(
                json.dumps({"source_key": "CLEANSYS_AIR", "status": "RESPONSE_OK_NO_TERM_MATCH"}),
                encoding="utf-8",
            )
            (root / "SOOSIRO_WATER" / "status.json").write_text(
                json.dumps({
                    "source_key": "SOOSIRO_WATER", "status": "NO_MATCH",
                    "annual_years": [2020, 2021, 2022, 2023, 2024, 2025],
                    "requests": 36, "errors": 0,
                }), encoding="utf-8",
            )
            rows = {r["source_key"]: r for r in postprocess.coverage_rows(root, "COMP_X", [])}
            self.assertEqual(rows["CLEANSYS_AIR"]["coverage_status"], "NO_DATA_CONFIRMED")
            self.assertEqual(rows["SOOSIRO_WATER"]["coverage_status"], "NO_DATA_CONFIRMED")
            self.assertEqual(rows["SOOSIRO_WATER"]["collected_start"], 2020)
            self.assertEqual(rows["SOOSIRO_WATER"]["collected_end"], 2025)

    def test_company_wide_identity_outside_requested_sites_is_nonblocking_but_retained(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            profile = {
                "company_display_name": "테스트타이어(주)",
                "aliases": [{"term": "테스트타이어"}],
                "requested_scope": {"mode": "SITE_SET", "candidate_ids": ["G"]},
                "site_candidates": [{
                    "candidate_id": "G", "site_name_raw": "테스트타이어 광주공장",
                    "address_raw": "광주광역시 광산구 어등대로 658",
                    "identity_status": "CONFIRMED", "verification_state": "VERIFIED",
                }],
            }
            (root / "Company_Profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            write_csv(root / "Source_Identity.csv", [
                {"source_key": "ENVINFO", "source_site_id": "G1", "source_site_name_raw": "테스트타이어 광주공장", "source_address_raw": "광주광역시 광산구 어등대로 658"},
                {"source_key": "ENVINFO", "source_site_id": "S1", "source_site_name_raw": "테스트타이어 서울사무소", "source_address_raw": "서울특별시 종로구 테스트로 1"},
            ], ["source_key", "source_site_id", "source_site_name_raw", "source_address_raw"])
            validations = [
                {"validation_id": "VG", "object_type": "SOURCE_IDENTITY", "object_key": "ENVINFO:G1", "severity": "HIGH", "status": "REVIEW_REQUIRED", "notes": ""},
                {"validation_id": "VS", "object_type": "SOURCE_IDENTITY", "object_key": "ENVINFO:S1", "severity": "HIGH", "status": "REVIEW_REQUIRED", "notes": ""},
            ]
            write_csv(root / "Validation_Queue.csv", validations, ["validation_id", "object_type", "object_key", "severity", "status", "notes"])
            (root / "REVIEW_REQUIRED.json").write_text(json.dumps(validations), encoding="utf-8")
            changed = package_run._demote_out_of_scope_identity_reviews(
                root,
                {"mode": "SITE_SET", "target_source_ids": {"ENVINFO": ["G1"]}},
            )
            self.assertEqual(changed, 1)
            queue = list(csv.DictReader((root / "Validation_Queue.csv").open(encoding="utf-8-sig")))
            by_id = {r["validation_id"]: r for r in queue}
            self.assertEqual(by_id["VS"]["status"], "OUT_OF_SCOPE_RETAINED")
            self.assertEqual(by_id["VG"]["status"], "REVIEW_REQUIRED")
            review = json.loads((root / "REVIEW_REQUIRED.json").read_text(encoding="utf-8"))
            self.assertEqual([r["validation_id"] for r in review], ["VG"])


if __name__ == "__main__":
    unittest.main()
