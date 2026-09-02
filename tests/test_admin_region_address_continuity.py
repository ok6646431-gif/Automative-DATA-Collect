import unittest

from orchestrator.postprocess import normalize_address_locality, resolve_identity


class AdministrativeRegionAddressContinuityTests(unittest.TestCase):
    def profile(self, sites=None):
        return {
            "company_display_name": "에이치디현대삼호 주식회사",
            "aliases": [
                {"term": "에이치디현대삼호 주식회사"},
                {"term": "현대삼호중공업"},
            ],
            "related_entity_exclusions": [],
            "site_candidates": sites or [{
                "candidate_id": "yeongam-yard",
                "site_name_raw": "HD현대삼호 영암 조선소",
                "address_raw": "전남광주통합특별시 영암군 삼호읍 대불로 93",
                "identity_status": "CONFIRMED",
                "verification_state": "VERIFIED",
            }],
        }

    def old_candidates(self):
        return [
            {
                "source_key": "PRTR", "source_site_id": "618",
                "source_site_name_raw": "에이치디현대삼호(주)",
                "source_address_raw": "전라남도 영암군 삼호읍 대불로 93",
                "years": [2024], "raw_ref": "PRTR/discovery.csv",
            },
            {
                "source_key": "CHEM_STATS", "source_site_id": "AFE121N",
                "source_site_name_raw": "현대삼호중공업주식회사",
                "source_address_raw": "전남 영암군 삼호읍 대불로 93",
                "years": [2022, 2024], "raw_ref": "CHEM_STATS/discovery.csv",
            },
        ]

    def test_locality_key_survives_top_level_region_change(self):
        current = normalize_address_locality("전남광주통합특별시 영암군 삼호읍 대불로 93")
        former = normalize_address_locality("전라남도 영암군 삼호읍 대불로 93")
        abbreviated = normalize_address_locality("전남 영암군 삼호읍 대불로 93")
        self.assertEqual(current, former)
        self.assertEqual(current, abbreviated)
        self.assertEqual(current, "영암군삼호읍대불로93")

    def test_two_independent_sources_bridge_verified_admin_region_transition(self):
        _, sites, identities, validations = resolve_identity(self.old_candidates(), self.profile())
        confirmed_sites = [x for x in sites if x["identity_status"] == "CONFIRMED"]
        self.assertEqual(len(confirmed_sites), 1)
        self.assertEqual({x["match_status"] for x in identities}, {"CONFIRMED"})
        self.assertEqual(
            {x["match_basis"] for x in identities},
            {"OFFICIAL_SITE_ADMIN_REGION_TRANSITION_ADDRESS"},
        )
        self.assertFalse([x for x in validations if x.get("object_type") == "SOURCE_IDENTITY"])

    def test_single_source_does_not_auto_bridge_region_transition(self):
        _, _, identities, _ = resolve_identity(self.old_candidates()[:1], self.profile())
        self.assertEqual(len(identities), 1)
        self.assertTrue(identities[0]["review_required"])
        self.assertNotEqual(identities[0]["match_basis"], "OFFICIAL_SITE_ADMIN_REGION_TRANSITION_ADDRESS")

    def test_duplicate_official_locality_fails_closed(self):
        sites = [
            {
                "candidate_id": "a", "site_name_raw": "A 사업장",
                "address_raw": "전남광주통합특별시 중구 중앙로 1",
                "identity_status": "CONFIRMED", "verification_state": "VERIFIED",
            },
            {
                "candidate_id": "b", "site_name_raw": "B 사업장",
                "address_raw": "부산광역시 중구 중앙로 1",
                "identity_status": "CONFIRMED", "verification_state": "VERIFIED",
            },
        ]
        candidates = [
            dict(self.old_candidates()[0], source_address_raw="전라남도 중구 중앙로 1"),
            dict(self.old_candidates()[1], source_address_raw="전남 중구 중앙로 1"),
        ]
        _, _, identities, _ = resolve_identity(candidates, self.profile(sites))
        self.assertNotIn("OFFICIAL_SITE_ADMIN_REGION_TRANSITION_ADDRESS", {x["match_basis"] for x in identities})


if __name__ == "__main__":
    unittest.main()
