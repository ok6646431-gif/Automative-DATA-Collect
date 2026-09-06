import unittest

from orchestrator.g0_plain_href_report_recovery import candidates_from_plain_href_page


class FakeResponse:
    def __init__(self, url, content=b"", status=200, content_type="application/octet-stream"):
        self.url = url
        self.content = content
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.text = ""

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def close(self):
        pass


class FakeHttp:
    def __init__(self):
        self.audit = []

    def get(self, url, **kwargs):
        if "fid=REPORT2025" in url:
            return FakeResponse(url, b"%PDF-1.7\nannual-report")
        if "fid=FACTBOOK2025" in url:
            return FakeResponse(url, b"%PDF-1.7\nfactbook")
        if "fid=REPORT2024" in url:
            return FakeResponse(url, b"%PDF-1.7\nannual-report-2024")
        if "other.example" in url:
            return FakeResponse(url, b"%PDF-1.7\ncross-host")
        return FakeResponse(url, status=404)


class PlainHrefReportRecoveryTests(unittest.TestCase):
    def test_plain_same_host_href_recovers_nearest_local_year(self):
        html = '''
        <section class="archive">
          <article><h3>2025 지속가능경영보고서</h3>
            <a href="/download.do?fid=REPORT2025">KOR</a>
          </article>
          <article><h3>2024 지속가능경영보고서</h3>
            <a href="/download.do?fid=REPORT2024">KOR</a>
          </article>
        </section>
        '''
        found, diagnostics = candidates_from_plain_href_page(
            FakeHttp(), "https://official.example/reports", html, 2020, 2026
        )
        self.assertEqual({x["year"] for x in found}, {2024, 2025})
        by_year = {x["year"]: x for x in found}
        self.assertEqual(by_year[2025]["url"], "https://official.example/download.do?fid=REPORT2025")
        self.assertEqual(by_year[2025]["download_contract"], "VERIFIED_PLAIN_SAME_ORG_HREF_LOCAL_YEAR")
        self.assertTrue(all(x.get("pdf_magic_verified") for x in diagnostics))

    def test_factbook_is_excluded_even_when_pdf_bytes_are_valid(self):
        html = '''
        <article><h3>2025 지속가능경영보고서</h3>
          <a href="/download.do?fid=REPORT2025">KOR</a>
          <a href="/download.do?fid=FACTBOOK2025">Factbook</a>
        </article>
        '''
        found, _ = candidates_from_plain_href_page(
            FakeHttp(), "https://official.example/reports", html, 2020, 2026
        )
        self.assertEqual(len(found), 1)
        self.assertIn("REPORT2025", found[0]["url"])

    def test_cross_host_href_is_rejected(self):
        html = '''
        <article><h3>2025 지속가능경영보고서</h3>
          <a href="https://other.example/download.do?fid=REPORT2025">KOR</a>
        </article>
        '''
        found, diagnostics = candidates_from_plain_href_page(
            FakeHttp(), "https://official.example/reports", html, 2020, 2026
        )
        self.assertEqual(found, [])
        self.assertEqual(diagnostics, [])

    def test_ambiguous_multi_year_context_fails_closed(self):
        html = '''
        <section><h3>2025 지속가능경영보고서 / 2024 지속가능경영보고서</h3>
          <a href="/download.do?fid=REPORT2025">KOR</a>
        </section>
        '''
        found, diagnostics = candidates_from_plain_href_page(
            FakeHttp(), "https://official.example/reports", html, 2020, 2026
        )
        self.assertEqual(found, [])
        self.assertEqual(diagnostics, [])

    def test_non_pdf_payload_is_rejected(self):
        class HtmlHttp(FakeHttp):
            def get(self, url, **kwargs):
                return FakeResponse(url, b"<html>login</html>", content_type="text/html")

        html = '''
        <article><h3>2025 지속가능경영보고서</h3>
          <a href="/download.do?fid=REPORT2025">KOR</a>
        </article>
        '''
        found, diagnostics = candidates_from_plain_href_page(
            HtmlHttp(), "https://official.example/reports", html, 2020, 2026
        )
        self.assertEqual(found, [])
        self.assertEqual(len(diagnostics), 1)
        self.assertFalse(diagnostics[0]["pdf_magic_verified"])


if __name__ == "__main__":
    unittest.main()
