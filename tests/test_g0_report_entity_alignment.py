import unittest

from orchestrator.g0_report_entity_policy import entity_alignment


class ReportEntityAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.discovery = {
            "requested_company_name": "예시화학(주)",
            "current_legal_name": "예시화학 주식회사",
            "company_aliases": [
                {
                    "name": "Example Chemicals CO.,LTD",
                    "alias_type": "english_legal_name",
                    "verification_state": "VERIFIED",
                }
            ],
        }

    def test_report_title_may_omit_terminal_english_legal_form(self):
        status, issuers = entity_alignment(
            self.discovery,
            "Example Chemicals Sustainability Report 2023.pdf",
            "",
        )
        self.assertEqual(status, "ALIGNED")
        self.assertIn("examplechemicals", issuers)

    def test_affiliate_word_is_not_erased_with_legal_suffix(self):
        status, issuers = entity_alignment(
            self.discovery,
            "Example Chemicals Energy Co., Ltd. Sustainability Report 2023.pdf",
            "",
        )
        self.assertEqual(status, "CONFLICT")
        self.assertIn("examplechemicalsenergy", issuers)

    def test_issuer_with_legal_form_and_verified_alias_aligns(self):
        status, _ = entity_alignment(
            self.discovery,
            "Example Chemicals Co., Ltd. Sustainability Report 2023.pdf",
            "",
        )
        self.assertEqual(status, "ALIGNED")

    def test_korean_range_year_prefix_is_not_mistaken_for_issuer(self):
        for title in (
            "2019_20년 지속가능경영보고서(국문)",
            "2020_21년 지속가능경영보고서(국문)",
            "2021-22년 지속가능경영보고서(국문)",
            "2022/23년 지속가능경영보고서(국문)",
        ):
            with self.subTest(title=title):
                status, issuers = entity_alignment(self.discovery, title, "")
                self.assertEqual(status, "UNKNOWN")
                self.assertEqual(issuers, [])

    def test_range_year_cleanup_does_not_hide_actual_affiliate_issuer(self):
        status, issuers = entity_alignment(
            self.discovery,
            "2022_23 Example Chemicals Energy Co., Ltd. Sustainability Report",
            "",
        )
        self.assertEqual(status, "CONFLICT")
        self.assertIn("examplechemicalsenergy", issuers)


if __name__ == "__main__":
    unittest.main()
