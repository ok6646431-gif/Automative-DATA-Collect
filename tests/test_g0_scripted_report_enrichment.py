import unittest

from orchestrator.g0_data_attr_report_recovery import (
    candidates_from_data_attr_page,
    extract_data_controls,
    reconstruct_data_targets,
)
from orchestrator.g0_generic_js_report_recovery import (
    candidates_from_generic_js_page,
    extract_direct_literal_targets,
    extract_literal_calls,
    extract_report_controls,
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
        if url.endswith("/files/report_2024_eng.pdf") or url.endswith("/files/report_2024_kor.pdf"):
            return FakeResponse(
                url,
                content=b"%PDF-1.7\nnested-js",
                content_type="application/pdf",
            )
        if url.endswith("/files/report_2020_kor.pdf"):
            return FakeResponse(
                url,
                content=b"%PDF-1.7\ndirect-js",
                content_type="application/pdf",
            )
        if "/fileViewer/pdf/1786079799668_7461931077646106262/attr/company/2026%20" in url or (
            "/fileViewer/pdf/1786079799668_7461931077646106262/attr/company/" in url
            and url.endswith(".pdf")
        ):
            return FakeResponse(
                url,
                content=b"%PDF-1.7\ndata-attr",
                content_type="application/pdf",
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

    def test_icon_only_control_and_nested_function_recover_year_specific_pdf(self):
        html = '''
        <html><body>
          <article class="annual-report">
            <h3>2024 지속가능경영보고서</h3>
            <a href="javascript:void(0)" onclick="mergeAnnual('2024','report_2024','kor')">
              KOR <i class="icon icon-download"></i>
            </a>
          </article>
          <script>
          function mergeAnnual(year, pdfNm, lang) {
            if (lang == "eng") {
              var url = "../files/report_" + year + "_eng.pdf";
            } else {
              var url = "../files/report_" + year + "_kor.pdf";
            }
            window.open(url);
          }
          </script>
        </body></html>
        '''
        controls = extract_report_controls(html, 2020, 2026)
        self.assertTrue(any(c["function"] == "mergeAnnual" for c in controls))
        found, diagnostics = candidates_from_generic_js_page(
            FakeHttp(),
            "https://official.example/esg/report/",
            html,
            2020,
            2026,
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["year"], 2024)
        self.assertIn(found[0]["url"], {
            "https://official.example/esg/files/report_2024_eng.pdf",
            "https://official.example/esg/files/report_2024_kor.pdf",
        })
        self.assertEqual(found[0]["download_contract"], "VERIFIED_GENERIC_SAME_HOST_JS_FUNCTION")
        self.assertTrue(any(d["function_definition_found"] for d in diagnostics if d["function"] == "mergeAnnual"))

    def test_direct_window_open_literal_is_recovered_without_function_definition(self):
        raw = "window.open('../files/report_2020_kor.pdf', '_blank')"
        self.assertEqual(extract_direct_literal_targets(raw), ["../files/report_2020_kor.pdf"])
        html = '''
        <html><body>
          <article class="annual-report">
            <h3>2020 지속가능경영보고서</h3>
            <button onclick="window.open('../files/report_2020_kor.pdf', '_blank')">국문</button>
          </article>
        </body></html>
        '''
        found, _ = candidates_from_generic_js_page(
            FakeHttp(),
            "https://official.example/esg/report/",
            html,
            2020,
            2026,
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["url"], "https://official.example/esg/files/report_2020_kor.pdf")
        self.assertEqual(found[0]["download_contract"], "VERIFIED_DIRECT_SAME_HOST_JS_TARGET")

    def _data_attr_html(self):
        return '''
        <html><body>
          <section class="report-library">
            <h3>지속가능경영보고서</h3>
            <article>
              <span>2026 지속가능경영보고서</span>
              <a href="javascript:;" class="btn icon-down_pdf fileDown"
                 data-savenm="1786079799668_7461931077646106262.pdf"
                 data-filepath="/attr/company"
                 data-orgnm="2026 금호타이어 지속가능경영보고서.pdf">
                 <span>국문 PDF 다운로드</span>
              </a>
            </article>
          </section>
          <script>
          $(function(){
            $(".fileDown").on('click', function(e){
              e.preventDefault();
              var ext = $(this).data('savenm').substring($(this).data('savenm').indexOf('.') + 1);
              var save = $(this).data('savenm').substring(0, $(this).data('savenm').indexOf('.'));
              var nm = $(this).data('orgnm').substring(0, $(this).data('orgnm').lastIndexOf('.'));
              if(ext.toLowerCase() == 'pdf'){
                var url = '/fileViewer/' + ext + '/' + save + $(this).data('filepath') + '/' + nm + '.' + ext;
                window.open(url);
              }else{
                $('#fileFrm').attr('action', '/fileDownload.do');
              }
            });
          })
          </script>
        </body></html>
        '''

    def test_data_attribute_report_control_is_extracted(self):
        controls = extract_data_controls(self._data_attr_html(), 2020, 2026)
        self.assertEqual(len(controls), 1)
        self.assertEqual(controls[0]["year"], 2026)
        self.assertEqual(controls[0]["data"]["filepath"], "/attr/company")
        self.assertIn("fileDown", controls[0]["classes"])

    def test_data_attribute_handler_reconstructs_viewer_url(self):
        controls = extract_data_controls(self._data_attr_html(), 2020, 2026)
        handler = '''
              e.preventDefault();
              var ext = $(this).data('savenm').substring($(this).data('savenm').indexOf('.') + 1);
              var save = $(this).data('savenm').substring(0, $(this).data('savenm').indexOf('.'));
              var nm = $(this).data('orgnm').substring(0, $(this).data('orgnm').lastIndexOf('.'));
              if(ext.toLowerCase() == 'pdf'){
                var url = '/fileViewer/' + ext + '/' + save + $(this).data('filepath') + '/' + nm + '.' + ext;
                window.open(url);
              }
        '''
        targets = reconstruct_data_targets(
            "https://official.example/ko/ESG/Materials/Report/",
            controls[0]["data"],
            handler,
        )
        self.assertEqual(
            targets,
            [
                "https://official.example/fileViewer/pdf/1786079799668_7461931077646106262"
                "/attr/company/2026 금호타이어 지속가능경영보고서.pdf"
            ],
        )

    def test_data_attribute_report_requires_handler_and_pdf_bytes(self):
        found, diagnostics = candidates_from_data_attr_page(
            FakeHttp(),
            "https://official.example/ko/ESG/Materials/Report/",
            self._data_attr_html(),
            2020,
            2026,
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["year"], 2026)
        self.assertEqual(found[0]["download_contract"], "VERIFIED_DATA_ATTRIBUTE_JS_HANDLER")
        self.assertIn("fileDown", diagnostics[0]["matched_handler_classes"])
        self.assertTrue(diagnostics[0]["candidate_targets"])


if __name__ == "__main__":
    unittest.main()
