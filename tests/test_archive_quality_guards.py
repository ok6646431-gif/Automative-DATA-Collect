import unittest

from collectors.corporate_docs_collect import repair_header_filename
from collectors.name_filter import matching_exclusion, normalize_entity_name
from orchestrator.request_builder import build


class ArchiveQualityGuardTests(unittest.TestCase):
    def test_verified_related_entity_variant_matches(self):
        exclusion="에스케이하이닉스 시스템아이씨"
        candidate="에스케이하이닉스 시스템아이씨 주식회사"
        self.assertEqual(matching_exclusion(candidate,[exclusion]),exclusion)
        self.assertEqual(normalize_entity_name("SK하이닉스㈜"),normalize_entity_name("SK하이닉스(주)"))

    def test_parent_name_is_not_excluded_by_longer_entity_name(self):
        self.assertEqual(matching_exclusion("에스케이하이닉스(주)",["에스케이하이닉스 시스템아이씨"]),"")

    def test_request_builder_propagates_verified_exclusions_to_all_sources(self):
        profile={
            "request_id":"REQ-1",
            "company_display_name":"테스트 주식회사",
            "profile_version":"2.0",
            "aliases":[{"term":"테스트","scope":"current","year_start":2020,"year_end":"auto","search_enabled":True}],
            "related_entity_exclusions":["테스트 시스템"],
            "site_address_anchors":{},
            "source_plan":{
                "ENVINFO":{"start_year":2020,"end_year":2024},
                "PRTR":{"start_year":2020,"end_year":2024},
                "CHEM_STATS":{"years":[2020,2022,2024]},
                "CLEANSYS_AIR":{"start_year":2020,"end_year":2025},
                "SOOSIRO_WATER":{"annual_years":[2020,2021,2022,2023,2024,2025],"daily_years":[2024]},
            },
        }
        request=build(profile)
        self.assertEqual(request["related_entity_exclusions"],["테스트 시스템"])
        for source in ("ENVINFO","PRTR","CHEM_STATS","CLEANSYS_AIR","SOOSIRO_WATER"):
            self.assertEqual(request["sources"][source]["exclude_terms"],["테스트 시스템"])

    def test_legacy_utf8_content_disposition_filename_is_repaired(self):
        correct="2025_SK하이닉스_지속가능경영보고서.pdf"
        mojibake=correct.encode("utf-8").decode("latin-1")
        self.assertEqual(repair_header_filename(mojibake),correct)

    def test_ascii_filename_remains_unchanged(self):
        name="2025_SK_hynix_report.pdf"
        self.assertEqual(repair_header_filename(name),name)


if __name__ == "__main__":
    unittest.main()
