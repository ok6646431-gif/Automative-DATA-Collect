import unittest

from orchestrator.g0_evidence_enrichment import (
    discover_site_candidates,
    enrich_discovery_from_audit,
    extract_rename_date_and_names,
)
from orchestrator.zero_touch_discovery import Page


class TestG0EvidenceEnrichment(unittest.TestCase):
    def test_operational_context_promotes_repeated_official_address(self):
        pages = [
            Page(
                "https://official.example/about/status",
                "생산야드 삼호산단 약 210만 제곱미터 HD현대삼호 주소 : 전남 영암군 삼호읍 대불로 93",
                "", 200,
            ),
            Page(
                "https://official.example/news/1",
                "HD현대삼호 주소 : 전남 영암군 삼호읍 대불로 93",
                "", 200,
            ),
        ]
        dart = {"address": "", "source_url": "https://dart.example/company"}
        sites, scope, unresolved = discover_site_candidates("HD현대삼호", pages, dart)
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["address_raw"], "전남 영암군 삼호읍 대불로 93")
        self.assertEqual(scope["mode"], "SITE_SET")
        self.assertEqual(unresolved, [])

    def test_repeated_footer_address_without_operational_context_is_not_plant(self):
        pages = [
            Page("https://official.example/a", "회사 주소 서울 강남구 테헤란로 100", "", 200),
            Page("https://official.example/b", "회사 주소 서울 강남구 테헤란로 100", "", 200),
        ]
        dart = {"address": "", "source_url": "https://dart.example/company"}
        sites, scope, unresolved = discover_site_candidates("예시회사", pages, dart)
        self.assertEqual(sites, [])
        self.assertEqual(scope["mode"], "COMPANY")
        self.assertEqual(unresolved[0]["code"], "SITE_SCOPE_NOT_UNIQUELY_RESOLVED")

    def test_two_similar_strength_operational_sites_remain_ambiguous(self):
        pages = [
            Page("https://official.example/plant-a", "A공장 사업장 주소 경남 창원시 산업로 10", "", 200),
            Page("https://official.example/plant-a2", "A공장 위치 경남 창원시 산업로 10", "", 200),
            Page("https://official.example/plant-b", "B공장 사업장 주소 울산 남구 산업로 20", "", 200),
            Page("https://official.example/plant-b2", "B공장 위치 울산 남구 산업로 20", "", 200),
        ]
        dart = {"address": "", "source_url": "https://dart.example/company"}
        sites, scope, unresolved = discover_site_candidates("예시회사", pages, dart)
        self.assertEqual(sites, [])
        self.assertEqual(scope["mode"], "COMPANY")
        self.assertTrue(unresolved)

    def test_explicit_official_rename_works_without_dart_history(self):
        pages = [Page(
            "https://official.example/news/rename",
            "작성일 2024-03-25 상호를 ‘현대삼호중공업(Hyundai Samho Heavy Industries CO., LTD)’에서 ‘HD현대삼호 (HD Hyundai Samho CO., LTD)로 변경하는 안건을 의결했다.",
            "", 200,
        )]
        result = extract_rename_date_and_names(pages, "에이치디현대삼호 주식회사", [])
        self.assertIsNotNone(result)
        self.assertEqual(result["date"], "2024-03-25")
        self.assertEqual(result["predecessor"], "현대삼호중공업")
        self.assertEqual(result["evidence_type"], "EXPLICIT_OFFICIAL_RENAME_STATEMENT")

    def test_enrichment_adds_bounded_historical_alias_and_rename(self):
        discovery = {
            "requested_company_name": "HD현대삼호",
            "current_legal_name": "에이치디현대삼호 주식회사",
            "current_legal_name_active_period": {"start_year": 1998},
            "company_aliases": [
                {"name": "HD현대삼호", "alias_type": "requested_name"},
                {"name": "HD HYUNDAI SAMHO CO., LTD.", "alias_type": "english_legal_name"},
            ],
            "historical_legal_names": [],
            "corporate_restructuring_evidence": [],
            "unresolved_items": [],
            "collection_policy": {"requested_history_window": {"start_year": 2020, "end_year": 2026}},
        }
        audit = {
            "gate_status": "PASS",
            "stages": {"name_history": {"bounded_rename": {
                "date": "2024-03-25", "predecessor": "현대삼호중공업",
                "source_locator": "https://official.example/news/rename",
            }}},
        }
        enriched, _, audit = enrich_discovery_from_audit(discovery, {}, audit)
        self.assertEqual(enriched["current_legal_name_active_period"], {"start_year": 2024})
        self.assertEqual(enriched["historical_legal_names"][0]["active_period"], {"start_year": 2020, "end_year": 2024})
        self.assertEqual(enriched["corporate_restructuring_evidence"][0]["event_type"], "rename")
        requested = next(x for x in enriched["company_aliases"] if x["name"] == "HD현대삼호")
        self.assertEqual(requested["active_period"], {"start_year": 2024})
        self.assertEqual(audit["gate_status"], "PASS")


if __name__ == "__main__":
    unittest.main()
