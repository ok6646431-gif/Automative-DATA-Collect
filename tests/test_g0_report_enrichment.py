import unittest

from orchestrator import g0_entity_window_normalization as entity_window
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


class LegalEntityDocumentWindowTests(unittest.TestCase):
    def _discovery(self):
        return {
            "requested_company_name": "Example",
            "collection_policy": {
                "requested_history_window": {"start_year": 2020, "end_year": 2026}
            },
        }

    def _audit(self, establishment_date="2022-03-02"):
        return {
            "stages": {
                "legal_identity": {
                    "resolved": {"establishment_date": establishment_date}
                }
            }
        }

    def test_pre_establishment_years_are_not_blocking_current_entity_gaps(self):
        documents = {
            "documents": [],
            "gaps": [
                {
                    "gap_id": f"AUTO_SUSTAINABILITY_{year}_UNRESOLVED",
                    "document_type": "SUSTAINABILITY_REPORT",
                    "year": year,
                    "blocking": True,
                }
                for year in range(2020, 2027)
            ],
        }
        discovery = self._discovery()
        audit = self._audit()
        entity_window.normalize(discovery, documents, audit)

        self.assertEqual(
            [g["year"] for g in documents["gaps"]],
            [2022, 2023, 2024, 2025, 2026],
        )
        self.assertEqual(discovery["legal_entity_active_period"]["start_year"], 2022)
        self.assertEqual(
            documents["discovery_scope"]["effective_current_entity_history_window"],
            {"start_year": 2022, "end_year": 2026},
        )
        self.assertEqual(
            audit["stages"]["legal_entity_document_window"]["removed_pre_entity_blocking_gap_years"],
            [2020, 2021],
        )

    def test_pre_entity_report_is_preserved_but_not_promoted_as_current_coverage(self):
        documents = {
            "documents": [{
                "document_id": "OLD_2021",
                "document_type": "SUSTAINABILITY_REPORT",
                "report_year": 2021,
                "notes": "Verified official PDF.",
            }],
            "gaps": [],
        }
        discovery = self._discovery()
        audit = self._audit()
        entity_window.normalize(discovery, documents, audit)
        doc = documents["documents"][0]
        self.assertEqual(doc["coverage_role"], "PRE_ENTITY_HISTORICAL_REFERENCE")
        self.assertIn("predates the verified current legal-entity start", doc["notes"])

    def test_old_entity_keeps_requested_window_unchanged(self):
        documents = {
            "documents": [],
            "gaps": [{
                "gap_id": "AUTO_SUSTAINABILITY_2020_UNRESOLVED",
                "document_type": "SUSTAINABILITY_REPORT",
                "year": 2020,
                "blocking": True,
            }],
        }
        discovery = self._discovery()
        audit = self._audit("1980-01-01")
        entity_window.normalize(discovery, documents, audit)
        self.assertEqual([g["year"] for g in documents["gaps"]], [2020])
        self.assertEqual(
            documents["discovery_scope"]["effective_current_entity_history_window"]["start_year"],
            2020,
        )


if __name__ == "__main__":
    unittest.main()
