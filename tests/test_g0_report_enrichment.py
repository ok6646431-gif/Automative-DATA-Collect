import unittest

from orchestrator import g0_entity_continuity_policy as continuity
from orchestrator import g0_entity_window_normalization as entity_window
from orchestrator import g0_report_catalog_policy as catalog_policy
from orchestrator import g0_report_entity_policy as report_policy
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


class ReportEntityRepresentationPolicyTests(unittest.TestCase):
    def _discovery(self):
        return {
            "requested_company_name": "포스코",
            "current_legal_name": "주식회사 포스코",
            "company_aliases": [
                {"name": "POSCO", "alias_type": "english_legal_name"},
            ],
        }

    def test_explicit_other_legal_entity_report_is_rejected(self):
        status, issuers = report_policy.entity_alignment(
            self._discovery(),
            "포스코홀딩스 지속가능경영보고서",
            "https://official.example/2025_POSCO-Holdings_Report_KOR.pdf",
        )
        self.assertEqual(status, "CONFLICT")
        self.assertIn("포스코홀딩스", issuers)

    def test_matching_english_issuer_is_aligned(self):
        status, _ = report_policy.entity_alignment(
            self._discovery(),
            "2023 POSCO Sustainability Report",
            "https://official.example/POSCO_Sustainability_Report_2023_kor.pdf",
        )
        self.assertEqual(status, "ALIGNED")

    def test_highlight_is_supporting_not_full_annual_report(self):
        self.assertTrue(report_policy.is_summary_representation(
            "하이라이트",
            "https://official.example/POSCO_Sustainability_Report_2022_highlight.pdf",
        ))

    def test_catalog_parser_can_identify_year_mentions_for_later_guarding(self):
        text = (
            "포스코 지속가능경영보고서 아카이브 "
            "2025 지속가능경영보고서 2024 지속가능경영보고서 "
            "2023 지속가능경영보고서 2022 기업시민보고서"
        )
        entries = report_policy._digital_report_entries(
            text,
            "https://sustainability.official.example/report-archive",
            self._discovery(),
            2022,
            2026,
        )
        self.assertEqual(set(entries), {2022, 2023, 2024, 2025})
        # These parser candidates are not final coverage. The catalog guard below
        # must demote a shared target before the discovery contract is finalized.
        self.assertTrue(all(x["representation"] == "DIGITAL_REPORT" for x in entries.values()))


