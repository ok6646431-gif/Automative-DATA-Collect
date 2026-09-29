import unittest
from unittest.mock import Mock, patch

from orchestrator.company_profile_builder import compile_discovery
from orchestrator.zero_touch_discovery import (
    Page,
    _extract_rename_date_and_names,
    _search_engine_official_dart,
    _search_engine_dart_filing_entity_keys,
    _english_dart_dynamic_entity_keys,
    _extract_select_keys,
    discover_site_candidates,
    legal_match_score,
    normalize_name,
    parse_dart_company,
    resolve_legal_identity,
)


class TestZeroTouchDiscovery(unittest.TestCase):
    def test_name_normalization_handles_korean_initial_brand_spelling(self):
        self.assertEqual(normalize_name("HD현대삼호"), normalize_name("에이치디현대삼호 주식회사"))
        self.assertEqual(normalize_name("LG화학"), normalize_name("엘지화학(주)"))

    def test_dart_select_key_parser_accepts_popup_and_assignment(self):
        html = """
        <a href='/dsbc001/selectPopup.ax?selectKey=00332468'>x</a>
        <script>var selectKey='00126380';</script>
        """
        self.assertEqual(_extract_select_keys(html), ["00332468", "00126380"])

    def test_parse_dart_company_popup(self):
        html = """
        <table>
          <tr><th>Company Name (Korean)</th><td>에이치디현대삼호 주식회사</td></tr>
          <tr><th>Company Name (English)</th><td>HD HYUNDAI SAMHO CO., LTD.</td></tr>
          <tr><th>Website</th><td>www.hshi.co.kr</td></tr>
          <tr><th>Establishment Date</th><td>1998-11-04</td></tr>
          <tr><th>Taxpayer Identification Number</th><td>411-81-19799</td></tr>
        </table>
        """
        parsed = parse_dart_company(html, "00332468", "https://englishdart.example/popup")
        self.assertEqual(parsed["korean_name"], "에이치디현대삼호 주식회사")
        self.assertEqual(parsed["website"], "www.hshi.co.kr")
        self.assertEqual(parsed["establishment_date"], "1998-11-04")
        self.assertGreaterEqual(legal_match_score("HD현대삼호", parsed), 88)

    def test_ambiguous_or_weak_name_score_is_not_verification(self):
        candidate = {"korean_name": "HD현대중공업 주식회사", "english_name": "HD HYUNDAI HEAVY INDUSTRIES"}
        self.assertLess(legal_match_score("HD현대삼호", candidate), 88)

    def test_short_parent_brand_substring_never_verifies_operating_company(self):
        parent = {"korean_name": "(주)LS", "english_name": "LS Corp."}
        operating = {"korean_name": "엘에스일렉트릭 주식회사", "english_name": "LS ELECTRIC CO., LTD"}
        self.assertLess(legal_match_score("LS ELECTRIC", parent), 88)
        self.assertGreaterEqual(legal_match_score("LS ELECTRIC", operating), 88)

    def test_first_party_english_dart_filing_row_recovers_entity_key(self):
        base_html = """
        <html><body>
          <table><tr><td>LS ELECTRIC</td>
          <td><a href='/dsbh001/main.do?rcpNo=20260318001243'>Annual Report</a></td></tr></table>
        </body></html>
        """
        report_html = """
        <html><body>
          <input type='hidden' name='textCrpCik' value='00105855'>
          LS ELECTRIC Annual Report
        </body></html>
        """
        base = Mock(status_code=200, text=base_html, url="https://englishdart.fss.or.kr/dsbb001/main.do")
        report = Mock(status_code=200, text=report_html, url="https://englishdart.fss.or.kr/dsbh001/main.do?rcpNo=20260318001243")

        def fake_get(url, **kwargs):
            if "/dsbh001/main.do" in url:
                return report
            return base

        http = Mock()
        http.get.side_effect = fake_get
        self.assertEqual(_english_dart_dynamic_entity_keys(http, "LS ELECTRIC"), ["00105855"])

    def test_filing_fallback_extracts_entity_cik_from_official_viewer(self):
        search_html = """
        <html><body>
          <cite>https://englishdart.fss.or.kr/dsbh002/viewer.do?rcpNo=20230320000799</cite>
        </body></html>
        """
        viewer_html = """
        <html><body>Entity Central IndexKey : 00105855 Entity Registrant Name : LS ELECTRIC Co.,Ltd.</body></html>
        """
        search_response = Mock(status_code=200, text=search_html)
        viewer_response = Mock(status_code=200, text=viewer_html)

        def fake_get(url, **kwargs):
            if "viewer.do" in url:
                return viewer_response
            return search_response

        http = Mock()
        http.get.side_effect = fake_get
        self.assertEqual(
            _search_engine_dart_filing_entity_keys(http, "LS ELECTRIC"),
            ["00105855"],
        )

    def test_search_fallback_extracts_official_dart_key_from_cite_text(self):
        html = """
        <html><body>
          <cite>https://englishdart.fss.or.kr/dsbc001/selectPopup.ax?selectKey=00105855</cite>
        </body></html>
        """
        response = Mock(status_code=200, text=html)
        http = Mock()
        http.get.return_value = response
        self.assertEqual(_search_engine_official_dart(http, "LS ELECTRIC"), ["00105855"])

    def test_weak_direct_dart_result_recovers_exact_search_candidate(self):
        parent = {
            "select_key": "00105952", "korean_name": "(주)LS", "english_name": "LS Corp.",
            "website": "www.lsholdings.co.kr",
        }
        operating = {
            "select_key": "00105855", "korean_name": "엘에스일렉트릭 주식회사",
            "english_name": "LS ELECTRIC CO., LTD", "website": "www.ls-electric.com",
        }
        def fake_fetch(_http, key):
            return {"00105952": parent, "00105855": operating}.get(key)

        with patch("orchestrator.zero_touch_discovery.discover_dart_keys", return_value=["00105952"]), \
             patch("orchestrator.zero_touch_discovery.fetch_dart_company", side_effect=fake_fetch), \
             patch("orchestrator.zero_touch_discovery._english_dart_dynamic_entity_keys", return_value=[]), \
             patch("orchestrator.zero_touch_discovery._search_engine_official_dart", return_value=["00105855"]):
            resolved, candidates = resolve_legal_identity(Mock(), "LS ELECTRIC")

        self.assertEqual(resolved["select_key"], "00105855")
        scores = {row["select_key"]: row["match_score"] for row in candidates}
        self.assertLess(scores["00105952"], 88)
        self.assertGreaterEqual(scores["00105855"], 88)

    def test_official_rename_text_bounds_history(self):
        pages = [Page(
            "https://official.example/news/471",
            "현대삼호중공업은 2024년 3월 25일 HD현대삼호로 상호 변경했습니다.",
            "<html></html>", 200,
        )]
        result = _extract_rename_date_and_names(
            pages, "에이치디현대삼호 주식회사", ["현대삼호중공업", "에이치디현대삼호 주식회사"]
        )
        # The official text may use the brand spelling rather than the full legal spelling;
        # normalization makes HD/에이치디 equivalent.
        self.assertIsNotNone(result)
        self.assertEqual(result["date"], "2024-03-25")
        self.assertEqual(result["predecessor"], "현대삼호중공업")

    def test_site_is_verified_only_with_repeated_or_dart_anchor(self):
        pages = [
            Page("https://official.example/company/location", "사업장 위치 전남 영암군 삼호읍 대불로 93", "", 200),
            Page("https://official.example/recruit/location", "조선소 주소 전남 영암군 삼호읍 대불로 93", "", 200),
        ]
        dart = {"address": "", "source_url": "https://dart.example/company"}
        sites, scope, unresolved = discover_site_candidates("HD현대삼호", pages, dart)
        self.assertEqual(len(sites), 1)
        self.assertEqual(scope["mode"], "SITE_SET")
        self.assertEqual(unresolved, [])

    def test_single_unanchored_address_does_not_become_site(self):
        pages = [Page("https://official.example/contact", "주소 전남 영암군 삼호읍 대불로 93", "", 200)]
        dart = {"address": "", "source_url": "https://dart.example/company"}
        sites, scope, unresolved = discover_site_candidates("HD현대삼호", pages, dart)
        self.assertEqual(sites, [])
        self.assertEqual(scope["mode"], "COMPANY")
        self.assertEqual(unresolved[0]["code"], "SITE_SCOPE_NOT_UNIQUELY_RESOLVED")

    def test_generated_style_discovery_compiles_through_existing_contract(self):
        discovery = {
            "schema_version": "1.0",
            "request_id": "g0-regression",
            "requested_company_name": "HD현대삼호",
            "current_legal_name": "에이치디현대삼호 주식회사",
            "current_legal_name_active_period": {"start_year": 2024},
            "company_verification_state": "VERIFIED",
            "confidence": "HIGH",
            "requested_scope": {"mode": "SITE_SET", "label": "HD현대삼호 주요 사업장", "candidate_ids": ["site-a"]},
            "company_aliases": [{"name": "HD현대삼호", "alias_type": "requested_name", "verification_state": "VERIFIED"}],
            "historical_legal_names": [{
                "name": "현대삼호중공업", "alias_type": "former_legal_name",
                "active_period": {"start_year": 2020, "end_year": 2024},
                "verification_state": "VERIFIED",
            }],
            "corporate_restructuring_evidence": [{"event_type": "rename", "effective_period": {"start_year": 2024, "end_year": 2024}}],
            "domestic_site_candidates": [{
                "candidate_id": "site-a", "site_name_raw": "HD현대삼호 주요 사업장",
                "address_raw": "전남 영암군 삼호읍 대불로 93", "identity_status": "VERIFIED", "verification_state": "VERIFIED",
            }],
            "identity_evidence": [], "related_entity_exclusions": [], "unresolved_items": [], "event_evidence_references": [],
            "collection_policy": {"minimum_history_years": 5, "sources": {
                "ENVINFO": {"requested_window": {"start_year": 2020, "end_year": 2024}, "prefer_full_history": False},
                "PRTR": {"requested_window": {"start_year": 2020, "end_year": 2024}, "prefer_full_history": False},
                "CHEM_STATS": {"available_survey_rounds": [2020, 2022, 2024], "requested_survey_rounds": [2020, 2022, 2024], "prefer_full_history": True},
                "CLEANSYS_AIR": {"requested_window": {"start_year": 2020, "end_year": 2025}, "prefer_full_history": False},
                "SOOSIRO_WATER": {"requested_window": {"start_year": 2020, "end_year": 2025}, "daily_available_years": [2024], "prefer_full_history": False},
            }},
        }
        profile, summary = compile_discovery(discovery)
        self.assertEqual(summary["review_required_count"], 0)
        old = next(x for x in profile["aliases"] if x["term"] == "현대삼호중공업")
        self.assertEqual((old["year_start"], old["year_end"]), (2020, 2024))


if __name__ == "__main__":
    unittest.main()
