import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / "orchestrator"
if str(ORCH) not in sys.path:
    sys.path.insert(0, str(ORCH))

import archive_zip_dedup
import review_report


class ScopeConsistencyFinalTests(unittest.TestCase):
    def test_study_reference_does_not_downgrade_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "archive"
            reports = archive / "01_사용자자료" / "04_지속가능경영보고서"
            reports.mkdir(parents=True)
            for y in range(2020, 2027):
                (reports / f"report_{y}.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * 300)
            (root / "Company_Profile.json").write_text(json.dumps({
                "requested_history_window": {"start_year": 2020, "end_year": 2026}
            }), encoding="utf-8")
            docs_dir = root / "output" / "CORP_DOCS"
            docs_dir.mkdir(parents=True)
            docs = [
                "document_id,document_type,report_year,collection_status,stored_path\n"
            ]
            for y in range(2020, 2027):
                docs.append(f"D{y},SUSTAINABILITY_REPORT,{y},DOWNLOADED,report_{y}.pdf\n")
            (docs_dir / "document_index.csv").write_text("".join(docs), encoding="utf-8-sig")
            summary = {
                "acceptance_checks": {
                    "user_excel_exports": True,
                    "collection_completeness_complete": True,
                    "guideline_reference_present": False,
                },
                "blocking_acceptance_checks": {
                    "user_excel_exports": True,
                    "collection_completeness_complete": True,
                },
                "study_enrichment_checks": {"guideline_reference_present": False},
            }
            out = archive_zip_dedup._apply_sustainability_coverage(root, archive, summary)
            self.assertEqual(out["archive_completeness"], "COMPLETE")
            self.assertFalse(out["study_enrichment_checks"]["guideline_reference_present"])
            self.assertTrue(all(out["blocking_acceptance_checks"].values()))

    def test_review_report_filters_profile_sites_to_requested_candidates(self):
        profile = {
            "site_candidates": [
                {"candidate_id": "a", "site_name_raw": "기흥사업장", "address_raw": "A"},
                {"candidate_id": "b", "site_name_raw": "화성사업장", "address_raw": "B"},
                {"candidate_id": "c", "site_name_raw": "평택사업장", "address_raw": "C"},
                {"candidate_id": "d", "site_name_raw": "천안사업장", "address_raw": "D"},
                {"candidate_id": "e", "site_name_raw": "온양사업장", "address_raw": "E"},
                {"candidate_id": "sait", "site_name_raw": "수원(SAIT) 사업장", "address_raw": "S"},
            ]
        }
        scope = {"target_candidate_ids": ["a", "b", "c", "d", "e"]}
        selected = [s for s in profile["site_candidates"] if not scope["target_candidate_ids"] or s["candidate_id"] in set(scope["target_candidate_ids"])]
        self.assertEqual(len(selected), 5)
        self.assertNotIn("sait", {s["candidate_id"] for s in selected})


if __name__ == "__main__":
    unittest.main()
