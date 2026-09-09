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
        existing = {
            "documents": [{
                "document_id": "OLD_2025",
                "document_type": "SUSTAINABILITY_REPORT",
                "report_year": 2025,
                "source_url": "https://kind.krx.co.kr/stable-2025.pdf",
                "source_locator": "https://kind.krx.co.kr/disclosure-2025.htm",
                "expected_extension": "pdf",
                "verification_status": "VERIFIED",
                "fallback_sources": [{
                    "source_url": "https://company.example/old.pdf",
                    "verification_status": "SOURCE_VERIFIED",
                    "expected_extension": "pdf",
                }],
            }]
        }
        fresh = {
            "documents": [{
                "document_id": "AUTO_SUSTAINABILITY_2025",
                "document_type": "SUSTAINABILITY_REPORT",
                "report_year": 2025,
                "source_url": "https://company.example/new.pdf",
                "source_locator": "https://company.example/reports",
                "expected_extension": "pdf",
                "verification_status": "SOURCE_VERIFIED",
            }]
        }
        result = merge_document_routes(self._company(), existing, self._company(), fresh)
        doc = result["documents"][0]
        self.assertEqual(doc["source_url"], "https://kind.krx.co.kr/stable-2025.pdf")
        self.assertEqual(doc["verification_status"], "VERIFIED")
        self.assertEqual(doc["route_merge_status"], "PRESERVED_STRONGER_PREVIOUS_PRIMARY")
        fallbacks = [x["source_url"] for x in doc["fallback_sources"]]
        self.assertEqual(fallbacks[0], "https://company.example/new.pdf")
        self.assertIn("https://company.example/old.pdf", fallbacks)

    def test_equal_strength_keeps_fresh_primary_and_old_as_fallback(self):
        existing = {"documents": [{
            "document_type": "SUSTAINABILITY_REPORT", "report_year": 2024,
            "source_url": "https://old.example/2024.pdf", "verification_status": "VERIFIED",
        }]}
        fresh = {"documents": [{
            "document_type": "SUSTAINABILITY_REPORT", "report_year": 2024,
            "source_url": "https://fresh.example/2024.pdf", "verification_status": "VERIFIED",
        }]}
        result = merge_document_routes(self._company(), existing, self._company(), fresh)
        doc = result["documents"][0]
        self.assertEqual(doc["source_url"], "https://fresh.example/2024.pdf")
        self.assertIn("https://old.example/2024.pdf", [x["source_url"] for x in doc["fallback_sources"]])

    def test_different_entity_never_merges(self):
        existing = {"documents": [{
            "document_type": "SUSTAINABILITY_REPORT", "report_year": 2025,
            "source_url": "https://old.example/2025.pdf", "verification_status": "VERIFIED",
        }]}
        fresh = {"documents": [{
            "document_type": "SUSTAINABILITY_REPORT", "report_year": 2025,
            "source_url": "https://fresh.example/2025.pdf", "verification_status": "SOURCE_VERIFIED",
        }]}
        other = self._company(name="다른회사(주)", key="00999999")
        self.assertFalse(same_verified_entity(self._company(), other))
        result = merge_document_routes(self._company(), existing, other, fresh)
        self.assertEqual(result, fresh)


if __name__ == "__main__":
    unittest.main()
