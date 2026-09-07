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


if __name__ == "__main__":
    unittest.main()
