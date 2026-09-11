import unittest
from urllib.parse import parse_qs, urlparse

from orchestrator.g0_js_form_report_recovery import (
    extract_form_report_controls,
    reconstruct_get_form_targets,
)


class JsFormReportRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.html = '''
        <section class="report-library">
          <ul>
            <li>
              <p class="title">[2022] SUSTAINABILITY REPORT</p>
              <p><a href="javascript:void(0)" onclick="requestAnnual('file-22')">KOR</a></p>
            </li>
          </ul>
          <form id="surveyForm" method="get" action="/reports/download-survey/">
            <input type="hidden" name="document_id" id="document_id" value="">
            <input type="hidden" name="unrelated_static" value="do-not-require-this">
            <input type="radio" name="audience" id="audience_other" value="other">
            <input type="submit" id="downloadButton" value="Download">
          </form>
          <script>
            function requestAnnual(fileId) {
              $("#document_id").val(fileId);
              $('#audience_other').prop('checked', true);
              $('#downloadButton').click();
            }
          </script>
        </section>
        '''

    def test_local_report_control_is_admitted_without_download_word(self):
        controls = extract_form_report_controls(self.html, 2020, 2026)
        self.assertEqual(len(controls), 1)
        self.assertEqual(controls[0]["year"], 2022)
        self.assertEqual(controls[0]["function"], "requestAnnual")
        self.assertEqual(controls[0]["args"], ["file-22"])
        self.assertEqual(controls[0]["year_evidence"], "LOCAL_DOM")

    def test_korean_sustainability_noun_form_is_admitted(self):
        html = self.html.replace("[2022] SUSTAINABILITY REPORT", "2022 지속가능성보고서")
        controls = extract_form_report_controls(html, 2020, 2026)
        self.assertEqual(len(controls), 1)
        self.assertEqual(controls[0]["year"], 2022)
        self.assertEqual(controls[0]["function"], "requestAnnual")

    def test_get_form_target_is_reconstructed_from_declared_contract(self):
        controls = extract_form_report_controls(self.html, 2020, 2026)
        body = '''
          $("#document_id").val(fileId);
          $('#audience_other').prop('checked', true);
          $('#downloadButton').click();
        '''
        targets = reconstruct_get_form_targets(
            "https://example.com/esg/reports/",
            self.html,
            ["fileId"],
            controls[0]["args"],
            body,
        )
        self.assertEqual(len(targets), 1)
        parsed = urlparse(targets[0])
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "example.com")
        self.assertEqual(parsed.path, "/reports/download-survey/")
        self.assertEqual(
            parse_qs(parsed.query),
            {"document_id": ["file-22"], "audience": ["other"]},
        )
        self.assertNotIn("unrelated_static", parse_qs(parsed.query))

    def test_non_report_js_control_fails_closed(self):
        html = '''
        <section>
          <h2>Customer survey</h2>
          <a href="javascript:void(0)" onclick="requestAnnual('file-22')">KOR</a>
        </section>
        '''
        self.assertEqual(extract_form_report_controls(html, 2020, 2026), [])

    def test_post_form_is_not_reconstructed(self):
        html = self.html.replace('method="get"', 'method="post"')
        controls = extract_form_report_controls(html, 2020, 2026)
        targets = reconstruct_get_form_targets(
            "https://example.com/esg/reports/",
            html,
            ["fileId"],
            controls[0]["args"],
            '''
            $("#document_id").val(fileId);
            $('#audience_other').prop('checked', true);
            $('#downloadButton').click();
            ''',
        )
        self.assertEqual(targets, [])

    def test_cross_host_form_action_is_not_reconstructed(self):
        html = self.html.replace(
            'action="/reports/download-survey/"',
            'action="https://downloads.other.example/report"',
        )
        controls = extract_form_report_controls(html, 2020, 2026)
        targets = reconstruct_get_form_targets(
            "https://example.com/esg/reports/",
            html,
            ["fileId"],
            controls[0]["args"],
            '''
            $("#document_id").val(fileId);
            $('#audience_other').prop('checked', true);
            $('#downloadButton').click();
            ''',
        )
        self.assertEqual(targets, [])


if __name__ == "__main__":
    unittest.main()
