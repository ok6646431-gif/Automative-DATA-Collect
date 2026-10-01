import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
from archive_builder import sustainability_series_expected


class ArchiveSeriesApplicabilityTests(unittest.TestCase):
    def test_explicit_empty_annual_series_is_not_applicable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Document_Evidence.json").write_text(
                json.dumps({
                    "discovery_scope": {"annual_series": []},
                    "documents": [{
                        "document_type": "ENVIRONMENTAL_MANAGEMENT",
                        "verification_status": "SOURCE_VERIFIED",
                    }],
                }),
                encoding="utf-8",
            )
            self.assertFalse(sustainability_series_expected(root))

    def test_explicit_sustainability_series_is_applicable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Document_Evidence.json").write_text(
                json.dumps({
                    "discovery_scope": {"annual_series": ["SUSTAINABILITY_REPORT"]},
                    "documents": [],
                }),
                encoding="utf-8",
            )
            self.assertTrue(sustainability_series_expected(root))

    def test_missing_contract_preserves_legacy_fail_closed_behavior(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(sustainability_series_expected(Path(td)))

    def test_legacy_document_evidence_with_annual_report_is_applicable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Document_Evidence.json").write_text(
                json.dumps({
                    "documents": [{
                        "document_type": "SUSTAINABILITY_REPORT",
                        "verification_status": "SOURCE_VERIFIED",
                    }],
                }),
                encoding="utf-8",
            )
            self.assertTrue(sustainability_series_expected(root))


if __name__ == "__main__":
    unittest.main()
