import unittest
from types import SimpleNamespace

from orchestrator import g0_kind_disclosure_recovery as kind
from orchestrator.company_profile_builder import compile_discovery
from orchestrator.request_builder import build


class FakeHttp:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []
        self.audit = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0) if self.responses else None

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0) if self.responses else None


def response(text, url="https://kind.krx.co.kr/example", status=200):
    return SimpleNamespace(text=text, content=text.encode("utf-8"), url=url, status_code=status, headers={"content-type": "text/html; charset=UTF-8"}, encoding="utf-8", apparent_encoding="utf-8")


class TestKindDisclosureRecovery(unittest.TestCase):
    def test_extract_company_code_does_not_confuse_dart_key(self):
        legal = {
            "select_key": "00111704",
            "raw_text": "Company Code 042660 Corporation Registration Number 110111-2095837",
        }
        self.assertEqual(kind.extract_company_code(legal), "042660")

    def test_parse_search_rows_extracts_acceptance_and_title(self):
        html = """
        <div>전체 137 건 : 1 /2</div>
        <table><tr>
          <td>91</td><td>2023-06-08 16:50</td>
          <td><a id='companysum' title='한화오션'>한화오션</a></td>
          <td><a href='#viewer' title='변경상장(상호변경)' onclick="openDisclsViewer('20230608000085','')">변경상장(상호변경)</a></td>
        </tr></table>
        """
        rows, total = kind.parse_search_rows(html)
        self.assertEqual(total, 137)
        self.assertEqual(rows[0]["acceptance_no"], "20230608000085")
        self.assertEqual(rows[0]["date"], "2023-06-08")
        self.assertTrue(kind._is_rename_title(rows[0]["title"]))

    def test_fetch_disclosure_body_follows_docpath_contract(self):
        wrapper = """
        <select id='mainDoc'><option value='20230814003763|Y' selected>반기보고서</option></select>
        <form name='docpathfrm' id='docpathfrm' target='docpathframe' action='/common/disclsviewer.do'>
          <input name='method' value='searchContents'><input name='docNo' value=''><input name='goAction2' value=''>
        </form>
        """
        path = """<script>parent.setPath('','https://kind.krx.co.kr/external/a/report.htm','/external/a/report','05','20');</script>"""
        body = """
        <html><body>
        2002.03.16 : 대우조선해양(주)으로 상호 변경
        2023.05.23 : 한화오션(주)로 상호 변경
        </body></html>
        """
        http = FakeHttp([
            response(wrapper, "https://kind.krx.co.kr/common/disclsviewer.do?method=search&acptno=20230814001207"),
            response(path, "https://kind.krx.co.kr/common/disclsviewer.do?method=searchContents&docNo=20230814003763"),
            response(body, "https://kind.krx.co.kr/external/a/report.htm"),
        ])
        resolved = kind.fetch_disclosure_body(http, "20230814001207", "한화오션(주)")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["doc_no"], "20230814003763")
        self.assertIn("대우조선해양", resolved["text"])
        method, _, kwargs = http.calls[1]
        self.assertEqual(method, "GET")
        self.assertEqual(kwargs["params"]["method"], "searchContents")
        self.assertEqual(kwargs["params"]["docNo"], "20230814003763")

    def test_unresolved_rename_signal_blocks_promotion(self):
        discovery = {
            "current_legal_name": "한화오션(주)",
            "corporate_restructuring_evidence": [],
            "unresolved_items": [],
        }
        audit = {"stages": {"official_site": {"recovery": {"rename_signals": [
            {"year": 2023, "url": "https://official.example/history", "context": "2023 한화오션으로 사명 변경"}
        ]}}}}
        kind.enforce_historical_continuity_gate(discovery, audit)
        self.assertEqual(discovery["unresolved_items"][0]["code"], "HISTORICAL_LEGAL_NAME_PREDECESSOR_UNRESOLVED")

    def test_verified_rename_clears_continuity_blocker(self):
        discovery = {
            "current_legal_name": "한화오션(주)",
            "corporate_restructuring_evidence": [{"event_type": "rename", "effective_date": "2023-05-23"}],
            "unresolved_items": [{"code": "HISTORICAL_LEGAL_NAME_PREDECESSOR_UNRESOLVED"}],
        }
        kind.enforce_historical_continuity_gate(discovery, {"stages": {}})
        self.assertEqual(discovery["unresolved_items"], [])

    def test_resolved_case_bounds_old_and_current_names(self):
        from orchestrator.g0_public_disclosure_enrichment import apply_rename

        discovery = {
            "current_legal_name": "한화오션(주)",
            "company_aliases": [{"name": "한화오션", "alias_type": "requested_name"}],
            "historical_legal_names": [],
            "corporate_restructuring_evidence": [],
            "collection_policy": {"requested_history_window": {"start_year": 2020, "end_year": 2026}},
        }
        audit = {"stages": {}}
        apply_rename(discovery, audit, {
            "date": "2023-05-23",
            "predecessor": "대우조선해양(주)",
            "successor": "한화오션(주)",
            "source_locator": "https://kind.krx.co.kr/external/report.htm",
        })
        self.assertEqual(discovery["current_legal_name_active_period"], {"start_year": 2023})
        self.assertEqual(discovery["historical_legal_names"][0]["name"], "대우조선해양(주)")
        self.assertEqual(discovery["historical_legal_names"][0]["active_period"], {"start_year": 2020, "end_year": 2023})
        self.assertEqual(discovery["company_aliases"][0]["active_period"], {"start_year": 2023})

    def test_compiled_collection_terms_respect_rename_boundary(self):
        from orchestrator.g0_public_disclosure_enrichment import apply_rename

        discovery = {
            "schema_version": "1.0",
            "request_id": "rename-boundary-regression",
            "requested_company_name": "한화오션",
            "current_legal_name": "한화오션(주)",
            "current_legal_name_active_period": {"start_year": 2000},
            "company_verification_state": "VERIFIED",
            "confidence": "HIGH",
            "requested_scope": {"mode": "SITE_SET", "label": "한화오션 주요 사업장", "candidate_ids": ["site-a"]},
            "company_aliases": [
                {"name": "한화오션", "alias_type": "requested_name", "verification_state": "VERIFIED"},
                {"name": "Hanwha Ocean Co., Ltd.", "alias_type": "english_legal_name", "verification_state": "VERIFIED"},
            ],
            "historical_legal_names": [],
            "corporate_restructuring_evidence": [],
            "domestic_site_candidates": [{
                "candidate_id": "site-a", "site_name_raw": "한화오션 거제사업장",
                "address_raw": "경상남도 거제시 거제대로 3370",
                "identity_status": "CONFIRMED", "verification_state": "VERIFIED",
            }],
            "identity_evidence": [], "related_entity_exclusions": [], "unresolved_items": [], "event_evidence_references": [],
            "collection_policy": {
                "minimum_history_years": 5,
                "requested_history_window": {"start_year": 2020, "end_year": 2026},
                "sources": {
                    "ENVINFO": {"requested_window": {"start_year": 2020, "end_year": 2024}, "prefer_full_history": False},
                    "PRTR": {"requested_window": {"start_year": 2020, "end_year": 2024}, "prefer_full_history": False},
                    "CHEM_STATS": {"available_survey_rounds": [2020, 2022, 2024], "requested_survey_rounds": [2020, 2022, 2024], "prefer_full_history": True},
                    "CLEANSYS_AIR": {"requested_window": {"start_year": 2020, "end_year": 2025}, "prefer_full_history": False},
                    "SOOSIRO_WATER": {"requested_window": {"start_year": 2020, "end_year": 2025}, "daily_available_years": [2024], "prefer_full_history": False},
                },
            },
        }
        apply_rename(discovery, {"stages": {}}, {
            "date": "2023-05-23", "predecessor": "대우조선해양(주)", "successor": "한화오션(주)",
            "source_locator": "https://kind.krx.co.kr/external/2023/08/14/report.htm",
        })
        profile, summary = compile_discovery(discovery)
        self.assertEqual(summary["review_required_count"], 0)
        request = build(profile)
        terms = request["sources"]["ENVINFO"]["search_terms_by_year"]
        for year in (2020, 2021, 2022):
            values = terms[str(year)] if str(year) in terms else terms[year]
            self.assertTrue(any("대우조선해양" in value for value in values))
            self.assertFalse(any("한화오션" in value for value in values))
        transition = terms["2023"] if "2023" in terms else terms[2023]
        self.assertTrue(any("대우조선해양" in value for value in transition))
        self.assertTrue(any("한화오션" in value for value in transition))
        current = terms["2024"] if "2024" in terms else terms[2024]
        self.assertTrue(any("한화오션" in value for value in current))
        self.assertFalse(any("대우조선해양" in value for value in current))


if __name__ == "__main__":
    unittest.main()
