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

    def test_group_affiliate_prefix_is_rejected(self):
        for name in ["포스코퓨처엠", "포스코홀딩스 주식회사", "포스코인터내셔널", "포스코이앤씨"]:
            with self.subTest(name=name):
                result = evaluate_candidate(name, "", GATE)
                self.assertFalse(result["allowed"])
                self.assertEqual(result["decision"], "REJECT_UNVERIFIED_ENTITY")

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
