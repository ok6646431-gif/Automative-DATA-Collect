import unittest

from collectors.cleansys_collect import term_matches_option
from collectors.soosiro_collect import normalize_address, address_seed_candidates


class TestTmsDiscovery(unittest.TestCase):
    def test_cleansys_legal_form_difference_matches(self):
        self.assertTrue(term_matches_option("에스케이하이닉스 주식회사", "에스케이하이닉스㈜ 청주1공장"))
        self.assertTrue(term_matches_option("테스트화학 주식회사", "(주)테스트화학 대산공장"))

    def test_cleansys_unrelated_embedded_customer_name_does_not_match(self):
        self.assertFalse(term_matches_option("SK하이닉스", "SK에너지㈜하이닉스 이천지점"))

    def test_soosiro_address_core_ignores_province_spelling_and_postal_annotation(self):
        a=normalize_address("충청북도 청주시 흥덕구 에스케이로 120")
        b=normalize_address("충북 청주시 흥덕구 에스케이로 120 (우 28356)")
        self.assertEqual(a,b)

    def test_soosiro_exact_verified_address_seeds_unique_fact(self):
        facts=[
            {"FACT_CODE":"A","FACT_NAME":"원천명칭A","FACT_ADDR":"충북 청주시 흥덕구 2순환로 959"},
            {"FACT_CODE":"B","FACT_NAME":"다른시설","FACT_ADDR":"충북 청주시 흥덕구 다른로 1"},
        ]
        hits=address_seed_candidates(facts,["충청북도 청주시 흥덕구 2순환로 959"])
        self.assertEqual([x["FACT_CODE"] for x in hits],["A"])

    def test_soosiro_ambiguous_same_address_is_not_seeded(self):
        facts=[
            {"FACT_CODE":"A","FACT_NAME":"A시설","FACT_ADDR":"충북 청주시 흥덕구 테스트로 1"},
            {"FACT_CODE":"B","FACT_NAME":"B시설","FACT_ADDR":"충북 청주시 흥덕구 테스트로 1"},
        ]
        self.assertEqual(address_seed_candidates(facts,["충북 청주시 흥덕구 테스트로 1"]),[])


if __name__=="__main__": unittest.main()
