import unittest
from orchestrator.postprocess import normalize_address, resolve_identity

PROFILE={"company_display_name":"테스트화학","aliases":[{"term":"테스트화학"}],"related_entity_exclusions":[]}


class TestPostprocessIdentity(unittest.TestCase):
    def test_road_address_core_removes_appended_labels(self):
        a=normalize_address("충청남도 서산시 대산읍 독곶1로 54 (주)테스트화학 대산공장",PROFILE)
        b=normalize_address("충남 서산시 대산읍 독곶1로 54",PROFILE)
        self.assertEqual(a,b)

    def test_optional_legal_dong_before_road_is_ignored(self):
        self.assertEqual(
            normalize_address("울산광역시 남구 성암동 처용로 260-257 테스트화학 울산수지공장",PROFILE),
            normalize_address("울산광역시 남구 처용로 260-257",PROFILE),
        )
        self.assertEqual(
            normalize_address("전라남도 여수시 평여동 여수산단3로 118 테스트화학 여수고무공장",PROFILE),
            normalize_address("전라남도 여수시 여수산단3로 118",PROFILE),
        )

    def test_eup_myeon_is_not_removed_from_road_address(self):
        self.assertEqual(
            normalize_address("충청남도 예산군 고덕면 예덕로 1033-9",PROFILE),
            "충남예산군고덕면예덕로10339",
        )

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

    def test_verified_profile_address_confirms_single_source(self):
        profile={**PROFILE,"site_candidates":[{
            "candidate_id":"test-daesan",
            "site_name_raw":"대산공장",
            "address_raw":"충청남도 서산시 대산읍 독곶1로 54",
            "identity_status":"CONFIRMED",
            "verification_state":"VERIFIED",
        }]}
        cs=[
          {"source_key":"PRTR","source_site_id":"1","source_site_name_raw":"테스트화학 대산제1공장","source_address_raw":"충남 서산시 대산읍 독곶1로 54","years":[2024]},
        ]
        _,sites,ids,vals=resolve_identity(cs,profile)
        self.assertEqual(sum(x["identity_status"]=="CONFIRMED" for x in sites),1)
        self.assertEqual(ids[0]["match_status"],"CONFIRMED")
        self.assertEqual(ids[0]["match_basis"],"OFFICIAL_SITE_EXACT_ADDRESS")
        self.assertEqual(vals,[])

    def test_ambiguous_verified_profile_address_does_not_auto_confirm(self):
        profile={**PROFILE,"site_candidates":[
            {"candidate_id":"unit-a","site_name_raw":"A공장","address_raw":"전북 익산시 석암로 99","identity_status":"CONFIRMED","verification_state":"VERIFIED"},
            {"candidate_id":"unit-b","site_name_raw":"B공장","address_raw":"전북 익산시 석암로 99","identity_status":"CONFIRMED","verification_state":"VERIFIED"},
        ]}
        cs=[
          {"source_key":"PRTR","source_site_id":"1","source_site_name_raw":"테스트화학 익산공장","source_address_raw":"전북 익산시 석암로 99","years":[2024]},
        ]
        _,sites,ids,vals=resolve_identity(cs,profile)
        self.assertEqual(ids[0]["match_status"],"REVIEW_REQUIRED")
        self.assertNotEqual(ids[0]["match_basis"],"OFFICIAL_SITE_EXACT_ADDRESS")
        self.assertTrue(any(v["issue_type"]=="COLOCATED_OFFICIAL_UNITS" for v in vals))
        self.assertTrue(any(v["object_key"]=="PRTR:1" for v in vals))

    def test_colocated_units_are_not_flagged_when_both_names_are_cross_source_confirmed(self):
        profile={**PROFILE,"site_candidates":[
            {"candidate_id":"unit-a","site_name_raw":"고무공장","address_raw":"울산 남구 상개로 64","identity_status":"CONFIRMED","verification_state":"VERIFIED"},
            {"candidate_id":"unit-b","site_name_raw":"LATEX공장","address_raw":"울산 남구 상개로 64","identity_status":"CONFIRMED","verification_state":"VERIFIED"},
        ]}
        cs=[
          {"source_key":"PRTR","source_site_id":"1","source_site_name_raw":"테스트화학 고무공장","source_address_raw":"울산 남구 상개로 64","years":[2024]},
          {"source_key":"CHEM_STATS","source_site_id":"A","source_site_name_raw":"테스트화학 고무공장","source_address_raw":"울산 남구 상개로 64","years":[2024]},
          {"source_key":"PRTR","source_site_id":"2","source_site_name_raw":"테스트화학 LATEX공장","source_address_raw":"울산 남구 상개로 64","years":[2024]},
          {"source_key":"CHEM_STATS","source_site_id":"B","source_site_name_raw":"테스트화학 LATEX공장","source_address_raw":"울산 남구 상개로 64","years":[2024]},
        ]
        _,sites,ids,vals=resolve_identity(cs,profile)
        self.assertEqual(sum(x["identity_status"]=="CONFIRMED" for x in sites),2)
        self.assertTrue(all(x["match_status"]=="CONFIRMED" for x in ids))
        self.assertFalse(any(v["issue_type"]=="COLOCATED_OFFICIAL_UNITS" for v in vals))

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

    def test_address_anchored_embedded_facility_alias_bridges_addressless_source(self):
        profile={**PROFILE,"site_candidates":[{
            "candidate_id":"test-cheongju-1",
            "site_name_raw":"청주캠퍼스(대신로)",
            "address_raw":"충북 청주시 흥덕구 대신로 215",
            "identity_status":"CONFIRMED",
            "verification_state":"VERIFIED",
        }]}
        cs=[
          {"source_key":"PRTR","source_site_id":"1","source_site_name_raw":"테스트화학","source_address_raw":"충북 청주시 흥덕구 대신로 215 (향정동)테스트화학 청주1공장","years":[2024]},
          {"source_key":"CLEANSYS_AIR","source_site_id":"100","source_site_name_raw":"테스트화학(주) 청주1공장","source_address_raw":"","years":[2020,2021,2022,2023,2024]},
        ]
        _,_,ids,vals=resolve_identity(cs,profile)
        prtr=[x for x in ids if x["source_key"]=="PRTR"][0]
        air=[x for x in ids if x["source_key"]=="CLEANSYS_AIR"][0]
        self.assertEqual(prtr["match_status"],"CONFIRMED")
        self.assertEqual(air["match_status"],"REVIEW_REQUIRED")
        self.assertEqual(air["match_basis"],"NAME_ONLY_CANDIDATE")
        self.assertEqual(air["canonical_site_id"],prtr["canonical_site_id"])
        self.assertTrue(any(v["object_key"]=="CLEANSYS_AIR:100" for v in vals))


if __name__=="__main__": unittest.main()
