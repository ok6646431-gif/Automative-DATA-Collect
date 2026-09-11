import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator import g0_report_catalog_policy as catalog_policy
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

    def test_verified_pdf_supersedes_same_year_digital_report(self):
        discovery = {
            "requested_company_name": "테스트",
            "current_legal_name": "테스트 주식회사",
            "company_aliases": [{"name": "TEST", "alias_type": "english_legal_name"}],
        }
        documents = {
            "documents": [
                {
                    "document_id": "AUTO_SUSTAINABILITY_2023",
                    "document_type": "SUSTAINABILITY_REPORT_SUMMARY",
                    "title": "2023 Sustainability Report ESG Highlight",
                    "report_year": 2023,
                    "source_url": "https://sustainability.example.com/files/TEST_Sustainability_Report_2023_eng.pdf",
                    "source_locator": "https://sustainability.example.com/reports",
                    "expected_extension": "pdf",
                    "verification_status": "SOURCE_VERIFIED",
                    "importance": "SUPPORTING",
                    "coverage_role": "SUPPORTING_SUMMARY_ONLY",
                },
                {
                    "document_id": "AUTO_SUSTAINABILITY_DIGITAL_2023",
                    "document_type": "SUSTAINABILITY_REPORT",
                    "title": "2023 Sustainability Report",
                    "report_year": 2023,
                    "source_url": "https://sustainability.example.com/reports",
                    "source_locator": "https://sustainability.example.com/reports",
                    "expected_extension": "html",
                    "verification_status": "SOURCE_VERIFIED",
                    "importance": "CORE",
                    "representation": "DIGITAL_REPORT",
                },
            ],
            "gaps": [{
                "gap_id": "AUTO_SUSTAINABILITY_2023_TARGET_UNRESOLVED",
                "document_type": "SUSTAINABILITY_REPORT",
                "year": 2023,
                "blocking": True,
            }],
        }
        audit = {}
        out = finalizer.finalize(discovery, documents, audit)
        annual_2023 = [
            d for d in out["documents"]
            if d.get("document_type") == "SUSTAINABILITY_REPORT" and d.get("report_year") == 2023
        ]
        self.assertEqual(len(annual_2023), 1)
        self.assertEqual(annual_2023[0]["source_url"], "https://sustainability.example.com/files/TEST_Sustainability_Report_2023_eng.pdf")
        self.assertEqual(annual_2023[0]["expected_extension"], "pdf")
        self.assertEqual(out["gaps"], [])
        self.assertEqual(len(audit["stages"]["report_finalizer"]["superseded_digital_reports"]), 1)

    def test_opaque_verified_annual_pdf_supersedes_same_year_digital_report(self):
        discovery = {"requested_company_name": "테스트", "current_legal_name": "테스트"}
        documents = {
            "documents": [
                {
                    "document_id": "PLAIN_2025",
                    "document_type": "SUSTAINABILITY_REPORT",
                    "title": "2025 sustainability report KOR",
                    "report_year": 2025,
                    "source_url": "https://official.example/download.do?fid=REPORT2025",
                    "source_locator": "https://official.example/report-archive",
                    "expected_extension": "pdf",
                    "verification_status": "SOURCE_VERIFIED",
                    "importance": "CORE",
                },
                {
                    "document_id": "DIGITAL_2025",
                    "document_type": "SUSTAINABILITY_REPORT",
                    "title": "2025 sustainability report",
                    "report_year": 2025,
                    "source_url": "https://official.example/report/2025",
                    "source_locator": "https://official.example/report/2025",
                    "expected_extension": "html",
                    "verification_status": "SOURCE_VERIFIED",
                    "importance": "CORE",
                    "representation": "DIGITAL_REPORT",
                },
            ],
            "gaps": [],
        }
        audit = {}
        out = finalizer.finalize(discovery, documents, audit)
        annual = [d for d in out["documents"] if d.get("document_type") == "SUSTAINABILITY_REPORT"]
        self.assertEqual(len(annual), 1)
        self.assertEqual(annual[0]["source_url"], "https://official.example/download.do?fid=REPORT2025")
        self.assertEqual(audit["stages"]["report_finalizer"]["verified_annual_pdf_years"], [2025])
        self.assertEqual(len(audit["stages"]["report_finalizer"]["superseded_digital_reports"]), 1)

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


