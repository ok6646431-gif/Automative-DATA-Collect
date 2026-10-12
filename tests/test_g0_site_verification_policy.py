import copy
import unittest

from orchestrator import g0_promotion_policy
from orchestrator import g0_site_verification_policy as policy
from orchestrator import g0_domestic_site_catalog as catalog
from orchestrator import g0_domestic_site_catalog_enrichment as enrichment
from orchestrator.zero_touch_discovery import Page


class G0SiteVerificationPolicyTests(unittest.TestCase):
    def _make(self, contract):
        return {
            "candidate_id": "site-a",
            "site_name_raw": "고객과 공장",
            "address_raw": "대구광역시 달성군 논공읍 논공로 53",
            "source_locator": "https://official.example/domestic",
            "identity_status": "CONFIRMED",
            "verification_state": "VERIFIED",
            "discovery_evidence": {
                "evidence_type": "EXPLICIT_DOMESTIC_SITE_CATALOG",
                "extraction_contract": contract,
            },
        }

    def test_flattened_evidence_cannot_become_verified(self):
        discovery = {"domestic_site_candidates": [self._make("FLATTENED_TEXT_FALLBACK")],
                     "unresolved_items": []}
        audit = {}
        policy.normalize(discovery, audit)
        candidate = discovery["domestic_site_candidates"][0]
        self.assertEqual("CANDIDATE", candidate["identity_status"])
        self.assertEqual("UNVERIFIED", candidate["verification_state"])
        self.assertEqual("SITE_IDENTITY_UNRESOLVED", discovery["unresolved_items"][0]["code"])
        self.assertEqual(1, audit["stages"]["site_verification_policy"]["downgraded_candidate_count"])
        _, _, result = g0_promotion_policy.apply(discovery, {"gaps": []}, audit)
        self.assertEqual("REVIEW_REQUIRED", result["gate_status"])

    def test_multiple_flat_site_candidates_are_never_source_verified(self):
        page = Page(
            "https://official.example/company/domestic",
            ("국내사업장 고객과 공장 대구광역시 달성군 논공읍 논공로 53 "
             "서울사무소 서울특별시 중구 세종대로 100"),
            "", 200)
        discovered = catalog.discover("이수페타시스", [page])
        self.assertIsNotNone(discovered)
        sites, scope, _ = discovered
        self.assertEqual("SITE_SET", scope["mode"])
        discovery = {"domestic_site_candidates": sites, "unresolved_items": []}
        policy.normalize(discovery, {})
        self.assertTrue(all(s["verification_state"] == "UNVERIFIED" for s in sites))
        self.assertEqual(len(sites), len(discovery["unresolved_items"]))

    def test_weak_name_from_location_page_is_not_verified(self):
        discovered, scope, _ = enrichment._materialize_site_set(
            "예시회사",
            {"a": {"name": "대구 공장", "address": "대구광역시 달성군 논공읍 논공로 53",
                   "source_locator": "https://official.example/location",
                   "extraction_contract": "LOCATION_PAGE_NEAREST_OPERATIONAL_NAME"}},
            "MULTI_PAGE_OFFICIAL_LOCATION_NAVIGATION",
        )
        discovery = {"domestic_site_candidates": discovered, "unresolved_items": []}
        policy.normalize(discovery, {})
        self.assertEqual("CANDIDATE", discovered[0]["identity_status"])

    def test_structured_and_external_verification_are_preserved(self):
        for contract in ("STRUCTURED_DOM_NAME_ADDRESS_PAIR",
                         "STRUCTURED_PRODUCTION_TABLE_NAME_ADDRESS_PAIR",
                         "SEMANTIC_HEADING_ADDRESS_PAIR", None):
            with self.subTest(contract=contract):
                site = self._make(contract)
                original = copy.deepcopy(site)
                discovery = {"domestic_site_candidates": [site], "unresolved_items": []}
                audit = {}
                policy.normalize(discovery, audit)
                self.assertEqual(original, site)
                self.assertEqual([], discovery["unresolved_items"])
                self.assertEqual(0, audit["stages"]["site_verification_policy"]["downgraded_candidate_count"])

    def test_normalization_is_idempotent(self):
        discovery = {"domestic_site_candidates": [self._make("FLATTENED_TEXT_FALLBACK")],
                     "unresolved_items": []}
        policy.normalize(discovery, {})
        policy.normalize(discovery, {})
        self.assertEqual(1, len(discovery["unresolved_items"]))


if __name__ == "__main__":
    unittest.main()
