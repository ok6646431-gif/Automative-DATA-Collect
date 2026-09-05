import unittest

from orchestrator import g0_promotion_policy as policy


class G0PromotionPolicyTests(unittest.TestCase):
    def test_document_coverage_gap_is_deferred_not_promotion_blocking(self):
        discovery = {
            "unresolved_items": [{
                "code": "CORPORATE_DOCUMENT_COVERAGE_INCOMPLETE",
                "subject": "테스트",
                "detail": "1 annual report gap remains",
            }]
        }
        documents = {
            "gaps": [{
                "gap_id": "G2025",
                "document_type": "SUSTAINABILITY_REPORT",
                "year": 2025,
                "blocking": True,
            }]
        }
        audit = {"gate_status": "REVIEW_REQUIRED"}
        d, docs, a = policy.apply(discovery, documents, audit)
        self.assertEqual(d["unresolved_items"], [])
        self.assertEqual(len(docs["gaps"]), 1)
        self.assertEqual(a["gate_status"], "PASS")
        stage = a["stages"]["promotion_policy"]
        self.assertEqual(stage["deferred_review_count"], 1)
        self.assertEqual(stage["document_blocking_gap_count"], 1)

    def test_identity_ambiguity_remains_fail_closed(self):
        discovery = {
            "unresolved_items": [
                {"code": "CORPORATE_DOCUMENT_COVERAGE_INCOMPLETE"},
                {"code": "LEGAL_ENTITY_AMBIGUOUS", "detail": "two candidates"},
            ]
        }
        d, _, a = policy.apply(discovery, {"gaps": []}, {})
        self.assertEqual([x["code"] for x in d["unresolved_items"]], ["LEGAL_ENTITY_AMBIGUOUS"])
        self.assertEqual(a["gate_status"], "REVIEW_REQUIRED")
        self.assertEqual(a["stages"]["promotion_policy"]["deferred_review_count"], 1)


if __name__ == "__main__":
    unittest.main()
