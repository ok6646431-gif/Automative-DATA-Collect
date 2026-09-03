import unittest
from types import SimpleNamespace

from orchestrator import g0_kind_disclosure_recovery as kind


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


if __name__ == "__main__":
    unittest.main()
