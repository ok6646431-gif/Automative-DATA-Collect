import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))

from orchestrator.scope_quality import (
    classify_archive_summary,
    is_blocking_document_gap,
    scoped_envinfo_attachment_status,
)


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    if not fields:
        fields = ["value"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


class ScopeQualityRegressionTests(unittest.TestCase):
    def test_outside_scope_envinfo_failure_is_not_scoped_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_csv(root / "output" / "ENVINFO" / "attachment_index.csv", [
                {
                    "compId": "TARGET",
                    "compNm": "대상사업장",
                    "year": "2024",
                    "original_filename": "ok.pdf",
                    "collection_status": "DOWNLOADED",
                },
                {
                    "compId": "OUTSIDE",
                    "compNm": "범위밖사업장",
                    "year": "2023",
                    "original_filename": "failed.pdf",
                    "collection_status": "DOWNLOAD_FAILED",
                },
            ])
            scope = {
                "mode": "SITE_SET",
                "target_source_ids": {"ENVINFO": {"TARGET"}},
            }
            state = scoped_envinfo_attachment_status(root, {}, scope)
            self.assertEqual(len(state["raw_failed"]), 1)
            self.assertEqual(len(state["scoped_failed"]), 0)
            self.assertEqual(len(state["outside_scope_failed"]), 1)

    def test_in_scope_envinfo_failure_remains_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_csv(root / "output" / "ENVINFO" / "attachment_index.csv", [
                {
                    "compId": "TARGET",
                    "compNm": "대상사업장",
                    "year": "2024",
                    "original_filename": "failed.pdf",
                    "collection_status": "DOWNLOAD_FAILED",
                },
            ])
            scope = {
                "mode": "SITE_SET",
                "target_source_ids": {"ENVINFO": {"TARGET"}},
            }
            state = scoped_envinfo_attachment_status(root, {}, scope)
            self.assertEqual(len(state["scoped_failed"]), 1)

    def test_context_gap_does_not_block_document_completeness(self):
        self.assertFalse(is_blocking_document_gap({
            "gap_id": "NONPUBLIC_INTERNAL_SOP_OUT_OF_SCOPE",
            "source_key": "SAMSUNG_INTERNAL",
            "severity": "LOW",
            "reason": "비공개 내부 SOP는 공개자료 수집 범위 밖",
        }))
        self.assertTrue(is_blocking_document_gap({
            "gap_id": "DECLARED_DOCUMENT_MISSING",
            "blocking": True,
            "severity": "HIGH",
        }))

    def test_missing_guideline_is_study_readiness_not_archive_collection_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Collection_Completeness.json").write_text(
                json.dumps({"status": "COMPLETE"}, ensure_ascii=False),
                encoding="utf-8",
            )
            summary = {
                "archive_root": "기업_환경자료",
                "acceptance_checks": {
                    "user_excel_exports": True,
                    "envinfo_pdf_complete": True,
                    "sustainability_minimum_5": True,
                    "public_policy_present": True,
                    "guideline_reference_present": False,
                    "review_report_present": True,
                },
            }
            result = classify_archive_summary(root, summary)
            self.assertEqual(result["archive_completeness"], "COMPLETE")
            self.assertEqual(result["study_enrichment_readiness"], "NEEDS_REFERENCE")
            self.assertTrue(result["blocking_acceptance_checks"]["collection_completeness_complete"])

    def test_samsung_ds_core_requested_scope_is_five_and_sait_is_preserved_as_candidate(self):
        discovery_path = Path(__file__).resolve().parents[1] / "requests" / "company_discovery.json"
        discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
        if discovery.get("request_id") != "samsung-electronics-ds-env-20260830-v1":
            self.skipTest("tracked Discovery is not the Samsung DS regression fixture")
        wanted = discovery["requested_scope"]["candidate_ids"]
        self.assertEqual(wanted, [
            "samsung-ds-giheung",
            "samsung-ds-hwaseong",
            "samsung-ds-pyeongtaek",
            "samsung-ds-cheonan",
            "samsung-ds-onyang",
        ])
        all_candidates = {
            row["candidate_id"] for row in discovery.get("domestic_site_candidates", [])
        }
        self.assertIn("samsung-ds-suwon-sait", all_candidates)
        self.assertNotIn("samsung-ds-suwon-sait", wanted)


if __name__ == "__main__":
    unittest.main()
