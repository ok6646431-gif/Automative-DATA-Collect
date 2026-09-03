import unittest

from bs4 import BeautifulSoup

from orchestrator.g0_live_adapters import (
    FLEX_ROAD_ADDRESS_RE,
    _candidate_view_links,
    _search_form_payload,
    discover_site_candidates,
)
from orchestrator.g0_official_site_recovery import (
    _corporate_self_identifies,
    _origin_variants,
    _search_result_links,
)
from orchestrator.g0_report_catalog_policy import _catalog_supports_nonpublication
from orchestrator.zero_touch_discovery import Page


class TestG0LiveAdapters(unittest.TestCase):
    def test_dynamic_merged_region_road_address(self):
        text = "주소 : 우편번호 58462 전남광주통합특별시 영암군 삼호읍 대불로 93 전화번호"
        m = FLEX_ROAD_ADDRESS_RE.search(text)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "전남광주통합특별시 영암군 삼호읍 대불로 93")

    def test_legacy_abbreviated_region_road_address(self):
        text = "주소 : 전남 영암군 삼호읍 대불로 93"
        self.assertEqual(FLEX_ROAD_ADDRESS_RE.search(text).group(1), "전남 영암군 삼호읍 대불로 93")

    def test_company_profile_operational_site_is_confirmed(self):
        page = Page(
            "https://official.example/PageLink.do?link=about/status",
            "한눈에 보는 예시회사 예시회사는 조선기업입니다. 생산야드 산업단지 약 200만 제곱미터 "
            "예시회사 주소 : 우편번호 12345 미래통합특별시 바다군 조선읍 산업로 93 전화번호 000",
            "", 200,
        )
        sites, scope, unresolved = discover_site_candidates(
            "예시회사", [page], {"address": "", "source_url": "https://dart.example/company"}
        )
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["identity_status"], "CONFIRMED")
        self.assertEqual(sites[0]["address_raw"], "미래통합특별시 바다군 조선읍 산업로 93")
        self.assertEqual(scope["mode"], "SITE_SET")
        self.assertEqual(unresolved, [])

    def test_news_location_does_not_establish_primary_site(self):
        page = Page(
            "https://official.example/bbs/news/view.do?n=1",
            "예시회사 공장 준공식 장소 미래특별시 바다군 조선읍 산업로 93",
            "", 200,
        )
        sites, scope, unresolved = discover_site_candidates(
            "예시회사", [page], {"address": "", "source_url": "https://dart.example/company"}
        )
        self.assertEqual(sites, [])
        self.assertEqual(scope["mode"], "COMPANY")
        self.assertTrue(unresolved)

    def test_official_board_search_form_payload(self):
        soup = BeautifulSoup(
            '<form action="/bbs/news/list.do" method="get">'
            '<select name="seek"><option value="">전체</option></select>'
            '<input type="text" name="selKeyword" placeholder="검색어입력">'
            '<input type="hidden" name="pg" value="1">'
            '</form>',
            "html.parser",
        )
        payload = _search_form_payload(soup.form, "상호")
        self.assertEqual(payload["selKeyword"], "상호")
        self.assertEqual(payload["pg"], "1")

    def test_candidate_view_links_are_same_host_and_detail_only(self):
        html = (
            '<a href="/bbs/news/view.do?n=471">회사명 변경</a>'
            '<a href="/bbs/news/list.do?pg=2">다음</a>'
            '<a href="https://other.example/view.do?n=9">외부</a>'
        )
        links = _candidate_view_links("https://official.example/bbs/news/list.do", html)
        self.assertEqual(links, ["https://official.example/bbs/news/view.do?n=471"])

    def test_stale_dart_url_generates_transport_and_www_variants(self):
        variants = _origin_variants("https://www.old-company.example")
        self.assertIn("https://old-company.example/", variants)
        self.assertIn("http://www.old-company.example/", variants)
        self.assertIn("http://old-company.example/", variants)

    def test_stale_dart_deep_path_generates_same_host_ancestors_before_search(self):
        variants = _origin_variants("https://www.example.com/pub/main/index.do?lang=ko")
        self.assertIn("https://www.example.com/pub/main/index.do?lang=ko", variants)
        self.assertIn("https://www.example.com/pub/main/", variants)
        self.assertIn("https://www.example.com/pub/", variants)
        self.assertIn("https://www.example.com/", variants)
        self.assertNotIn("https://www.example.com/?lang=ko", variants)
        self.assertLess(
            variants.index("https://www.example.com/pub/main/"),
            variants.index("https://www.example.com/"),
        )

    def test_search_results_are_locator_only_and_public_platforms_are_filtered(self):
        html = (
            '<a href="/url?q=https%3A%2F%2Fofficial.example%2Fabout">공식</a>'
            '<a href="https://www.linkedin.com/company/example">링크드인</a>'
            '<a href="https://official.example/news">공식뉴스</a>'
        )
        links = _search_result_links("https://www.google.com/search?q=x", html)
        self.assertEqual(links, ["https://official.example/about", "https://official.example/news"])

    def test_search_results_recover_displayed_cite_and_data_urls(self):
        html = (
            '<a href="https://www.bing.com/ck/a?x=1">tracking</a>'
            '<div data-url="https://official.example/company/about">회사소개</div>'
            '<cite>www.official.example</cite>'
            '<script>{"destination":"https:\\/\\/official.example\\/sustainability"}</script>'
        )
        links = _search_result_links("https://www.bing.com/search?q=x", html)
        self.assertIn("https://official.example/company/about", links)
        self.assertIn("https://www.official.example", links)
        self.assertIn("https://official.example/sustainability", links)
        self.assertFalse(any("bing.com" in link for link in links))

    def test_search_results_recover_bare_www_text(self):
        links = _search_result_links(
            "https://www.google.com/search?q=x",
            "Official company website: www.official.example/about",
        )
        self.assertEqual(links, ["https://www.official.example/about"])

    def test_verified_report_catalog_interior_hole_is_nonpublication(self):
        years = [2020, 2022, 2023, 2024, 2025, 2026]
        self.assertTrue(_catalog_supports_nonpublication(2021, years))
        self.assertFalse(_catalog_supports_nonpublication(2019, years))
        self.assertFalse(_catalog_supports_nonpublication(2027, years))
        self.assertFalse(_catalog_supports_nonpublication(2022, years))

    def test_recovered_host_requires_self_identifying_corporate_structure(self):
        pages = [
            Page(
                "https://official.example/",
                "예시회사 회사소개 사업분야 지속가능경영 투자자정보 인재채용 "
                "copyright 예시회사 all rights reserved",
                "", 200,
            ),
            Page(
                "https://official.example/about",
                "예시회사 회사명 예시회사 대표이사 회사소개 business sustainability investor",
                "", 200,
            ),
        ]
        links = [
            ("https://official.example/", "회사소개", "https://official.example/about"),
            ("https://official.example/", "사업", "https://official.example/business"),
            ("https://official.example/", "지속가능", "https://official.example/sustainability"),
            ("https://official.example/", "IR", "https://official.example/ir"),
            ("https://official.example/", "채용", "https://official.example/career"),
        ]
        verified, evidence = _corporate_self_identifies("예시회사", pages, links)
        self.assertTrue(verified)
        self.assertGreaterEqual(evidence["company_pages"], 2)
        self.assertGreaterEqual(evidence["internal_link_count"], 5)

    def test_single_article_cannot_be_promoted_as_official_site(self):
        pages = [Page("https://news.example/article", "예시회사 관련 기사 회사소개", "", 200)]
        verified, _ = _corporate_self_identifies("예시회사", pages, [])
        self.assertFalse(verified)


if __name__ == "__main__":
    unittest.main()
