import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.bootstrap_inputs import bootstrap_inputs


def source_policy():
    return {
        "ENVINFO": {"requested_window": {"start_year": 2020, "end_year": 2024}, "prefer_full_history": False},
        "PRTR": {"requested_window": {"start_year": 2020, "end_year": 2024}, "prefer_full_history": False},
        "CHEM_STATS": {"available_survey_rounds": [2020, 2022, 2024], "prefer_full_history": True},
        "CLEANSYS_AIR": {"available_history": {"start_year": 2015, "end_year": 2024}, "prefer_full_history": True},
        "SOOSIRO_WATER": {"available_history": {"start_year": 2020, "end_year": 2024}, "daily_available_years": [2024], "prefer_full_history": True},
    }


def discovery_payload():
    return {
        "schema_version": "1.0",
        "request_id": "bootstrap-discovery-test",
        "requested_company_name": "테스트화학",
        "current_legal_name": "테스트화학 주식회사",
        "company_verification_state": "VERIFIED",
        "company_aliases": [{"name": "테스트화학", "alias_type": "current_alias", "verification_state": "VERIFIED"}],
        "historical_legal_names": [],
        "corporate_restructuring_evidence": [],
        "domestic_site_candidates": [],
        "identity_evidence": [],
        "related_entity_exclusions": [],
        "unresolved_items": [],
        "event_evidence_references": [],
        "collection_policy": {"minimum_history_years": 5, "sources": source_policy()},
    }


def fallback_profile():
    return {
        "profile_version": "2.0",
        "request_id": "bootstrap-profile-test",
        "company_display_name": "대체화학",
        "aliases": [{"term": "대체화학", "scope": "current", "year_start": 2020, "year_end": "auto"}],
        "source_plan": {
            "ENVINFO": {"start_year": 2020, "end_year": 2024},
            "PRTR": {"start_year": 2020, "end_year": 2024},
            "CHEM_STATS": {"years": [2020, 2022, 2024]},
            "CLEANSYS_AIR": {"start_year": 2015, "end_year": 2024},
            "SOOSIRO_WATER": {"annual_years": [2020, 2021, 2022, 2023, 2024], "daily_years": [2024]},
        },
    }


class TestBootstrapInputs(unittest.TestCase):
    def test_discovery_is_preferred_and_compiled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            discovery = root / "company_discovery.json"
            fallback = root / "company_profile.json"
            profile_out = root / "runtime" / "profile.json"
            request_out = root / "runtime" / "request.json"
            summary_out = root / "runtime" / "summary.json"
            discovery.write_text(json.dumps(discovery_payload(), ensure_ascii=False), encoding="utf-8")
            fallback.write_text(json.dumps(fallback_profile(), ensure_ascii=False), encoding="utf-8")

            result = bootstrap_inputs(discovery, fallback, profile_out, request_out, summary_out)

            self.assertEqual(result["bootstrap_mode"], "DISCOVERY")
            profile = json.loads(profile_out.read_text(encoding="utf-8"))
            request = json.loads(request_out.read_text(encoding="utf-8"))
            summary = json.loads(summary_out.read_text(encoding="utf-8"))
            self.assertEqual(profile["request_id"], "bootstrap-discovery-test")
            self.assertEqual(request["company_display_name"], "테스트화학 주식회사")
            self.assertEqual(summary["bootstrap_mode"], "DISCOVERY")

    def test_profile_fallback_remains_compatible(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            discovery = root / "missing_discovery.json"
            fallback = root / "company_profile.json"
            profile_out = root / "runtime" / "profile.json"
            request_out = root / "runtime" / "request.json"
            summary_out = root / "runtime" / "summary.json"
            fallback.write_text(json.dumps(fallback_profile(), ensure_ascii=False), encoding="utf-8")

            result = bootstrap_inputs(discovery, fallback, profile_out, request_out, summary_out)

            self.assertEqual(result["bootstrap_mode"], "PROFILE_FALLBACK")
            self.assertEqual(json.loads(profile_out.read_text(encoding="utf-8"))["request_id"], "bootstrap-profile-test")
            self.assertEqual(json.loads(request_out.read_text(encoding="utf-8"))["company_display_name"], "대체화학")
            self.assertEqual(json.loads(summary_out.read_text(encoding="utf-8"))["bootstrap_mode"], "PROFILE_FALLBACK")

    def test_missing_both_inputs_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(FileNotFoundError):
                bootstrap_inputs(
                    root / "missing_discovery.json",
                    root / "missing_profile.json",
                    root / "profile.json",
                    root / "request.json",
                    root / "summary.json",
                )


if __name__ == "__main__":
    unittest.main()
