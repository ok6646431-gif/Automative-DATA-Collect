import unittest

from orchestrator.g0_report_enrichment import strong_report_semantics


class TestG0ReportEnrichment(unittest.TestCase):
    def test_sustainability_report_filename_is_accepted(self):
        self.assertTrue(strong_report_semantics(
            "다운로드",
            "https://official.example/pdf/회사_지속가능경영보고서_2024_F.pdf",
            "https://official.example/sustainability/",
        ))

    def test_brochure_never_satisfies_annual_report(self):
        self.assertFalse(strong_report_semantics(
            "브로슈어 다운로드 (2025)",
            "https://official.example/pdf/Company_Brochure_KR_2025.pdf",
            "https://official.example/media/brochure/",
        ))

    def test_generic_pdf_without_report_semantics_is_rejected(self):
        self.assertFalse(strong_report_semantics(
            "다운로드",
            "https://official.example/download/2025.pdf",
            "https://official.example/media/",
        ))


if __name__ == "__main__":
    unittest.main()
