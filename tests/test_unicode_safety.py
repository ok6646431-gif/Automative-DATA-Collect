import csv
import tempfile
import unittest
from pathlib import Path

from orchestrator.review_selection_common import stable_id, utf8_safe, write_csv


class UnicodeSafetyTests(unittest.TestCase):
    def test_stable_id_accepts_isolated_surrogate(self):
        bad = "energy K-BREF \uda82 technique"
        first = stable_id("SEM_", bad)
        second = stable_id("SEM_", bad)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("SEM_"))

    def test_utf8_safe_only_changes_malformed_text(self):
        valid = "유기화학산업 최적가용기법 기준서"
        self.assertEqual(utf8_safe(valid), valid)
        cleaned = utf8_safe("before\uda82after")
        cleaned.encode("utf-8")
        self.assertNotIn("\uda82", cleaned)

    def test_write_csv_sanitizes_rows_in_place_for_later_json_use(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "semantic.csv"
            rows = [{"statement": "before\uda82after", "other": "정상"}]
            write_csv(path, rows, ["statement", "other"])
            rows[0]["statement"].encode("utf-8")
            self.assertNotIn("\uda82", rows[0]["statement"])
            with path.open(encoding="utf-8-sig", newline="") as f:
                loaded = list(csv.DictReader(f))
            self.assertEqual(loaded[0]["statement"], rows[0]["statement"])


if __name__ == "__main__":
    unittest.main()
