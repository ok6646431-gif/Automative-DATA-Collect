import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.scope_quality import classify_archive_summary


class PostNormalizationArchiveClassificationTests(unittest.TestCase):
    def _root(self, td):
        root = Path(td)
        (root / "Collection_Completeness.json").write_text(
            json.dumps({"status": "COMPLETE"}), encoding="utf-8"
        )
        return root

    def test_passed_final_user_tree_overrides_stale_pre_normalization_check(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            summary = {
                "acceptance_checks": {
                    "user_excel_exports": True,
                    "envinfo_pdf_complete": True,
                    "public_policy_present": True,
                    "review_report_present": True,
                    "user_machine_formats_absent": False,
                    "sustainability_coverage_sufficient": True,
                    "guideline_reference_present": False,
                },
                "user_format_normalization": {
                    "acceptance": {
                        "status": "PASS",
                        "checks": {
                            "user_machine_formats_absent": True,
                            "structured_user_exports_valid": True,
                            "user_pdfs_structurally_valid": True,
                        },
                        "failures": [],
                    }
                },
            }
            result = classify_archive_summary(root, summary)
            self.assertTrue(result["acceptance_checks"]["user_machine_formats_absent"])
            self.assertTrue(result["blocking_acceptance_checks"]["user_machine_formats_absent"])
            self.assertEqual(result["archive_completeness"], "COMPLETE")
            self.assertEqual(result["study_enrichment_readiness"], "NEEDS_REFERENCE")

    def test_failed_post_normalization_result_cannot_relax_stale_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            summary = {
                "acceptance_checks": {
                    "user_machine_formats_absent": False,
                    "guideline_reference_present": True,
                },
                "user_format_normalization": {
                    "acceptance": {
                        "status": "FAIL",
                        "checks": {"user_machine_formats_absent": True},
                        "failures": [{"check": "OTHER_FINAL_CHECK", "detail": "failed"}],
                    }
                },
            }
            result = classify_archive_summary(root, summary)
            self.assertFalse(result["blocking_acceptance_checks"]["user_machine_formats_absent"])
            self.assertEqual(result["archive_completeness"], "INCOMPLETE")
            self.assertEqual(result["post_normalization_acceptance_checks"], {})


if __name__ == "__main__":
    unittest.main()
