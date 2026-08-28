import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "orchestrator"
if str(ORCHESTRATOR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR))

from package_run import (
    choose_icis,
    declared_empty_row_stream,
    package_health,
    validate,
    write_unavailable_source,
)


SOURCES = ["ENVINFO", "PRTR", "CHEM_STATS", "CLEANSYS_AIR", "SOOSIRO_WATER"]


def write_status(root, source, status="NO_MATCH", **extra):
    d = root / source
    d.mkdir(parents=True, exist_ok=True)
    payload = {"source_key": source, "status": status, **extra}
    (d / "status.json").write_text(json.dumps(payload), encoding="utf-8")


class TestPackageValidation(unittest.TestCase):
    def test_declared_zero_row_stream_is_not_structural_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for source in SOURCES:
                write_status(root, source)
                if source == "SOOSIRO_WATER":
                    write_status(root, source, annual_rows=0, daily_rows=0)
                    (root / source / "annual_rows.jsonl").write_text("", encoding="utf-8")
                    (root / source / "daily_rows.jsonl").write_text("", encoding="utf-8")

            ok, results, review = validate(root)

            self.assertTrue(ok)
            self.assertEqual(results["SOOSIRO_WATER"]["checks"], [])
            self.assertEqual(review, [])
            self.assertEqual(package_health(results, review), "PASS")

    def test_zero_row_stream_with_nonzero_declared_count_still_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for source in SOURCES:
                write_status(root, source)
                if source == "SOOSIRO_WATER":
                    write_status(root, source, annual_rows=1, daily_rows=0)
                    (root / source / "annual_rows.jsonl").write_text("", encoding="utf-8")
                    (root / source / "daily_rows.jsonl").write_text("", encoding="utf-8")

            ok, results, review = validate(root)

            self.assertFalse(ok)
            self.assertIn("zero_byte_artifact", results["SOOSIRO_WATER"]["checks"])
            self.assertTrue(any(x["source"] == "SOOSIRO_WATER" for x in review))
            self.assertEqual(package_health(results, review), "FAIL")

    def test_public_source_outage_is_degraded_not_structural_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for source in SOURCES:
                status = "REMOTE_HOST_UNREACHABLE" if source == "PRTR" else "NO_MATCH"
                write_status(root, source, status)

            ok, results, review = validate(root)

            self.assertFalse(ok)
            self.assertIn("terminal_failure", results["PRTR"]["checks"])
            self.assertEqual(package_health(results, review), "DEGRADED")

    def test_retry_exhausted_synthetic_source_is_degraded_and_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for source in SOURCES:
                if source == "CHEM_STATS":
                    write_unavailable_source(root, source, "all retries exhausted")
                else:
                    write_status(root, source)

            ok, results, review = validate(root)

            self.assertFalse(ok)
            self.assertEqual(results["CHEM_STATS"]["status"], "COLLECTION_FAILED_RETRY_EXHAUSTED")
            self.assertTrue(results["CHEM_STATS"].get("synthetic_status"))
            self.assertEqual(package_health(results, review), "DEGRADED")

    def test_configuration_error_remains_structural_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for source in SOURCES:
                status = "CONFIG_ERROR" if source == "ENVINFO" else "NO_MATCH"
                write_status(root, source, status)

            _, results, review = validate(root)

            self.assertEqual(package_health(results, review), "FAIL")

    def test_missing_status_remains_structural_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for source in SOURCES:
                if source != "CLEANSYS_AIR":
                    write_status(root, source)

            _, results, review = validate(root)

            self.assertEqual(results["CLEANSYS_AIR"]["status"], "MISSING_STATUS")
            self.assertEqual(package_health(results, review), "FAIL")

    def test_choose_icis_preserves_failed_attempt_after_retries(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            attempt = root / "icis-attempt-1"
            write_status(attempt, "PRTR", "REMOTE_HOST_UNREACHABLE")
            write_status(attempt, "CHEM_STATS", "REQUEST_OR_PARSE_FAILED")

            chosen, state = choose_icis(root)

            self.assertEqual(chosen, attempt)
            self.assertEqual(state, "FAILED_ATTEMPT_PRESERVED")

    def test_choose_icis_prefers_good_attempt_over_failed_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            failed = root / "icis-attempt-1"
            good = root / "icis-attempt-2"
            write_status(failed, "PRTR", "REMOTE_HOST_UNREACHABLE")
            write_status(failed, "CHEM_STATS", "REQUEST_OR_PARSE_FAILED")
            write_status(good, "PRTR", "NO_MATCH")
            write_status(good, "CHEM_STATS", "NO_MATCH")

            chosen, state = choose_icis(root)

            self.assertEqual(chosen, good)
            self.assertEqual(state, "GOOD_ATTEMPT")

    def test_unexpected_empty_artifact_is_never_suppressed(self):
        self.assertFalse(declared_empty_row_stream(
            "SOOSIRO_WATER", Path("raw_annual/bad.json"), {"annual_rows": 0, "daily_rows": 0}
        ))


if __name__ == "__main__":
    unittest.main()
