import unittest

from orchestrator.document_route_merge import merge_document_routes, same_verified_entity


class DocumentRouteMergeTest(unittest.TestCase):
    def _company(self, name="금호석유화학(주)", key="00106368"):
        return {
            "current_legal_name": name,
            "identity_evidence": [{
                "source_locator": f"https://englishdart.fss.or.kr/dsbc001/selectPopup.ax?selectKey={key}",
                "verification_state": "VERIFIED",
            }],
        }

    def test_preserves_stronger_previous_primary(self):
        existing = {"documents": [{
            "document_id": "OLD_2025", "document_type": "SUSTAINABILITY_REPORT", "report_year": 2025,
            "source_url": "https://kind.krx.co.kr/stable-2025.pdf",
            "source_locator": "https://kind.krx.co.kr/disclosure-2025.htm",
            "expected_extension": "pdf", "verification_status": "VERIFIED",
            "fallback_sources": [{"source_url": "https://company.example/old.pdf", "verification_status": "SOURCE_VERIFIED", "expected_extension": "pdf"}],
        }]}
        fresh = {"documents": [{
            "document_id": "AUTO_SUSTAINABILITY_2025", "document_type": "SUSTAINABILITY_REPORT", "report_year": 2025,
            "source_url": "https://company.example/new.pdf", "source_locator": "https://company.example/reports",
            "expected_extension": "pdf", "verification_status": "SOURCE_VERIFIED",
        }]}
        result = merge_document_routes(self._company(), existing, self._company(), fresh)
        doc = result["documents"][0]
        self.assertEqual(doc["source_url"], "https://kind.krx.co.kr/stable-2025.pdf")
        self.assertEqual(doc["verification_status"], "VERIFIED")
        self.assertEqual(doc["route_merge_status"], "PRESERVED_STRONGER_PREVIOUS_PRIMARY")
        self.assertEqual(doc["fallback_sources"][0]["source_url"], "https://company.example/new.pdf")
        self.assertIn("https://company.example/old.pdf", [x["source_url"] for x in doc["fallback_sources"]])

    def test_equal_strength_keeps_fresh_primary_and_old_as_fallback(self):
        existing = {"documents": [{"document_type": "SUSTAINABILITY_REPORT", "report_year": 2024, "source_url": "https://old.example/2024.pdf", "verification_status": "VERIFIED"}]}
        fresh = {"documents": [{"document_type": "SUSTAINABILITY_REPORT", "report_year": 2024, "source_url": "https://fresh.example/2024.pdf", "verification_status": "VERIFIED"}]}
        result = merge_document_routes(self._company(), existing, self._company(), fresh)
        self.assertEqual(result["documents"][0]["source_url"], "https://fresh.example/2024.pdf")
        self.assertIn("https://old.example/2024.pdf", [x["source_url"] for x in result["documents"][0]["fallback_sources"]])

    def test_different_entity_never_merges(self):
        existing = {"documents": [{"document_type": "SUSTAINABILITY_REPORT", "report_year": 2025, "source_url": "https://old.example/2025.pdf", "verification_status": "VERIFIED"}]}
        fresh = {"documents": [{"document_type": "SUSTAINABILITY_REPORT", "report_year": 2025, "source_url": "https://fresh.example/2025.pdf", "verification_status": "SOURCE_VERIFIED"}]}
        other = self._company(name="다른회사(주)", key="00999999")
        self.assertFalse(same_verified_entity(self._company(), other))
        self.assertEqual(merge_document_routes(self._company(), existing, other, fresh), fresh)

    def test_restores_strong_old_document_only_for_matching_blocking_gap(self):
        existing = {"documents": [{
            "document_id": "OLD_2021", "document_type": "SUSTAINABILITY_REPORT", "report_year": 2021,
            "source_url": "https://official.example/2021.pdf", "verification_status": "SOURCE_VERIFIED",
            "expected_extension": "pdf",
        }]}
        fresh = {"documents": [], "gaps": [{
            "gap_id": "G2021", "document_type": "SUSTAINABILITY_REPORT", "year": 2021,
            "blocking": True, "status": "DISCOVERY_GAP",
        }], "discovery_status": "PARTIAL"}
        out = merge_document_routes(self._company(), existing, self._company(), fresh)
        self.assertEqual(len(out["documents"]), 1)
        self.assertEqual(out["documents"][0]["route_merge_status"], "RESTORED_PREVIOUS_VERIFIED_DOCUMENT")
        self.assertEqual(out["gaps"], [])
        self.assertEqual(out["discovery_status"], "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE")

    def test_unverified_old_document_does_not_resolve_gap(self):
        existing = {"documents": [{
            "document_type": "SUSTAINABILITY_REPORT", "report_year": 2021,
            "source_url": "https://official.example/2021.pdf", "verification_status": "UNVERIFIED",
        }]}
        fresh = {"documents": [], "gaps": [{"document_type": "SUSTAINABILITY_REPORT", "year": 2021, "blocking": True}], "discovery_status": "PARTIAL"}
        out = merge_document_routes(self._company(), existing, self._company(), fresh)
        self.assertEqual(out["documents"], [])
        self.assertEqual(len(out["gaps"]), 1)

    def test_old_document_is_not_injected_without_matching_fresh_gap(self):
        existing = {"documents": [{
            "document_type": "SUSTAINABILITY_REPORT", "report_year": 2019,
            "source_url": "https://official.example/2019.pdf", "verification_status": "VERIFIED",
        }]}
        fresh = {"documents": [], "gaps": [], "discovery_status": "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE"}
        out = merge_document_routes(self._company(), existing, self._company(), fresh)
        self.assertEqual(out["documents"], [])

    def test_different_entity_old_document_cannot_resolve_matching_gap(self):
        existing = {"documents": [{
            "document_type": "SUSTAINABILITY_REPORT", "report_year": 2021,
            "source_url": "https://official.example/2021.pdf", "verification_status": "VERIFIED",
        }]}
        fresh = {"documents": [], "gaps": [{"document_type": "SUSTAINABILITY_REPORT", "year": 2021, "blocking": True}], "discovery_status": "PARTIAL"}
        other = self._company(name="다른회사(주)", key="00999999")
        out = merge_document_routes(self._company(), existing, other, fresh)
        self.assertEqual(out, fresh)


if __name__ == "__main__":
    unittest.main()
