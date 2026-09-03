import unittest
from orchestrator.request_builder import build


class TestRequestBuilder(unittest.TestCase):
    def test_predecessor_is_not_scheduled_as_company_alias(self):
        p={
            "request_id":"x","company_display_name":"테스트화학",
            "aliases":[
                {"term":"테스트화학","scope":"current","year_start":2010,"year_end":"auto"},
                {"term":"구테스트","scope":"predecessor","alias_type":"spin_off_predecessor","year_start":2000,"year_end":2016}
            ],
            "source_plan":{
                "ENVINFO":{"start_year":2015,"end_year":2024},
                "PRTR":{"start_year":2015,"end_year":2024},
                "CHEM_STATS":{"years":[2016,2018,2020,2022,2024]},
                "CLEANSYS_AIR":{"start_year":2015,"end_year":2025},
                "SOOSIRO_WATER":{"annual_years":[2019,2020,2021,2022,2023,2024,2025],"daily_years":[2024]}
            }
        }
        r=build(p)
        self.assertNotIn("구테스트",r["sources"]["ENVINFO"]["search_terms"])
        self.assertFalse(any(x["term"]=="구테스트" for x in r["sources"]["PRTR"]["search_terms"]))
        self.assertNotIn("구테스트",r["sources"]["CHEM_STATS"]["search_terms"])
        self.assertNotIn("구테스트",r["sources"]["CLEANSYS_AIR"]["search_terms"])
        self.assertNotIn("구테스트",r["sources"]["SOOSIRO_WATER"]["search_terms"])
        self.assertNotIn("구테스트",r["sources"]["ENVINFO"]["search_terms_by_year"]["2016"])
        self.assertNotIn("구테스트",r["sources"]["CHEM_STATS"]["search_terms_by_year"]["2016"])

    def test_bounded_alias_is_only_scheduled_during_active_period(self):
        p={"request_id":"x","company_display_name":"새회사","aliases":[
                {"term":"새회사","scope":"current","year_start":2020,"year_end":"auto"},
                {"term":"옛회사","scope":"historical","year_start":2017,"year_end":2019}],
           "source_plan":{"ENVINFO":{"start_year":2017,"end_year":2022},
             "PRTR":{"start_year":2017,"end_year":2022},"CHEM_STATS":{"years":[2018,2020,2022]},
             "CLEANSYS_AIR":{"start_year":2017,"end_year":2022},
             "SOOSIRO_WATER":{"annual_years":[2017,2018,2019,2020,2021,2022],"daily_years":[]}}}
        r=build(p)
        self.assertIn("옛회사",r["sources"]["ENVINFO"]["search_terms_by_year"]["2018"])
        self.assertNotIn("옛회사",r["sources"]["ENVINFO"]["search_terms_by_year"]["2022"])
        self.assertNotIn("옛회사",r["sources"]["CHEM_STATS"]["search_terms_by_year"]["2022"])

    def test_disabled_unbounded_alias_is_not_scheduled(self):
        p={"request_id":"x","company_display_name":"새회사","aliases":[
                {"term":"새회사","scope":"current","year_start":2020,"year_end":"auto"},
                {"term":"기간미상","scope":"historical","year_start":0,"year_end":"auto","search_enabled":False}],
           "source_plan":{"ENVINFO":{"start_year":2020,"end_year":2024},
             "PRTR":{"start_year":2020,"end_year":2024},"CHEM_STATS":{"years":[2020,2022,2024]},
             "CLEANSYS_AIR":{"start_year":2020,"end_year":2024},
             "SOOSIRO_WATER":{"annual_years":[2020,2021,2022,2023,2024],"daily_years":[]}}}
        r=build(p)
        self.assertNotIn("기간미상",r["sources"]["ENVINFO"]["search_terms"])
        self.assertFalse(any(x["term"] == "기간미상" for x in r["sources"]["PRTR"]["search_terms"]))

    def test_only_verified_confirmed_site_addresses_are_passed_to_tms(self):
        p={"request_id":"x","company_display_name":"새회사","aliases":[{"term":"새회사","scope":"current","year_start":2020,"year_end":"auto"}],
           "site_candidates":[
             {"site_name_raw":"A공장","address_raw":"충북 청주시 테스트로 1","identity_status":"CONFIRMED","verification_state":"VERIFIED"},
             {"site_name_raw":"B공장","address_raw":"충북 청주시 테스트로 2","identity_status":"CANDIDATE","verification_state":"VERIFIED"},
             {"site_name_raw":"C공장","address_raw":"충북 청주시 테스트로 3","identity_status":"CONFIRMED","verification_state":"UNVERIFIED"}],
           "source_plan":{"ENVINFO":{"start_year":2020,"end_year":2024},"PRTR":{"start_year":2020,"end_year":2024},"CHEM_STATS":{"years":[2020,2022,2024]},"CLEANSYS_AIR":{"start_year":2020,"end_year":2024},"SOOSIRO_WATER":{"annual_years":[2020,2021,2022,2023,2024],"daily_years":[]}}}
        r=build(p)
        expected=["충북 청주시 테스트로 1"]
        self.assertEqual(r["sources"]["CLEANSYS_AIR"]["site_addresses"],expected)
        self.assertEqual(r["sources"]["SOOSIRO_WATER"]["site_addresses"],expected)

    def test_verified_korean_legal_names_expand_source_native_legal_forms_with_same_bounds(self):
        p={"request_id":"hd","company_display_name":"에이치디현대삼호 주식회사","aliases":[
             {"term":"에이치디현대삼호 주식회사","scope":"current","alias_type":"current_legal_name","year_start":2024,"year_end":"auto"},
             {"term":"HD현대삼호","scope":"current","alias_type":"requested_name","year_start":2024,"year_end":"auto"},
             {"term":"HD HYUNDAI SAMHO CO., LTD.","scope":"current","alias_type":"english_legal_name","year_start":2024,"year_end":"auto"},
             {"term":"현대삼호중공업","scope":"historical","alias_type":"former_legal_name","year_start":2020,"year_end":2024}],
           "source_plan":{"ENVINFO":{"start_year":2020,"end_year":2024},"PRTR":{"start_year":2020,"end_year":2024},"CHEM_STATS":{"years":[2020,2022,2024]},"CLEANSYS_AIR":{"start_year":2020,"end_year":2025},"SOOSIRO_WATER":{"annual_years":[2020,2021,2022,2023,2024,2025],"daily_years":[2024]}}}
        r=build(p)
        chem=r["sources"]["CHEM_STATS"]["search_terms_by_year"]
        self.assertIn("현대삼호중공업(주)",chem["2020"])
        self.assertNotIn("에이치디현대삼호(주)",chem["2020"])
        self.assertIn("현대삼호중공업(주)",chem["2024"])
        self.assertIn("에이치디현대삼호(주)",chem["2024"])
        self.assertNotIn("HD현대삼호(주)",chem["2024"])
        self.assertIn("HD HYUNDAI SAMHO CO., LTD.",chem["2024"])

        pr={x["term"]:(x["year_start"],x["year_end"]) for x in r["sources"]["PRTR"]["search_terms"]}
        self.assertEqual(pr["현대삼호중공업(주)"],(2020,2024))
        self.assertEqual(pr["에이치디현대삼호(주)"],(2024,2024))
        self.assertNotIn("HD현대삼호(주)",pr)

        air=r["sources"]["CLEANSYS_AIR"]
        self.assertIn("에이치디현대삼호(주)",air["search_terms_by_year"]["2025"])
        self.assertNotIn("현대삼호중공업(주)",air["search_terms_by_year"]["2025"])


if __name__=="__main__": unittest.main()
