import unittest
from unittest.mock import patch

from orchestrator.postprocess import coverage_rows


PROFILE = {
    "company_display_name": "테스트화학",
    "aliases": [{"term": "테스트화학"}],
    "related_entity_exclusions": [],
}


def base_row(source="PRTR", status="SHORT_COVERAGE"):
    return {
        "company_id": "COMP_TEST",
        "source_key": source,
        "coverage_scope": "1 linked/candidate sites",
        "available_start": "UNKNOWN",
        "available_end": "UNKNOWN",
        "collected_start": 2022 if status == "SHORT_COVERAGE" else "UNKNOWN",
        "collected_end": 2024 if status == "SHORT_COVERAGE" else "UNKNOWN",
        "rounds_or_detail": "3 source identities",
        "meets_minimum": False,
        "event_baseline_status": "PENDING_EVENT_LINK",
        "comparability_status": "PENDING",
        "coverage_status": status,
        "next_action": "extend collection window to minimum policy/full public history",
    }


def audit_row(year, state, source="PRTR"):
    return {
        "source": source,
        "period_kind": "YEAR",
        "period": str(year),
        "expected": "Y",
        "query_state": "COMPLETE" if state in {"DATA_PRESENT", "NO_DATA_CONFIRMED"} else "FAILED",
        "data_present": "Y" if state == "DATA_PRESENT" else "N",
        "completeness_state": state,
        "evidence": "test",
        "user_note": "",
    }


class CoverageSemanticsTests(unittest.TestCase):
    def run_coverage(self, base, audited):
        with patch("orchestrator.postprocess._BASE_COVERAGE_ROWS", return_value=[base]), \
             patch("orchestrator.postprocess._build_request", return_value={}), \
             patch("orchestrator.postprocess._public_rows", return_value=audited):
            return coverage_rows("unused", "COMP_TEST", [], PROFILE)[0]

    def test_confirmed_no_data_years_do_not_become_fake_zero_data_points(self):
        audited = [
            audit_row(2020, "NO_DATA_CONFIRMED"),
            audit_row(2021, "NO_DATA_CONFIRMED"),
            audit_row(2022, "DATA_PRESENT"),
            audit_row(2023, "DATA_PRESENT"),
            audit_row(2024, "DATA_PRESENT"),
        ]
        row = self.run_coverage(base_row(), audited)

        self.assertEqual(row["coverage_status"], "SHORT_DATA_SERIES_CONFIRMED")
        self.assertFalse(row["meets_minimum"])
        self.assertEqual(row["collected_start"], 2022)
        self.assertEqual(row["collected_end"], 2024)
        self.assertEqual(row["comparability_status"], "SHORT_SERIES_CONFIRMED_NO_DATA")
        self.assertIn("no_data_confirmed=2020|2021", row["rounds_or_detail"])
        self.assertIn("do not impute", row["next_action"])

    def test_failed_year_keeps_collection_gap_state(self):
        audited = [
            audit_row(2020, "NO_DATA_CONFIRMED"),
            audit_row(2021, "QUERY_FAILED"),
            audit_row(2022, "DATA_PRESENT"),
            audit_row(2023, "DATA_PRESENT"),
            audit_row(2024, "DATA_PRESENT"),
        ]
        row = self.run_coverage(base_row(), audited)

        self.assertEqual(row["coverage_status"], "SHORT_COVERAGE")
        self.assertEqual(row["next_action"], "extend collection window to minimum policy/full public history")
        self.assertIn("query_complete=4/5", row["rounds_or_detail"])

    def test_all_successful_empty_years_are_no_data_confirmed(self):
        audited = [audit_row(year, "NO_DATA_CONFIRMED") for year in range(2020, 2025)]
        row = self.run_coverage(base_row(status="NO_DATA"), audited)

        self.assertEqual(row["coverage_status"], "NO_DATA_CONFIRMED")
        self.assertFalse(row["meets_minimum"])
        self.assertEqual(row["collected_start"], 2020)
        self.assertEqual(row["collected_end"], 2024)
        self.assertEqual(row["comparability_status"], "NOT_APPLICABLE_NO_DATA")

    def test_unqueried_or_failed_empty_period_is_not_confirmed_no_data(self):
        audited = [
            audit_row(2020, "NO_DATA_CONFIRMED"),
            audit_row(2021, "NO_DATA_CONFIRMED"),
            audit_row(2022, "QUERY_FAILED"),
            audit_row(2023, "NO_DATA_CONFIRMED"),
            audit_row(2024, "NO_DATA_CONFIRMED"),
        ]
        row = self.run_coverage(base_row(status="NO_DATA"), audited)

        self.assertEqual(row["coverage_status"], "NO_DATA")
        self.assertEqual(row["collected_start"], "UNKNOWN")
        self.assertEqual(row["collected_end"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
