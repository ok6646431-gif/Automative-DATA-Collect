import unittest

from orchestrator import g0_report_finalizer as finalizer


class ReportFinalizerTests(unittest.TestCase):
    def test_full_report_pdf_is_not_demoted_by_incidental_highlight_text(self):
        discovery = {
            "requested_company_name": "테스트",
            "current_legal_name": "테스트 주식회사",
            "company_aliases": [{"name": "TEST", "alias_type": "english_legal_name"}],
        }
        documents = {
            "documents": [{
                "document_id": "AUTO_SUSTAINABILITY_2023",
                "document_type": "SUSTAINABILITY_REPORT_SUMMARY",
                "title": "2023 Sustainability Report ESG Management Highlight Environmental",
                "report_year": 2023,
                "source_url": "https://sustainability.example.com/files/TEST_Sustainability_Report_2023_eng.pdf",
                "source_locator": "https://sustainability.example.com/reports",
                "expected_extension": "pdf",
                "importance": "SUPPORTING",
                "coverage_role": "SUPPORTING_SUMMARY_ONLY",
            }],
            "gaps": [{
                "gap_id": "AUTO_SUSTAINABILITY_2023_TARGET_UNRESOLVED",
                "document_type": "SUSTAINABILITY_REPORT",
                "year": 2023,
                "blocking": True,
            }],
        }
        audit = {}
        out = finalizer.finalize(discovery, documents, audit)
        self.assertEqual(out["documents"][0]["document_type"], "SUSTAINABILITY_REPORT")
        self.assertEqual(out["documents"][0]["importance"], "CORE")
        self.assertEqual(out["documents"][0]["title"], "TEST Sustainability Report 2023 eng")
        self.assertNotIn("coverage_role", out["documents"][0])
        self.assertEqual(out["gaps"], [])
        self.assertEqual(out["discovery_status"], "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE")
        self.assertEqual(len(audit["stages"]["report_finalizer"]["promoted_full_report_pdfs"]), 1)
        self.assertEqual(len(audit["stages"]["report_finalizer"]["normalized_pdf_titles"]), 1)

    def test_existing_full_report_uses_concrete_year_specific_pdf_title(self):
        discovery = {"requested_company_name": "테스트", "current_legal_name": "테스트"}
        documents = {
            "documents": [{
                "document_id": "D2021",
                "document_type": "SUSTAINABILITY_REPORT",
                "title": "2025 Sustainability Report current catalog heading and many sections",
                "report_year": 2021,
                "source_url": "https://example.com/files/TEST_Sustainability_Report_2021_eng.pdf",
                "expected_extension": "pdf",
                "importance": "CORE",
            }],
            "gaps": [],
        }
        audit = {}
        out = finalizer.finalize(discovery, documents, audit)
        self.assertEqual(out["documents"][0]["title"], "TEST Sustainability Report 2021 eng")
        self.assertEqual(out["documents"][0]["report_year"], 2021)
        self.assertEqual(len(audit["stages"]["report_finalizer"]["normalized_pdf_titles"]), 1)

    def test_highlight_filename_remains_supporting_summary(self):
        discovery = {"requested_company_name": "테스트", "current_legal_name": "테스트"}
        documents = {
            "documents": [{
                "document_id": "D1",
                "document_type": "SUSTAINABILITY_REPORT_SUMMARY",
                "title": "2023 Sustainability Report",
                "report_year": 2023,
                "source_url": "https://example.com/TEST_Sustainability_Report_2023_highlight.pdf",
                "expected_extension": "pdf",
                "importance": "SUPPORTING",
            }],
            "gaps": [{
                "gap_id": "G1",
                "document_type": "SUSTAINABILITY_REPORT",
                "year": 2023,
                "blocking": True,
            }],
        }
        out = finalizer.finalize(discovery, documents, {})
        self.assertEqual(out["documents"][0]["document_type"], "SUSTAINABILITY_REPORT_SUMMARY")
        self.assertEqual(len(out["gaps"]), 1)
        self.assertEqual(out["discovery_status"], "PARTIAL")


if __name__ == "__main__":
    unittest.main()