class MultiYearCatalogGuardTests(unittest.TestCase):
    def _shared_docs(self):
        return {
            "documents": [
                {
                    "document_id": f"DIGITAL_{year}",
                    "document_type": "SUSTAINABILITY_REPORT",
                    "title": f"{year} sustainability report",
                    "report_year": year,
                    "source_url": "https://official.example/report-catalog",
                    "source_locator": "https://official.example/report-catalog",
                    "expected_extension": "html",
                    "verification_status": "SOURCE_VERIFIED",
                    "importance": "CORE",
                    "representation": "DIGITAL_REPORT",
                }
                for year in (2022, 2023, 2024)
            ],
            "gaps": [],
            "discovery_status": "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE",
        }

    def test_one_catalog_target_cannot_satisfy_multiple_annual_years(self):
        documents = self._shared_docs()
        audit = {}
        demoted = catalog_policy._demote_shared_digital_catalogs({}, documents, audit)

        self.assertEqual(len(demoted), 1)
        self.assertEqual(demoted[0]["years"], [2022, 2023, 2024])
        annual = [d for d in documents["documents"] if d["document_type"] == "SUSTAINABILITY_REPORT"]
        self.assertEqual(annual, [])
        catalog = [d for d in documents["documents"] if d.get("representation") == "REPORT_CATALOG"]
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["catalog_years"], [2022, 2023, 2024])
        self.assertEqual(
            {g["year"] for g in documents["gaps"]},
            {2022, 2023, 2024},
        )
        self.assertTrue(all(g["blocking"] for g in documents["gaps"]))
        self.assertTrue(all(g["status"] == "PUBLISHED_DOCUMENT_TARGET_UNRESOLVED" for g in documents["gaps"]))
        self.assertEqual(documents["discovery_status"], "PARTIAL")
        self.assertEqual(
            audit["stages"]["multi_year_catalog_guard"]["status"],
            "SHARED_MULTI_YEAR_DIGITAL_TARGET_DEMOTED",
        )

    def test_distinct_year_specific_targets_are_not_demoted(self):
        documents = {
            "documents": [
                {
                    "document_id": f"DIGITAL_{year}",
                    "document_type": "SUSTAINABILITY_REPORT",
                    "title": f"{year} sustainability report",
                    "report_year": year,
                    "source_url": f"https://official.example/digital-report?year={year}",
                    "source_locator": "https://official.example/report-catalog",
                    "verification_status": "SOURCE_VERIFIED",
                    "representation": "DIGITAL_REPORT",
                }
                for year in (2023, 2024)
            ],
            "gaps": [],
        }
        audit = {}
        demoted = catalog_policy._demote_shared_digital_catalogs({}, documents, audit)
        self.assertEqual(demoted, [])
        self.assertEqual(len(documents["documents"]), 2)
        self.assertEqual(documents["gaps"], [])

    def test_real_annual_target_for_same_year_prevents_false_gap(self):
        documents = self._shared_docs()
        documents["documents"].append({
            "document_id": "PDF_2023",
            "document_type": "SUSTAINABILITY_REPORT",
            "title": "2023 sustainability report PDF",
            "report_year": 2023,
            "source_url": "https://official.example/files/report_2023.pdf",
            "source_locator": "https://official.example/report-catalog",
            "expected_extension": "pdf",
            "verification_status": "VERIFIED",
            "importance": "CORE",
        })
        catalog_policy._demote_shared_digital_catalogs({}, documents, {})
        self.assertEqual(
            {g["year"] for g in documents["gaps"]},
            {2022, 2024},
        )
        annual = [d for d in documents["documents"] if d["document_type"] == "SUSTAINABILITY_REPORT"]
        self.assertEqual([d["document_id"] for d in annual], ["PDF_2023"])


class EntityContinuityPolicyTests(unittest.TestCase):
    def test_pre_entity_rename_signal_does_not_block_current_entity(self):
        discovery = {
            "current_legal_name": "주식회사 신설회사",
            "current_legal_name_active_period": {"start_year": 2022},
            "company_aliases": [{"name": "신설회사", "alias_type": "requested_name"}],
            "corporate_restructuring_evidence": [],
            "unresolved_items": [{"code": continuity.BLOCKER}],
        }
        audit = {"stages": {
            "legal_identity": {"resolved": {"establishment_date": "2022-03-02"}},
            "official_site": {"recovery": {"rename_signals": [
                {"year": 2002, "url": "https://official.example/history"}
            ]}},
        }}
        continuity.normalize(discovery, audit)
        self.assertEqual(discovery["unresolved_items"], [])
        self.assertEqual(
            audit["stages"]["entity_continuity_policy"]["status"],
            "PRE_ENTITY_RENAME_SIGNALS_IGNORED",
        )

    def test_post_entity_or_unknown_rename_signal_remains_fail_closed(self):
        for signal in ({"year": 2023}, {"year": None}):
            discovery = {
                "current_legal_name": "주식회사 예시",
                "current_legal_name_active_period": {"start_year": 2022},
                "corporate_restructuring_evidence": [],
                "unresolved_items": [{"code": continuity.BLOCKER}],
            }
            audit = {"stages": {
                "legal_identity": {"resolved": {"establishment_date": "2022-03-02"}},
                "official_site": {"recovery": {"rename_signals": [signal]}},
            }}
            continuity.normalize(discovery, audit)
            self.assertEqual(discovery["unresolved_items"][0]["code"], continuity.BLOCKER)


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
