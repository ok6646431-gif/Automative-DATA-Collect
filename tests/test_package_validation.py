import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "orchestrator"
if str(ORCHESTRATOR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR))

from package_run import declared_empty_row_stream, validate


class TestPackageValidation(unittest.TestCase):
    def test_declared_zero_row_stream_is_not_structural_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for source in ["ENVINFO", "PRTR", "CHEM_STATS", "CLEANSYS_AIR", "SOOSIRO_WATER"]:
                (root / source).mkdir(parents=True)
                status = {"source_key": source, "status": "NO_MATCH"}
                if source == "SOOSIRO_WATER":
                    status.update({"annual_rows": 0, "daily_rows": 0})
                    (root / source / "annual_rows.jsonl").write_text("", encoding="utf-8")
                    (root / source / "daily_rows.jsonl").write_text("", encoding="utf-8")
                (root / source / "status.json").write_text(json.dumps(status), encoding="utf-8")

            ok, results, review = validate(root)

            self.assertTrue(ok)
            self.assertEqual(results["SOOSIRO_WATER"]["checks"], [])
            self.assertEqual(review, [])

    def test_zero_row_stream_with_nonzero_declared_count_still_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for source in ["ENVINFO", "PRTR", "CHEM_STATS", "CLEANSYS_AIR", "SOOSIRO_WATER"]:
                (root / source).mkdir(parents=True)
                status = {"source_key": source, "status": "NO_MATCH"}
                if source == "SOOSIRO_WATER":
                    status.update({"annual_rows": 1, "daily_rows": 0})
                    (root / source / "annual_rows.jsonl").write_text("", encoding="utf-8")
                    (root / source / "daily_rows.jsonl").write_text("", encoding="utf-8")
                (root / source / "status.json").write_text(json.dumps(status), encoding="utf-8")

            ok, results, review = validate(root)

            self.assertFalse(ok)
            self.assertIn("zero_byte_artifact", results["SOOSIRO_WATER"]["checks"])
            self.assertTrue(any(x["source"] == "SOOSIRO_WATER" for x in review))

    def test_unexpected_empty_artifact_is_never_suppressed(self):
        self.assertFalse(declared_empty_row_stream(
            "SOOSIRO_WATER", Path("raw_annual/bad.json"), {"annual_rows": 0, "daily_rows": 0}
        ))


if __name__ == "__main__":
    unittest.main()
