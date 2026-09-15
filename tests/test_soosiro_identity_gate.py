import unittest

from collectors.soosiro_collect import source_name_scope_decision


GATE = {
    "enabled": True,
    "current_entity_names": ["주식회사 포스코"],
    "verified_sites": [
        {"site_name": "포항제철소", "address": "경상북도 포항시 남구 동해안로 6262"},
        {"site_name": "광양제철소", "address": "전라남도 광양시 폭포사랑길 20-26"},
    ],
}


class SoosiroIdentityGateTest(unittest.TestCase):
    def test_duplicate_alternative_names_do_not_break_location_alias(self):
        row = {
            "FACT_NAME": "포스코(포항)",
            "FACT_FNAME": "포스코(포항)",
            "FACT_ADDR": "경북 포항시 남구 동촌동 (주)포스코",
        }
        result = source_name_scope_decision(row, GATE)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["decision"], "ALLOW_CURRENT_ENTITY_LOCATION_ALIAS")
        self.assertEqual(result["matched_name_field"], "FACT_NAME")

    def test_second_alternative_name_can_admit_candidate(self):
        row = {
            "FACT_NAME": "",
            "FACT_FNAME": "포스코(광양)",
            "FACT_ADDR": "전남 광양시",
        }
        result = source_name_scope_decision(row, GATE)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["matched_name_field"], "FACT_FNAME")

    def test_affiliate_remains_rejected_even_at_current_site_address(self):
        row = {
            "FACT_NAME": "포스코퓨처엠(포항)",
            "FACT_FNAME": "(주)포스코퓨처엠 포항화학사업부",
            "FACT_ADDR": "경상북도 포항시 남구 동해안로 6262",
        }
        result = source_name_scope_decision(row, GATE)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["decision"], "REJECT_ADDRESS_ONLY")


if __name__ == "__main__":
    unittest.main()