class ReportCatalogCurrentYearTests(unittest.TestCase):
    def test_verified_route_merge_precedes_final_coverage_policies(self):
        runner_path = Path(__file__).resolve().parents[1] / "orchestrator" / "zero_touch_runner.py"
        source = runner_path.read_text(encoding="utf-8")
        start = source.index("def _enriched_discover")
        merge_pos = source.index(
            "documents = _merge_verified_document_routes(discovery, documents, audit)", start
        )
        finalizer_pos = source.index(
            "documents = g0_report_finalizer.finalize(discovery, documents, audit)", start
        )
        catalog_pos = source.index(
            "documents = g0_report_catalog_policy.normalize_verified_catalog_gaps(", start
        )
        promotion_pos = source.index(
            "discovery, documents, audit = g0_promotion_policy.apply(", start
        )
        self.assertLess(merge_pos, finalizer_pos)
        self.assertLess(finalizer_pos, catalog_pos)
        self.assertLess(catalog_pos, promotion_pos)

    def _annual_docs(self):
        locator = "https://official.example/sustainability/reports"
        return [
            {
                "document_id": f"REPORT_{year}",
                "document_type": "SUSTAINABILITY_REPORT",
                "title": f"{year} Sustainability Report",
                "report_year": year,
                "source_url": f"https://official.example/files/report_{year}.pdf",
                "source_locator": locator,
                "expected_extension": "pdf",
                "verification_status": "SOURCE_VERIFIED",
                "importance": "CORE",
            }
            for year in range(2020, 2026)
        ]

    def test_verified_catalog_current_through_previous_year_resolves_live_year(self):
        documents = {
            "documents": self._annual_docs(),
            "gaps": [{
                "gap_id": "AUTO_SUSTAINABILITY_2026_UNRESOLVED",
                "document_type": "SUSTAINABILITY_REPORT",
                "year": 2026,
                "blocking": True,
                "verification_status": "UNVERIFIED",
            }],
            "discovery_status": "PARTIAL",
        }
        with patch(
            "orchestrator.g0_report_catalog_policy._years_from_verified_catalog",
            return_value=set(range(2020, 2026)),
        ), patch(
            "orchestrator.g0_report_catalog_policy._current_utc_year",
            return_value=2026,
        ):
            out = catalog_policy.normalize_verified_catalog_gaps({}, documents, {})
        gap = out["gaps"][0]
        self.assertEqual(gap["status"], "NOT_PUBLISHED")
        self.assertEqual(gap["verification_status"], "SOURCE_VERIFIED")
        self.assertFalse(gap["blocking"])
        self.assertEqual(out["discovery_status"], "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE")

    def test_catalog_listing_current_year_does_not_hide_missing_target(self):
        documents = {
            "documents": self._annual_docs(),
            "gaps": [{
                "gap_id": "AUTO_SUSTAINABILITY_2026_TARGET_UNRESOLVED",
                "document_type": "SUSTAINABILITY_REPORT",
                "year": 2026,
                "blocking": True,
                "verification_status": "SOURCE_VERIFIED",
            }],
            "discovery_status": "PARTIAL",
        }
        with patch(
            "orchestrator.g0_report_catalog_policy._years_from_verified_catalog",
            return_value=set(range(2020, 2027)),
        ), patch(
            "orchestrator.g0_report_catalog_policy._current_utc_year",
            return_value=2026,
        ):
            out = catalog_policy.normalize_verified_catalog_gaps({}, documents, {})
        gap = out["gaps"][0]
        self.assertTrue(gap["blocking"])
        self.assertNotEqual(gap.get("status"), "NOT_PUBLISHED")
        self.assertEqual(out["discovery_status"], "PARTIAL")

    def test_historical_trailing_gap_is_not_excused_as_current_year_cadence(self):
        self.assertFalse(
            catalog_policy._catalog_supports_current_year_nonpublication(
                2025, {2020, 2021, 2022, 2023, 2024}, current_year=2026
            )
        )


if __name__ == "__main__":
    unittest.main()
