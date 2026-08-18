import unittest
from orchestrator.postprocess import normalize_address, resolve_identity

PROFILE={"company_display_name":"테스트화학","aliases":[{"term":"테스트화학"}],"related_entity_exclusions":[]}


class TestPostprocessIdentity(unittest.TestCase):
    def test_road_address_core_removes_appended_labels(self):
        a=normalize_address("충청남도 서산시 대산읍 독곶1로 54 (주)테스트화학 대산공장",PROFILE)
        b=normalize_address("충남 서산시 대산읍 독곶1로 54",PROFILE)
        self.assertEqual(a,b)

    def test_same_address_different_unit_not_auto_merged(self):
        cs=[
          {"source_key":"PRTR","source_site_id":"1","source_site_name_raw":"테스트화학 익산공장","source_address_raw":"전북 익산시 석암로 99","years":[2024]},
          {"source_key":"CHEM_STATS","source_site_id":"A","source_site_name_raw":"테스트화학 익산공장(EP)","source_address_raw":"전라북도 익산시 석암로 99","years":[2024]},
        ]
        _,sites,ids,vals=resolve_identity(cs,PROFILE)
        self.assertEqual(sum(x["identity_status"]=="CONFIRMED" for x in sites),0)
        self.assertTrue(all(x["match_status"]=="REVIEW_REQUIRED" for x in ids))
        self.assertEqual(len(vals),2)

    def test_exact_address_and_site_label_cross_source_confirms(self):
        cs=[
          {"source_key":"PRTR","source_site_id":"1","source_site_name_raw":"(주)테스트화학 대산공장","source_address_raw":"충남 서산시 대산읍 독곶1로 54","years":[2024]},
          {"source_key":"CHEM_STATS","source_site_id":"A","source_site_name_raw":"테스트화학 대산공장","source_address_raw":"충청남도 서산시 대산읍 독곶1로 54 테스트화학 대산공장","years":[2024]},
        ]
        _,sites,ids,vals=resolve_identity(cs,PROFILE)
        self.assertEqual(sum(x["identity_status"]=="CONFIRMED" for x in sites),1)
        self.assertTrue(all(x["match_status"]=="CONFIRMED" for x in ids))
        self.assertEqual(vals,[])

    def test_name_only_stays_review_required(self):
        cs=[
          {"source_key":"PRTR","source_site_id":"1","source_site_name_raw":"테스트화학 대산공장","source_address_raw":"충남 서산시 대산읍 독곶1로 54","years":[2024]},
          {"source_key":"CHEM_STATS","source_site_id":"A","source_site_name_raw":"테스트화학 대산공장","source_address_raw":"충남 서산시 대산읍 독곶1로 54","years":[2024]},
          {"source_key":"CLEANSYS_AIR","source_site_id":"100","source_site_name_raw":"테스트화학 대산공장","source_address_raw":"","years":[2020,2021,2022,2023,2024]},
        ]
        _,_,ids,_=resolve_identity(cs,PROFILE)
        air=[x for x in ids if x["source_key"]=="CLEANSYS_AIR"][0]
        self.assertEqual(air["match_status"],"REVIEW_REQUIRED")
        self.assertEqual(air["match_basis"],"NAME_ONLY_CANDIDATE")


if __name__=="__main__": unittest.main()
