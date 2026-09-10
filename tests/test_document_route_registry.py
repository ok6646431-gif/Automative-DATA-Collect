import unittest

from orchestrator.document_route_registry import empty_registry, entity_key, merge_from_registry, update_registry


class DocumentRouteRegistryTests(unittest.TestCase):
    def _company(self, name="예시화학(주)", key="00112233"):
        return {
            "current_legal_name": name,
            "requested_company_name": name,
            "identity_evidence": [{
                "source_locator": f"https://englishdart.fss.or.kr/dsbc001/selectPopup.ax?selectKey={key}",
                "verification_state": "VERIFIED",
            }],
        }

    def test_entity_key_requires_one_verified_dart_key(self):
        self.assertEqual(entity_key(self._company()), "00112233")
        self.assertEqual(entity_key({"current_legal_name": "예시"}), "")

    def test_company_switch_keeps_independent_entities(self):
        registry = empty_registry()
        a = self._company("A화학(주)", "00111111")
        b = self._company("B소재(주)", "00222222")
        registry = update_registry(registry, a, {"documents": [], "gaps": []})
        registry = update_registry(registry, b, {"documents": [], "gaps": []})
        self.assertEqual(set(registry["entities"]), {"00111111", "00222222"})
        self.assertEqual(registry["entities"]["00111111"]["current_legal_name"], "A화학(주)")

    def test_registry_restores_matching_verified_document_after_company_switch(self):
        company = self._company()
        stored = {"documents": [{
            "document_id": "OLD2020", "document_type": "SUSTAINABILITY_REPORT", "report_year": 2020,
            "source_url": "https://official.example/report2020.pdf", "verification_status": "VERIFIED",
            "expected_extension": "pdf",
        }], "gaps": []}
        registry = update_registry(empty_registry(), company, stored)
        fresh = {"documents": [], "gaps": [{
            "document_type": "SUSTAINABILITY_REPORT", "year": 2020,
            "blocking": True, "status": "DISCOVERY_GAP",
        }], "discovery_status": "PARTIAL"}
        merged, info = merge_from_registry(registry, company, fresh)
        self.assertEqual(info["status"], "APPLIED")
        self.assertEqual(info["restored_documents"], 1)
        self.assertEqual(merged["documents"][0]["source_url"], "https://official.example/report2020.pdf")
        self.assertEqual(merged["gaps"], [])

    def test_registry_never_crosses_dart_entities(self):
        a = self._company("A화학(주)", "00111111")
        b = self._company("B화학(주)", "00222222")
        registry = update_registry(empty_registry(), a, {"documents": [{
            "document_type": "SUSTAINABILITY_REPORT", "report_year": 2020,
            "source_url": "https://a.example/2020.pdf", "verification_status": "VERIFIED",
        }], "gaps": []})
        fresh = {"documents": [], "gaps": [{"document_type": "SUSTAINABILITY_REPORT", "year": 2020, "blocking": True}], "discovery_status": "PARTIAL"}
        merged, info = merge_from_registry(registry, b, fresh)
        self.assertEqual(info["status"], "NO_MATCH")
        self.assertEqual(merged, fresh)

    def test_registry_update_does_not_weaken_stronger_old_primary(self):
        company = self._company()
        registry = update_registry(empty_registry(), company, {"documents": [{
            "document_type": "SUSTAINABILITY_REPORT", "report_year": 2025,
            "source_url": "https://kind.example/verified.pdf", "verification_status": "VERIFIED",
        }], "gaps": []})
        registry = update_registry(registry, company, {"documents": [{
            "document_type": "SUSTAINABILITY_REPORT", "report_year": 2025,
            "source_url": "https://company.example/source.pdf", "verification_status": "SOURCE_VERIFIED",
        }], "gaps": []})
        doc = registry["entities"]["00112233"]["document_evidence"]["documents"][0]
        self.assertEqual(doc["source_url"], "https://kind.example/verified.pdf")
        self.assertEqual(doc["verification_status"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
