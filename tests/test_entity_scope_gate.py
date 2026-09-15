import unittest

from collectors.entity_scope_gate import evaluate_candidate


GATE = {
    "enabled": True,
    "mode": "VERIFIED_CURRENT_ENTITY_OR_SITE",
    "current_entity_names": ["주식회사 포스코"],
    "verified_sites": [
        {"site_name": "포항제철소", "address": "경상북도 포항시 남구 동해안로 6262"},
        {"site_name": "광양제철소", "address": "전라남도 광양시 폭포사랑길 20-26"},
    ],
    "address_only_is_sufficient": False,
}

KUMHO_GATE = {
    "enabled": True,
    "mode": "VERIFIED_CURRENT_ENTITY_OR_SITE",
    "current_entity_names": ["금호석유화학(주)"],
    "verified_sites": [
        {"site_name": "율촌CNT공장", "address": "전남 여수시 율촌면 율촌산단6로 115"},
        {"site_name": "울산고무공장", "address": "울산광역시 남구 상개로 64"},
    ],
}

HANWHA_GATE = {
    "enabled": True,
    "mode": "VERIFIED_CURRENT_ENTITY_OR_SITE",
    "current_entity_names": ["한화에어로스페이스(주)"],
    "verified_sites": [
        {"site_name": "서울 본사", "address": "서울특별시 중구 청계천로 86"},
        {"site_name": "창원 1사업장/한국사업장", "address": "경남 창원시 성산구 창원대로 1204"},
        {"site_name": "창원 3사업장/R&D 캠퍼스", "address": "경남 창원시 성산구 공단로 69"},
    ],
}

HYOSUNG_GATE = {
    "enabled": True,
    "mode": "VERIFIED_CURRENT_ENTITY_OR_SITE",
    "current_entity_names": ["효성티앤씨(주)"],
    "verified_sites": [
        {"site_name": "나이론폴리에스터 울산공장", "address": "울산시 남구 납도로 30"},
    ],
}


class EntityScopeGateTest(unittest.TestCase):
    def test_exact_current_legal_entity_allowed(self):
        result = evaluate_candidate("포스코 주식회사", "", GATE)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["decision"], "ALLOW_CURRENT_ENTITY_NAME")

    def test_verified_site_source_label_allowed(self):
        result = evaluate_candidate("포스코(주) 광양제철소", "전남 광양시 폭포사랑길 20-26", GATE)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["decision"], "ALLOW_CURRENT_ENTITY_SITE")

    def test_site_only_label_allowed(self):
        result = evaluate_candidate("포항제철소", "경상북도 포항시 남구 동해안로 6262", GATE)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["decision"], "ALLOW_VERIFIED_SITE_NAME")

    def test_verified_location_alias_allowed(self):
        for name, token in [("포스코(포항)", "포항"), ("포스코(광양)", "광양")]:
            with self.subTest(name=name):
                result = evaluate_candidate(name, "", GATE)
                self.assertTrue(result["allowed"])
                self.assertEqual(result["decision"], "ALLOW_CURRENT_ENTITY_VERIFIED_SITE_ALIAS")
                self.assertIn(token, result["reason"])

    def test_location_alias_must_be_exact_suffix(self):
        for name in ["포스코포항테크", "포스코광양서비스"]:
            with self.subTest(name=name):
                result = evaluate_candidate(name, "", GATE)
                self.assertFalse(result["allowed"])

    def test_verified_site_role_omission_handles_alphanumeric_site_stem(self):
        result = evaluate_candidate("금호석유화학 율촌CNT", "", KUMHO_GATE)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["decision"], "ALLOW_CURRENT_ENTITY_VERIFIED_SITE_ALIAS")

    def test_composite_verified_site_can_use_explicit_catalog_segment(self):
        result = evaluate_candidate("한화에어로스페이스(주) 창원3사업장", "", HANWHA_GATE)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["decision"], "ALLOW_CURRENT_ENTITY_VERIFIED_SITE_ALIAS")

    def test_unique_headquarters_role_alias_allowed(self):
        result = evaluate_candidate("한화에어로스페이스(주) 본사", "", HANWHA_GATE)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["decision"], "ALLOW_CURRENT_ENTITY_UNIQUE_ROLE_ALIAS")

    def test_hyosung_source_native_locality_aliases_remain_allowed(self):
        for name in ["효성티앤씨(울산)", "효성티앤씨 울산공장"]:
            with self.subTest(name=name):
                result = evaluate_candidate(name, "", HYOSUNG_GATE)
                self.assertTrue(result["allowed"])
                self.assertIn(result["decision"], {
                    "ALLOW_CURRENT_ENTITY_LOCATION_ALIAS",
                    "ALLOW_CURRENT_ENTITY_LOCATION_ROLE_ALIAS",
                })

    def test_unverified_site_name_after_exact_entity_is_rejected(self):
        result = evaluate_candidate("금호석유화학 화성단열재", "", KUMHO_GATE)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["decision"], "REJECT_UNVERIFIED_ENTITY")

    def test_group_affiliate_prefix_is_rejected(self):
        for name in ["포스코퓨처엠", "포스코홀딩스 주식회사", "포스코인터내셔널", "포스코이앤씨"]:
            with self.subTest(name=name):
                result = evaluate_candidate(name, "", GATE)
                self.assertFalse(result["allowed"])
                self.assertEqual(result["decision"], "REJECT_UNVERIFIED_ENTITY")

    def test_group_affiliate_at_verified_address_is_still_rejected(self):
        result = evaluate_candidate(
            "(주)포스코퓨처엠 포항화학사업부",
            "경상북도 포항시 남구 동해안로 6262",
            GATE,
        )
        self.assertFalse(result["allowed"])
        self.assertEqual(result["decision"], "REJECT_ADDRESS_ONLY")

    def test_address_alone_does_not_override_name_identity(self):
        result = evaluate_candidate("별도법인", "경상북도 포항시 남구 동해안로 6262", GATE)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["decision"], "REJECT_ADDRESS_ONLY")

    def test_no_gate_keeps_legacy_compatibility(self):
        result = evaluate_candidate("어떤회사", "", None)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["decision"], "ALLOW_LEGACY_NO_GATE")


if __name__ == "__main__":
    unittest.main()
