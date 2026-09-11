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

    def test_global_network_page_can_be_explicit_domestic_catalog(self):
        text = (
            "글로벌네트워크 생산공장 "
            "울산고무공장 울산광역시 남구 상개로 64 "
            "여수고무제1공장 전라남도 여수시 여수산단3로 118 "
            "예산건자재공장 충청남도 예산군 고덕면 예덕로 1033-9"
        )
        result = catalog.discover(
            "예시화학",
            [Page("https://official.example/company/global/network", text, "", 200)],
        )
        self.assertIsNotNone(result)
        sites, scope, unresolved = result
        self.assertEqual(len(sites), 3)
        self.assertEqual(scope["mode"], "SITE_SET")
        self.assertEqual(unresolved, [])
        self.assertEqual(
            {site["site_name_raw"] for site in sites},
            {"울산고무공장", "여수고무제1공장", "예산건자재공장"},
        )

    def test_flattened_global_network_pairs_short_metro_addresses_and_rejects_ui_centers(self):
        text = (
            "글로벌네트워크 대한민국 "
            "제보센터 서울특별시 마포구 마포대로 119 "
            "스판덱스 본사 서울시 마포구 마포대로 119 "
            "스판덱스 구미공장 경북 구미시 3공단2로 108 "
            "스판덱스 대구영업소 대구시 중구 국채보상로 488 "
            "스판덱스 효성기술원 경기도 안양시 동안구 시민대로 74 "
            "나이론폴리에스터 울산공장 울산시 남구 납도로 30 "
            "직물염색 대구 공장 대구시 달서구 성서공단로55길 45"
        )
        result = catalog.discover(
            "예시섬유",
            [Page("https://official.example/company/global-network/textile", text, "", 200)],
        )
        self.assertIsNotNone(result)
        sites, scope, unresolved = result
        by_address = {site["address_raw"]: site["site_name_raw"] for site in sites}
        self.assertEqual(by_address["경기도 안양시 동안구 시민대로 74"], "효성기술원")
        self.assertEqual(by_address["울산시 남구 납도로 30"], "울산공장")
        self.assertEqual(by_address["대구시 달서구 성서공단로55길 45"], "대구 공장")
        self.assertNotIn("제보센터", set(by_address.values()))
        self.assertIn("서울시 마포구 마포대로 119", by_address)
        self.assertEqual(scope["mode"], "SITE_SET")
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

    def test_region_abbreviation_is_same_site_key(self):
        self.assertEqual(
            catalog._compact("경상북도 포항시 남구 동해안로 6261"),
            catalog._compact("경북 포항시 남구 동해안로 6261"),
        )
        self.assertEqual(
            catalog._compact("울산광역시 남구 납도로 30"),
            catalog._compact("울산시 남구 납도로 30"),
        )
        self.assertNotEqual(
            catalog._compact("경상북도 포항시 남구 동해안로 6261"),
            catalog._compact("경상북도 포항시 남구 동해안로 6262"),
        )


    def test_semantic_location_headings_preserve_campus_names_and_full_beongil_addresses(self):
        html = '''<html><body>
          <h2>국내 사업장</h2>
          <section><h3>서울 본사</h3><p>주소 서울특별시 중구 중앙로 86</p></section>
          <section><h3>판교 R&amp;D 캠퍼스</h3><p>주소 경기도 성남시 분당구 혁신로 319번길 6</p></section>
          <section><h3>양주 CS센터</h3><p>주소 경기도 양주시 백석읍 꿈나무로 108</p></section>
          <section><h3>대전 R&amp;D 캠퍼스</h3><p>주소 대전광역시 유성구 연구대로 1366번길 10</p></section>
          <section><h3>대전 사업장</h3><p>주소 대전광역시 유성구 외삼로 8번길 99</p></section>
        </body></html>'''
        text = (
            '국내 사업장 서울 본사 주소 서울특별시 중구 중앙로 86 '
            '판교 R&D 캠퍼스 주소 경기도 성남시 분당구 혁신로 319번길 6 '
            '양주 CS센터 주소 경기도 양주시 백석읍 꿈나무로 108 '
            '대전 R&D 캠퍼스 주소 대전광역시 유성구 연구대로 1366번길 10 '
            '대전 사업장 주소 대전광역시 유성구 외삼로 8번길 99'
        )
        result = catalog.discover(
            '예시항공',
            [Page('https://official.example/company/domestic-sites', text, html, 200)],
        )
        self.assertIsNotNone(result)
        sites, scope, unresolved = result
        by_address = {site['address_raw']: site for site in sites}
        self.assertEqual(by_address['경기도 성남시 분당구 혁신로 319번길 6']['site_name_raw'], '판교 R&D 캠퍼스')
        self.assertEqual(by_address['대전광역시 유성구 연구대로 1366번길 10']['site_name_raw'], '대전 R&D 캠퍼스')
        self.assertEqual(by_address['대전광역시 유성구 외삼로 8번길 99']['site_name_raw'], '대전 사업장')
        self.assertEqual(by_address['경기도 양주시 백석읍 꿈나무로 108']['site_name_raw'], '양주 CS센터')
        self.assertTrue(all(site['discovery_evidence']['extraction_contract'] == 'SEMANTIC_HEADING_ADDRESS_PAIR' for site in sites))
        self.assertEqual(scope['mode'], 'SITE_SET')
        self.assertEqual(unresolved, [])

    def test_nested_beongil_address_is_not_truncated(self):
        self.assertEqual(
            catalog._validated_address('주소 경기도 성남시 분당구 혁신로 319번길 6 전화 000'),
            '경기도 성남시 분당구 혁신로 319번길 6',
        )


    def test_flattened_fallback_rejects_prose_and_table_fragments_before_real_catalog(self):
        noisy = Page(
            "https://official.example/esg/overview",
            (
                "국내사업장 당사는 여러 지역에 보유한 공장 서울특별시 서초구 산업로 10 "
                "단위: 백만원) 사업장 전북 익산시 산업로 20 "
                "백만원) 사업장 충청남도 서산시 대산읍 산업2로 30"
            ),
            "",
            200,
        )
        real = Page(
            "https://official.example/company/global-network",
            (
                "글로벌네트워크 생산공장 "
                "서울 본사 서울특별시 서초구 산업로 10 "
                "익산공장 전북 익산시 산업로 20 "
                "대산 제2공장 충청남도 서산시 대산읍 산업2로 30"
            ),
            "",
            200,
        )
        result = catalog.discover("예시소재", [noisy, real])
        self.assertIsNotNone(result)
        sites, scope, unresolved = result
        self.assertEqual(
            {site["site_name_raw"] for site in sites},
            {"서울 본사", "익산공장", "제2공장"},
        )
        self.assertTrue(all(site["source_locator"] == real.url for site in sites))
        self.assertTrue(all(
            site["discovery_evidence"]["extraction_contract"] == "FLATTENED_TEXT_FALLBACK"
            for site in sites
        ))
        self.assertEqual(scope["mode"], "SITE_SET")
        self.assertEqual(unresolved, [])

    def test_site_name_quality_guard_is_company_agnostic_and_preserves_real_labels(self):
        self.assertEqual(catalog._operational_name("보유한 공장", "예시회사"), "")
        self.assertEqual(catalog._operational_name("운영하는 사업장", "예시회사"), "")
        self.assertEqual(catalog._operational_name("백만원) 사업장", "예시회사"), "")
        self.assertEqual(catalog._operational_name("대구 공장", "예시회사"), "대구 공장")
        self.assertEqual(catalog._operational_name("대전 사업장", "예시회사"), "대전 사업장")
        self.assertEqual(catalog._operational_name("판교 R&D 캠퍼스", "예시회사"), "판교 R&D 캠퍼스")
        self.assertEqual(catalog._operational_name("대한 공장", "대한"), "대한 공장")


if __name__ == "__main__":
    unittest.main()
