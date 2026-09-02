import unittest

from bs4 import BeautifulSoup

from orchestrator.g0_live_adapters import (
    FLEX_ROAD_ADDRESS_RE,
    _candidate_view_links,
    _search_form_payload,
    discover_site_candidates,
)
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


if __name__ == "__main__":
    unittest.main()
