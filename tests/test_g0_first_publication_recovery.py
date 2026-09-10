import unittest

from orchestrator.g0_first_publication_recovery import apply_verified_claim


class FirstPublicationRecoveryTests(unittest.TestCase):
    def _documents(self):
        return {
            "discovery_status": "PARTIAL",
            "documents": [
                {
                    "document_type": "SUSTAINABILITY_REPORT",
                    "report_year": 2021,
                    "verification_status": "SOURCE_VERIFIED",
                },
                {
                    "document_type": "SUSTAINABILITY_REPORT",
                    "report_year": 2022,
                    "verification_status": "SOURCE_VERIFIED",
                },
            ],
            "gaps": [
                {
                    "gap_id": "AUTO_SUSTAINABILITY_2020_UNRESOLVED",
                    "document_type": "SUSTAINABILITY_REPORT",
                    "year": 2020,
                    "status": "DISCOVERY_GAP",
                    "verification_status": "UNVERIFIED",
                    "blocking": True,
                }
            ],
        }

    def test_verified_first_year_resolves_only_prepublication_prefix(self):
        docs = self._documents()
        resolved = apply_verified_claim({}, docs, {
            "first_report_year": 2021,
            "source_url": "https://official.example/news/first-report",
        })
        self.assertEqual(resolved, [2020])
        gap = docs["gaps"][0]
        self.assertEqual(gap["status"], "NOT_PUBLISHED")
        self.assertEqual(gap["verification_status"], "SOURCE_VERIFIED")
        self.assertFalse(gap["blocking"])
        self.assertEqual(docs["discovery_status"], "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE")

    def test_claim_year_must_match_earliest_verified_report_file(self):
        docs = self._documents()
        resolved = apply_verified_claim({}, docs, {
            "first_report_year": 2022,
            "source_url": "https://official.example/news/claim",
        })
        self.assertEqual(resolved, [])
        self.assertTrue(docs["gaps"][0]["blocking"])

    def test_later_gap_is_never_erased_by_first_publication_claim(self):
        docs = self._documents()
        docs["gaps"].append({
            "gap_id": "AUTO_SUSTAINABILITY_2023_UNRESOLVED",
            "document_type": "SUSTAINABILITY_REPORT",
            "year": 2023,
            "status": "DISCOVERY_GAP",
            "verification_status": "UNVERIFIED",
            "blocking": True,
        })
        resolved = apply_verified_claim({}, docs, {
            "first_report_year": 2021,
            "source_url": "https://official.example/news/first-report",
        })
        self.assertEqual(resolved, [2020])
        self.assertTrue(docs["gaps"][1]["blocking"])
        self.assertEqual(docs["discovery_status"], "PARTIAL")


if __name__ == "__main__":
    unittest.main()
