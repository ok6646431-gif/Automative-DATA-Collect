import unittest

from orchestrator.g0_report_enrichment import first_publication_claim


class FirstPublicationEvidenceTests(unittest.TestCase):
    def test_explicit_korean_first_report_with_year_is_verified_candidate(self):
        claim = first_publication_claim(
            "한화에어로스페이스는 2021년 첫 지속가능경영보고서를 발간했다.",
            "https://official.example/news/first-report",
            2020,
            2026,
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim["first_report_year"], 2021)
        self.assertEqual(claim["evidence_type"], "EXPLICIT_FIRST_ANNUAL_REPORT_CLAIM")

    def test_report_then_first_publication_word_order_is_accepted(self):
        claim = first_publication_claim(
            "2021. 11. 22 한화에어로스페이스, 지속가능경영보고서 첫 발간, ESG경영 본격화",
            "https://official.example/news/report-first",
            2020,
            2026,
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim["first_report_year"], 2021)

    def test_explicit_english_inaugural_report_with_year_is_accepted(self):
        claim = first_publication_claim(
            "In 2022 the company published its inaugural sustainability report.",
            "https://official.example/news/inaugural-report",
            2020,
            2026,
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim["first_report_year"], 2022)

    def test_archive_beginning_at_one_year_is_not_first_publication_evidence(self):
        claim = first_publication_claim(
            "지속가능경영보고서 2021 2022 2023 2024 2025",
            "https://official.example/esg/reports",
            2020,
            2026,
        )
        self.assertIsNone(claim)

    def test_first_report_phrase_without_nearby_year_fails_closed(self):
        claim = first_publication_claim(
            "당사는 첫 지속가능경영보고서를 발간했습니다.",
            "https://official.example/news/report",
            2020,
            2026,
        )
        self.assertIsNone(claim)

    def test_year_outside_requested_window_is_not_used(self):
        claim = first_publication_claim(
            "2018년 첫 지속가능경영보고서를 발간했습니다.",
            "https://official.example/news/report",
            2020,
            2026,
        )
        self.assertIsNone(claim)


if __name__ == "__main__":
    unittest.main()
