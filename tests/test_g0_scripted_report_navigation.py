import unittest

from orchestrator.g0_scripted_report_navigation import extract_report_navigation_targets


class TestG0ScriptedReportNavigation(unittest.TestCase):
    def test_report_semantic_href_is_recovered(self):
        html = '<nav><a href="/dl/rep/" data-path="rep">지속가능경영보고서</a></nav>'
        self.assertEqual(
            extract_report_navigation_targets("https://esg.example/", html),
            ["https://esg.example/dl/rep/"],
        )

    def test_report_semantic_javascript_path_is_recovered(self):
        html = (
            '<button aria-label="Sustainability Report" '
            'onclick="location.href=\'/library/reports/\'">Reports</button>'
        )
        self.assertEqual(
            extract_report_navigation_targets("https://esg.example/home", html),
            ["https://esg.example/library/reports/"],
        )

    def test_unrelated_script_path_is_not_recovered(self):
        html = '<button onclick="location.href=\'/career/jobs/\'">채용</button>'
        self.assertEqual(extract_report_navigation_targets("https://esg.example/", html), [])

    def test_cross_host_report_target_is_rejected(self):
        html = '<a href="https://other.example/reports/">지속가능경영보고서</a>'
        self.assertEqual(extract_report_navigation_targets("https://esg.example/", html), [])


if __name__ == "__main__":
    unittest.main()
