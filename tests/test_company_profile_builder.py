import copy
import unittest

from orchestrator.company_profile_builder import compile_discovery
from orchestrator.request_builder import build


def discovery():
    return {
        "schema_version": "1.0", "request_id": "synthetic", "requested_company_name": "현재산업",
        "current_legal_name": "현재산업 주식회사", "company_verification_state": "VERIFIED",
        "company_aliases": [{"name": "현재산업", "alias_type": "current_alias", "verification_state": "VERIFIED"}],
        "historical_legal_names": [], "corporate_restructuring_evidence": [],
        "domestic_site_candidates": [], "identity_evidence": [], "related_entity_exclusions": [],
        "unresolved_items": [], "event_evidence_references": [],
        "collection_policy": {"minimum_history_years": 5, "sources": {
            "ENVINFO": {"requested_window": {"start_year": 2022, "end_year": 2024}, "prefer_full_history": False},
            "PRTR": {"available_history": {"start_year": 2014, "end_year": 2024}, "prefer_full_history": True},
            "CHEM_STATS": {"available_survey_rounds": [2018, 2020, 2022, 2024], "prefer_full_history": True},
            "CLEANSYS_AIR": {"available_history": {"start_year": 2015, "end_year": 2025}},
            "SOOSIRO_WATER": {"available_history": {"start_year": 2017, "end_year": 2025}, "daily_available_years": [2024, 2025]}
        }}
    }


