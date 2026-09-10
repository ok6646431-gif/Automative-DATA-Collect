import unittest

from orchestrator import g0_first_publication_recovery as recovery


class FirstPublicationRecoveryTests(unittest.TestCase):
    def _documents(self):
        return {
            "discovery_status": "PARTIAL",
            "documents": [
                {
                    "document_type": "SUSTAINABILITY_REPORT",
                    "report_year": 2021,
                    "verification_status": "SOURCE_VERIFIED",
                },
                {
                    "document_type": "SUSTAINABILITY_REPORT",
                    "report_year": 2022,
                    "verification_status": "SOURCE_VERIFIED",
                },
            ],
            "gaps": [
                {
                    "gap_id": "AUTO_SUSTAINABILITY_2020_UNRESOLVED",
                    "document_type": "SUSTAINABILITY_REPORT",
                    "year": 2020,
                    "status": "DISCOVERY_GAP",
                    "verification_status": "UNVERIFIED",
                    "blocking": True,
                }
            ],
        }

    def test_verified_first_year_resolves_only_prepublication_prefix(self):
        docs = self._documents()
        resolved = recovery.apply_verified_claim({}, docs, {
            "first_report_year": 2021,
            "source_url": "https://official.example/news/first-report",
        })
        self.assertEqual(resolved, [2020])
        gap = docs["gaps"][0]
        self.assertEqual(gap["status"], "NOT_PUBLISHED")
        self.assertEqual(gap["verification_status"], "SOURCE_VERIFIED")
        self.assertFalse(gap["blocking"])
        self.assertEqual(docs["discovery_status"], "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE")

    def test_claim_year_must_match_earliest_verified_report_file(self):
        docs = self._documents()
        resolved = recovery.apply_verified_claim({}, docs, {
            "first_report_year": 2022,
            "source_url": "https://official.example/news/claim",
        })
        self.assertEqual(resolved, [])
        self.assertTrue(docs["gaps"][0]["blocking"])

    def test_later_gap_is_never_erased_by_first_publication_claim(self):
        docs = self._documents()
        docs["gaps"].append({
            "gap_id": "AUTO_SUSTAINABILITY_2023_UNRESOLVED",
            "document_type": "SUSTAINABILITY_REPORT",
            "year": 2023,
            "status": "DISCOVERY_GAP",
            "verification_status": "UNVERIFIED",
            "blocking": True,
        })
        resolved = recovery.apply_verified_claim({}, docs, {
            "first_report_year": 2021,
            "source_url": "https://official.example/news/first-report",
        })
        self.assertEqual(resolved, [2020])
        self.assertTrue(docs["gaps"][1]["blocking"])
        self.assertEqual(docs["discovery_status"], "PARTIAL")

    def test_first_party_newsroom_search_form_is_detected(self):
        html = """
        <html><body>
          <form action="/kor/media/newsroom/list.do" method="get">
            <input type="hidden" name="page" value="1">
            <input type="search" name="searchText">
          </form>
        </body></html>
        """
        forms = recovery._search_forms(
            "https://official.example/",
            "https://official.example/kor/media/newsroom/list.do",
            html,
        )
        self.assertEqual(len(forms), 1)
        _, field, action, method = forms[0]
        self.assertEqual(field, "searchText")
        self.assertEqual(action, "https://official.example/kor/media/newsroom/list.do")
        self.assertEqual(method, "get")

    def test_cross_host_search_form_is_rejected(self):
        html = """
        <form action="https://search.example.net/find" method="get">
          <input type="search" name="q">
        </form>
        """
        forms = recovery._search_forms(
            "https://official.example/",
            "https://official.example/kor/media/newsroom/list.do",
            html,
        )
        self.assertEqual(forms, [])

    def test_matching_result_links_stay_first_party_and_report_specific(self):
        html = """
        <a href="/kor/media/newsroom/view.do?seq=1">지속가능경영보고서 첫 발간</a>
        <a href="/kor/media/newsroom/view.do?seq=2">일반 회사 뉴스</a>
        <a href="https://other.example/report">sustainability report</a>
        """
        links = recovery._matching_result_links(
            "https://official.example/",
            "https://official.example/kor/media/newsroom/list.do",
            html,
        )
        self.assertEqual(
            links,
            ["https://official.example/kor/media/newsroom/view.do?seq=1"],
        )


if __name__ == "__main__":
    unittest.main()
