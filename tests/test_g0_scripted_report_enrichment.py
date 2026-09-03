import unittest

from orchestrator.g0_generic_js_report_recovery import (
    candidates_from_generic_js_page,
    extract_literal_calls,
    reconstruct_targets,
)
from orchestrator.g0_scripted_report_enrichment import (
    candidates_from_scripted_page,
    extract_download_prefixes,
)


class FakeResponse:
    def __init__(self, url, text="", content=b"", status=200, content_type="text/html"):
        self.url = url
        self.text = text
        self.content = content
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.closed = False

    def iter_content(self, chunk_size=1):
        data = self.content or b""
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]

    def close(self):
        self.closed = True


class FakeHttp:
    def __init__(self):
        self.audit = []

    def get(self, url, **kwargs):
        if url.endswith("/js/download.js"):
            return FakeResponse(
                url,
                text='function fileDownload(param) { let url = getContextPath() + "/attach?et=" + param; window.location.href = url; }',
                content_type="application/javascript",
            )
        if url.endswith("/js/generic-download.js"):
            return FakeResponse(
                url,
                text=(
                    'function downloadAnnual(path, original) {'
                    ' window.location.href = "/common/download?file=" + encodeURIComponent(path)'
                    ' + "&name=" + encodeURIComponent(original);'
                    ' }'
                ),
                content_type="application/javascript",
            )
        if "/attach?et=TOKEN2024" in url:
            return FakeResponse(
                url,
                content=b"%PDF-1.7\nmock",
                content_type="application/octet-stream",
            )
        if "/common/download?file=%2Fupload%2Freport_2025.pdf&name=report_2025_kor.pdf" in url:
            return FakeResponse(
                url,
                content=b"%PDF-1.7\ngeneric",
                content_type="application/octet-stream",
            )
        return FakeResponse(url, status=404)


class TestG0ScriptedReportEnrichment(unittest.TestCase):
    def test_extract_download_prefixes_from_same_function_contract(self):
        script = 'function fileDownload(param) { let url = getContextPath() + "/attach?et=" + param; window.location.href = url; }'
        self.assertEqual(extract_download_prefixes(script), ["/attach?et="])

    def test_scripted_report_requires_report_semantics_and_pdf_bytes(self):
        html = '''
        <html><head><script src="/js/download.js"></script></head><body>
          <ol>
            <li>
              <div class="file-name"><span>2024년 지속가능경영보고서</span></div>
              <a onclick='fileDownload("TOKEN2024")' download="회사_지속가능경영보고서_2024_kor.pdf">다운로드</a>
            </li>
          </ol>
        </body></html>
        '''
        found = candidates_from_scripted_page(
            FakeHttp(),
            "https://official.example/dl/rep/",
            html,
            2020,
            2026,
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["year"], 2024)
        self.assertEqual(found[0]["url"], "https://official.example/attach?et=TOKEN2024")
        self.assertEqual(found[0]["download_contract"], "VERIFIED_SAME_HOST_SCRIPT_TOKEN")

    def test_brochure_scripted_download_is_rejected(self):
        html = '''
        <html><head><script src="/js/download.js"></script></head><body>
          <li>
            <span>2025 회사 브로슈어</span>
            <a onclick='fileDownload("TOKEN2024")' download="Company_Brochure_2025.pdf">다운로드</a>
          </li>
        </body></html>
        '''
        found = candidates_from_scripted_page(
            FakeHttp(),
            "https://official.example/media/",
            html,
            2020,
            2026,
        )
        self.assertEqual(found, [])

    def test_generic_literal_function_call_is_parsed(self):
        calls = extract_literal_calls(
            'downloadAnnual("/upload/report_2025.pdf", "report_2025_kor.pdf")'
        )
        self.assertEqual(
            calls,
            [("downloadAnnual", ["/upload/report_2025.pdf", "report_2025_kor.pdf"])],
        )

    def test_generic_js_contract_reconstructs_multi_argument_download(self):
        body = (
            'window.location.href = "/common/download?file=" + encodeURIComponent(path)'
            ' + "&name=" + encodeURIComponent(original);'
        )
        targets = reconstruct_targets(
            "https://official.example/esg/report/",
            ["path", "original"],
            ["/upload/report_2025.pdf", "report_2025_kor.pdf"],
            body,
        )
        self.assertEqual(
            targets,
            ["https://official.example/common/download?file=%2Fupload%2Freport_2025.pdf&name=report_2025_kor.pdf"],
        )

    def test_generic_js_report_control_requires_semantics_and_pdf_bytes(self):
        html = '''
        <html><head><script src="/js/generic-download.js"></script></head><body>
          <article class="annual-report">
            <h3>2025 지속가능경영보고서</h3>
            <a href="javascript:void(0)"
               onclick='downloadAnnual("/upload/report_2025.pdf", "report_2025_kor.pdf")'>
               국문 PDF 다운로드
            </a>
          </article>
        </body></html>
        '''
        found, diagnostics = candidates_from_generic_js_page(
            FakeHttp(),
            "https://official.example/esg/report/",
            html,
            2020,
            2026,
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["year"], 2025)
        self.assertEqual(found[0]["download_contract"], "VERIFIED_GENERIC_SAME_HOST_JS_FUNCTION")
        self.assertTrue(diagnostics[0]["function_definition_found"])


if __name__ == "__main__":
    unittest.main()