class TestCompanyProfileBuilder(unittest.TestCase):
    def test_normal_company_compiles_for_existing_builder(self):
        profile, summary = compile_discovery(discovery())
        request = build(profile)
        self.assertEqual(request["company_display_name"], "현재산업 주식회사")
        self.assertEqual(summary["review_required_count"], 0)

    def test_historical_name_is_bounded(self):
        data = discovery()
        data["historical_legal_names"] = [{"name": "과거산업", "alias_type": "former_legal_name",
                                            "active_period": {"start_year": 2014, "end_year": 2019}}]
        profile, _ = compile_discovery(data)
        old = next(x for x in profile["aliases"] if x["term"] == "과거산업")
        self.assertEqual((old["year_start"], old["year_end"]), (2014, 2019))
        spec = next(x for x in build(profile)["sources"]["PRTR"]["search_terms"] if x["term"] == "과거산업")
        self.assertEqual((spec["year_start"], spec["year_end"]), (2014, 2019))

    def test_unbounded_historical_name_is_preserved_but_not_searched(self):
        data = discovery()
        data["historical_legal_names"] = [{"name": "기간미상산업", "alias_type": "former_legal_name"}]
        profile, summary = compile_discovery(data)
        old = next(x for x in profile["aliases"] if x["term"] == "기간미상산업")
        self.assertFalse(old["search_enabled"])
        request = build(profile)
        self.assertNotIn("기간미상산업", request["sources"]["ENVINFO"]["search_terms"])
        self.assertTrue(any(x["code"] == "HISTORICAL_ALIAS_PERIOD_UNRESOLVED"
                            for x in summary["unresolved_discovery_items"]))

    def test_rename_is_context_not_identity_merge(self):
        data = discovery()
        data["corporate_restructuring_evidence"] = [{"event_type": "rename", "source_locator": "evidence://rename"}]
        profile, _ = compile_discovery(data)
        self.assertEqual(profile["corporate_restructuring_evidence"][0]["event_type"], "rename")
        self.assertNotIn("canonical_site_id", profile["corporate_restructuring_evidence"][0])

    def test_merger_and_spin_off_do_not_create_aliases_or_merges(self):
        data = discovery()
        data["corporate_restructuring_evidence"] = [{"event_type": "merger"}, {"event_type": "spin_off"}]
        profile, _ = compile_discovery(data)
        self.assertEqual(len(profile["aliases"]), 2)
        self.assertEqual(profile["site_address_anchors"], {})

    def test_similar_related_company_is_excluded_with_evidence_preserved(self):
        data = discovery()
        data["related_entity_exclusions"] = [{"name": "현재산업에너지", "reason": "separate entity",
                                                "source_locator": "evidence://x", "verification_state": "VERIFIED"}]
        profile, summary = compile_discovery(data)
        self.assertEqual(profile["related_entity_exclusions"], ["현재산업에너지"])
        self.assertEqual(summary["related_entity_exclusions"][0]["source_locator"], "evidence://x")

    def test_unverified_related_company_is_review_only(self):
        data = discovery()
        data["related_entity_exclusions"] = [
            {"name": "현재산업에너지", "verification_state": "PARTIAL", "source_locator": "evidence://partial"},
            "현재산업서비스",
        ]
        profile, summary = compile_discovery(data)
        self.assertEqual(profile["related_entity_exclusions"], [])
        self.assertEqual(profile["related_entity_exclusion_evidence"], data["related_entity_exclusions"])
        codes = [x["code"] for x in summary["unresolved_discovery_items"]]
        self.assertEqual(codes.count("RELATED_ENTITY_EXCLUSION_NOT_VERIFIED"), 2)

    def test_same_address_different_units_remain_separate_candidates(self):
        data = discovery()
        data["domestic_site_candidates"] = [
            {"candidate_id": "a", "site_name_raw": "1공장", "address_raw": "같은 주소", "business_unit_raw": "A"},
            {"candidate_id": "b", "site_name_raw": "2공장", "address_raw": "같은 주소", "business_unit_raw": "B"}]
        profile, _ = compile_discovery(data)
        self.assertEqual([x["candidate_id"] for x in profile["site_candidates"]], ["a", "b"])
        self.assertEqual(profile["site_address_anchors"], {})

    def test_unresolved_site_survives_as_review_required(self):
        data = discovery()
        data["unresolved_items"] = [{"code": "SITE_IDENTITY_UNRESOLVED", "subject": "a", "detail": "ambiguous"}]
        profile, summary = compile_discovery(data)
        self.assertEqual(profile["discovery_review_required"][0]["status"], "REVIEW_REQUIRED")
        self.assertEqual(summary["review_required_count"], 1)

    def test_short_request_is_extended_to_five_consecutive_years(self):
        profile, _ = compile_discovery(discovery())
        self.assertEqual(profile["source_plan"]["ENVINFO"], {"start_year": 2020, "end_year": 2024})

    def test_chemical_statistics_uses_disclosed_rounds_not_annual_years(self):
        profile, _ = compile_discovery(discovery())
        self.assertEqual(profile["source_plan"]["CHEM_STATS"]["years"], [2018, 2020, 2022, 2024])
        self.assertNotIn(2019, profile["source_plan"]["CHEM_STATS"]["years"])

    def test_chemical_round_span_uses_inclusive_calendar_years(self):
        data = discovery()
        data["collection_policy"]["sources"]["CHEM_STATS"] = {
            "available_survey_rounds": [2020, 2022, 2024], "prefer_full_history": True}
        _, summary = compile_discovery(data)
        self.assertFalse(any(x["code"] == "SURVEY_ROUND_SPAN_SHORT"
                             for x in summary["unresolved_discovery_items"]))

    def test_chemical_two_rounds_do_not_meet_minimum(self):
        data = discovery()
        data["collection_policy"]["sources"]["CHEM_STATS"] = {
            "available_survey_rounds": [2020, 2024], "prefer_full_history": True}
        _, summary = compile_discovery(data)
        self.assertTrue(any(x["code"] == "SURVEY_ROUND_SPAN_SHORT"
                            for x in summary["unresolved_discovery_items"]))

    def test_structured_sources_prefer_full_history_and_water_modes_stay_separate(self):
        profile, _ = compile_discovery(discovery())
        self.assertEqual(profile["source_plan"]["CLEANSYS_AIR"], {"start_year": 2015, "end_year": 2025})
        self.assertEqual(profile["source_plan"]["SOOSIRO_WATER"]["annual_years"], list(range(2017, 2026)))
        self.assertEqual(profile["source_plan"]["SOOSIRO_WATER"]["daily_years"], [2024, 2025])

    def test_input_is_not_mutated_and_no_weak_site_merge(self):
        data = discovery(); original = copy.deepcopy(data)
        profile, _ = compile_discovery(data)
        self.assertEqual(data, original)
        self.assertEqual(profile["site_address_anchors"], {})


if __name__ == "__main__":
    unittest.main()
