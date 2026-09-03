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
