import unittest

from orchestrator import g0_domestic_site_catalog as catalog
from orchestrator import g0_domestic_site_catalog_enrichment as enrichment
from orchestrator.zero_touch_discovery import Page


class DomesticSiteCatalogTests(unittest.TestCase):
    def test_explicit_domestic_catalog_preserves_all_operational_sites(self):
        text = (
            "국내사업장 금호타이어 중앙연구소 경기도 용인시 기흥구 사은로 215-21 "
            "금호타이어 광주공장 전남광주통합특별시 광산구 어등대로 658 "
            "금호타이어 평택공장 경기도 평택시 포승읍 평택항로156번길 87 "
            "금호타이어 곡성공장 전남광주통합특별시 곡성군 입면 금호길 85-63"
        )
        result = catalog.discover(
            "금호타이어",
            [Page("https://official.example/company/domestic-sites", text, "", 200)],
        )
        self.assertIsNotNone(result)
        sites, scope, unresolved = result
        self.assertEqual(len(sites), 4)
        self.assertEqual(scope["mode"], "SITE_SET")
        self.assertEqual(len(scope["candidate_ids"]), 4)
        self.assertEqual(unresolved, [])
        addresses = {site["address_raw"] for site in sites}
        self.assertIn("경기도 용인시 기흥구 사은로 215-21", addresses)
        self.assertIn("전남광주통합특별시 광산구 어등대로 658", addresses)
        self.assertIn("경기도 평택시 포승읍 평택항로156번길 87", addresses)
        self.assertIn("전남광주통합특별시 곡성군 입면 금호길 85-63", addresses)

    def test_structured_dom_pairs_preserve_clean_site_names(self):
        html = '''
        <html><body>
          <h3>금호타이어 국내사업장</h3>
          <ul class="js-accordion_menu">
            <li><div class="box-head-toggle">
              <span class="name">금호타이어 중앙연구소</span>
              <span class="addr">경기도 용인시 기흥구 사은로 215-21 (지곡동, 금호타이어연구소)</span>
              <span class="contact">TEL : 031-8033-5114 FAX : 031-8033-5115</span>
            </div></li>
            <li><div class="box-head-toggle">
              <span class="name">금호타이어 광주공장</span>
              <span class="addr">전남광주통합특별시 광산구 어등대로 658</span>
              <span class="contact">TEL : 062-940-2114 FAX : 062-941-3161</span>
            </div></li>
            <li><div class="box-head-toggle">
              <span class="name">금호타이어 평택공장</span>
              <span class="addr">경기도 평택시 포승읍 평택항로156번길 87 (내기리, 금호타이어평택공장)</span>
              <span class="contact">TEL : 031-680-5700 FAX : 031-680-5789</span>
            </div></li>
            <li><div class="box-head-toggle">
              <span class="name">금호타이어 곡성공장</span>
              <span class="addr">전남광주통합특별시 곡성군 입면 금호길 85-63</span>
              <span class="contact">TEL : 061-360-3114 FAX : 061-362-8000</span>
            </div></li>
          </ul>
        </body></html>
        '''
        text = (
            "금호타이어 국내사업장 금호타이어 중앙연구소 경기도 용인시 기흥구 사은로 215-21 "
            "금호타이어 광주공장 전남광주통합특별시 광산구 어등대로 658 "
            "금호타이어 평택공장 경기도 평택시 포승읍 평택항로156번길 87 "
            "금호타이어 곡성공장 전남광주통합특별시 곡성군 입면 금호길 85-63"
        )
        result = catalog.discover(
            "금호타이어",
            [Page("https://official.example/ko/company/domeList.do", text, html, 200)],
        )
        self.assertIsNotNone(result)
        sites, scope, unresolved = result
        self.assertEqual(
            [site["site_name_raw"] for site in sites],
            ["금호타이어 중앙연구소", "금호타이어 광주공장", "금호타이어 평택공장", "금호타이어 곡성공장"],
        )
        self.assertTrue(all(
            site["discovery_evidence"]["extraction_contract"] == "STRUCTURED_DOM_NAME_ADDRESS_PAIR"
            for site in sites
        ))
        self.assertEqual(len(scope["candidate_ids"]), 4)
        self.assertEqual(unresolved, [])

    def test_single_address_page_does_not_claim_complete_catalog(self):
        result = catalog.discover(
            "예시회사",
            [Page(
                "https://official.example/company/location",
                "국내사업장 예시회사 공장 경기도 평택시 포승읍 산업로 87",
                "", 200,
            )],
        )
        self.assertIsNone(result)

    def test_steelworks_is_a_generic_operational_facility_suffix(self):
        page = Page(
            "https://official.example/support/location-a",
            "찾아오시는 길 포항제철소 지도보기 경상북도 포항시 남구 동해안로 6262",
            "",
            200,
        )
        found = enrichment._location_page_sites("주식회사 포스코", page)
        item = next(x for x in found.values() if x["address"] == "경상북도 포항시 남구 동해안로 6262")
        self.assertEqual(item["name"], "포항제철소")

    def test_multi_page_official_location_navigation_forms_one_site_set(self):
        pages = [
            Page(
                "https://official.example/support/location-a",
                "찾아오시는 길 포항제철소 지도보기 경상북도 포항시 남구 동해안로 6262",
                "",
                200,
            ),
            Page(
                "https://official.example/support/location-b",
                "찾아오시는 길 광양제철소 지도보기 전라남도 광양시 폭포사랑길 20-26",
                "",
                200,
            ),
        ]
        found = enrichment._aggregate_multi_page_sites("주식회사 포스코", pages)
        self.assertEqual(len(found), 2)
        self.assertEqual(len({x["source_locator"] for x in found.values()}), 2)
        sites, scope, unresolved = enrichment._materialize_site_set(
            "주식회사 포스코", found, "MULTI_PAGE_OFFICIAL_LOCATION_NAVIGATION"
        )
        self.assertEqual({x["site_name_raw"] for x in sites}, {"포항제철소", "광양제철소"})
        self.assertEqual(scope["mode"], "SITE_SET")
        self.assertEqual(len(scope["candidate_ids"]), 2)
        self.assertEqual(unresolved, [])

    def test_repeated_single_footer_address_does_not_become_multi_site(self):
        pages = [
            Page(
                "https://official.example/support/location-a",
                "찾아오시는 길 예시회사 본사 경기도 평택시 포승읍 산업로 87",
                "", 200,
            ),
            Page(
                "https://official.example/support/location-b",
                "찾아오시는 길 예시회사 본사 경기도 평택시 포승읍 산업로 87",
                "", 200,
            ),
        ]
        found = enrichment._aggregate_multi_page_sites("예시회사", pages)
        self.assertEqual(len(found), 1)

    def test_location_seed_policy_excludes_generic_company_history_pages(self):
        root = "https://official.example/home"
        seeds = enrichment._location_seed_urls(
            root,
            [
                "https://official.example/company/history",
                "https://official.example/company/about",
                "https://official.example/support/location-a",
                "https://official.example/company/domestic-sites",
            ],
            ["https://official.example/sustainability/report-index"],
        )
        self.assertEqual(
            seeds,
            [
                root,
                "https://official.example/support/location-a",
                "https://official.example/company/domestic-sites",
            ],
        )
        self.assertNotIn("https://official.example/company/history", seeds)
        self.assertNotIn("https://official.example/company/about", seeds)


if __name__ == "__main__":
    unittest.main()
