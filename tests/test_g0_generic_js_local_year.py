import unittest

from orchestrator.g0_generic_js_report_recovery import extract_report_controls


class GenericJsLocalYearTests(unittest.TestCase):
    def test_literal_year_wins_over_ambiguous_multi_year_ancestor(self):
        html = '''
        <section class="report-archive">
          <h2>지속가능경영보고서</h2>
          <div class="all-years">
            <div>2024 지속가능경영보고서</div>
            <a onclick="mergeAnnual('2024','report_2024','kor')">KOR<i class="icon-download"></i></a>
            <div class="nested">
              <div>2023 지속가능경영보고서</div>
              <a onclick="mergeAnnual('2023','report_2023','kor')">KOR<i class="icon-download"></i></a>
              <div class="more-nested">
                <div>2022 지속가능경영보고서</div>
                <a onclick="mergeAnnual('2022','report_2022','kor')">KOR<i class="icon-download"></i></a>
                <div>
                  <span>2021 지속가능경영보고서</span>
                  <a onclick="mergeAnnual('2021','report_2021','kor')">KOR<i class="icon-download"></i></a>
                </div>
              </div>
            </div>
          </div>
        </section>
        '''
        controls = extract_report_controls(html, 2020, 2026)
        annual = [c for c in controls if c.get("function") == "mergeAnnual"]
        self.assertEqual({c["year"] for c in annual}, {2021, 2022, 2023, 2024})
        by_arg = {c["args"][0]: c for c in annual}
        for year in (2021, 2022, 2023, 2024):
            self.assertEqual(by_arg[str(year)]["year"], year)
            self.assertEqual(by_arg[str(year)]["year_evidence"], "CONTROL_LITERAL")

    def test_direct_pdf_target_supplies_local_year_in_shared_archive(self):
        html = '''
        <section>
          <h2>지속가능경영보고서 2021 2020</h2>
          <div>
            <button onclick="window.open('../files/report_2021_kor.pdf', '_blank')">
              KOR <i class="download"></i>
            </button>
            <button onclick="window.open('../files/report_2020_kor.pdf', '_blank')">
              KOR <i class="download"></i>
            </button>
          </div>
        </section>
        '''
        controls = extract_report_controls(html, 2020, 2026)
        direct = [c for c in controls if c.get("direct_targets")]
        self.assertEqual({c["year"] for c in direct}, {2020, 2021})
        self.assertTrue(all(c["year_evidence"] == "CONTROL_LITERAL" for c in direct))

    def test_ambiguous_multi_year_dom_without_literal_year_fails_closed(self):
        html = '''
        <section>
          <h2>2024 지속가능경영보고서 / 2023 지속가능경영보고서</h2>
          <a onclick="downloadAnnual('report-current','kor')">PDF 다운로드</a>
        </section>
        '''
        controls = extract_report_controls(html, 2020, 2026)
        self.assertEqual(controls, [])


if __name__ == "__main__":
    unittest.main()
