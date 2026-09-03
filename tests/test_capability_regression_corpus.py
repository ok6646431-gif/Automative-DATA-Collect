import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.g0_report_enrichment import strong_report_semantics
from orchestrator.g0_rename_chronology_recovery import parse_official_name_chain
from orchestrator.requested_scope import (
    _address_match,
    _generic_same_entity_site_label,
    _road_building_numbers,
)
from orchestrator.collection_completeness import requested_scope_binding_rows


CASES = json.loads(
    (Path(__file__).parent / "regression_cases" / "capability_cases.json").read_text(encoding="utf-8")
)["cases"]


class CapabilityRegressionCorpusTests(unittest.TestCase):
    def test_corpus(self):
        for case in CASES:
            with self.subTest(case=case["id"], capability=case["capability"]):
                kind = case["kind"]
                if kind == "report_semantics":
                    actual = strong_report_semantics(case["label"], case["url"], "https://official.example/sustainability/")
                    self.assertEqual(actual, case["expected"])
                elif kind == "rename_chain":
                    parsed = parse_official_name_chain(case["text"], case["current_name"])
                    self.assertIsNotNone(parsed)
                    self.assertEqual(parsed["predecessor"], case["expected_predecessor"])
                    self.assertEqual(parsed["date"], case["expected_date"])
                elif kind == "address_match":
                    self.assertEqual(_address_match(case["left"], case["right"]), case["expected"])
                elif kind == "road_number_overlap":
                    actual = sorted(_road_building_numbers(case["left"]) & _road_building_numbers(case["right"]))
                    self.assertEqual(actual, case["expected_numbers"])
                elif kind == "generic_site_label":
                    profile = {
                        "company_display_name": case["company"],
                        "requested_company_name": case["company"],
                        "aliases": [],
                    }
                    self.assertEqual(_generic_same_entity_site_label(case["source_name"], profile), case["expected"])
                elif kind == "scope_binding_guard":
                    with tempfile.TemporaryDirectory() as td:
                        root = Path(td)
                        target = {case["source"]: case["target_ids"]}
                        (root / "Requested_Scope.json").write_text(json.dumps({
                            "mode": case["mode"], "label": "target", "target_source_ids": target,
                        }), encoding="utf-8")
                        state = "DATA_PRESENT" if case["raw_data_present"] else "NO_DATA_CONFIRMED"
                        rows = requested_scope_binding_rows(root, [{"source": case["source"], "completeness_state": state}])
                        self.assertEqual(bool(rows), case["expected_blocker"])
                else:
                    self.fail(f"unknown regression corpus kind: {kind}")


if __name__ == "__main__":
    unittest.main()
