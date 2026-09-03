import unittest

from orchestrator.g0_domestic_site_catalog import discover
from orchestrator.zero_touch_discovery import Page


class DomesticSiteCatalogTests(unittest.TestCase):
    def test_explicit_domestic_catalog_preserves_all_operational_sites(self):
        text = (
            "국내사업장 금호타이어 중앙연구소 경기도 용인시 기흥구 사은로 215-21 "
            "금호타이어 광주공장 전남광주통합특별시 광산구 어등대로 658 "
            "금호타이어 평택공장 경기도 평택시 포승읍 평택항로156번길 87 "
            "금호타이어 곡성공장 전남광주통합특별시 곡성군 입면 금호길 85-63"
        )
        result = discover(
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
        result = discover(
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
        result = discover(
            "예시회사",
            [Page(
                "https://official.example/company/location",
                "국내사업장 예시회사 공장 경기도 평택시 포승읍 산업로 87",
                "", 200,
            )],
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
