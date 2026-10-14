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

    def test_dart_prefixed_korean_legal_name_does_not_generate_double_markers(self):
        from orchestrator.request_builder import query_terms_for_alias
        expected = {
            "이수페타시스", "이수페타시스(주)", "이수페타시스㈜",
            "주식회사 이수페타시스", "이수페타시스 주식회사",
        }
        for original in ("(주)이수페타시스", "㈜이수페타시스",
                         "주식회사 이수페타시스", "이수페타시스(주)",
                         "이수페타시스 주식회사"):
            with self.subTest(original=original):
                actual = set(query_terms_for_alias({
                    "term": original, "alias_type": "current_legal_name",
                }))
                self.assertTrue(expected.issubset(actual))
                self.assertFalse(any("(주)이수페타시스(주)" in x for x in actual))
                self.assertFalse(any("주식회사 (주)" in x for x in actual))
                self.assertFalse(any("㈜이수페타시스(주)" in x for x in actual))

    def test_non_legal_or_english_alias_is_not_synthetically_expanded(self):
        from orchestrator.request_builder import query_terms_for_alias
        for raw, kind in (("(주)이수페타시스", "requested_name"),
                          ("ISUPETASYS CO.,LTD", "english_legal_name")):
            self.assertEqual([raw], query_terms_for_alias({"term": raw, "alias_type": kind}))

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

    def test_prtr_anchors_use_only_g0_verified_sites(self):
        p={"request_id":"so", "company_display_name":"S-OIL(주)",
           "aliases":[{"term":"S-OIL(주)", "scope":"current", "year_start":2020,"year_end":"auto"}],
           "site_candidates":[
             {"site_name_raw":"온산공장","address_raw":"울산광역시 울주군 온산읍 온산로 68",
              "verification_state":"VERIFIED","identity_status":"CONFIRMED"},
             {"site_name_raw":"계열사","address_raw":"울산광역시 울주군 온산읍 산업로 999",
              "verification_state":"UNVERIFIED","identity_status":"CANDIDATE"}],
           "site_address_anchors":{"공식공장ID":["울산광역시 울주군 온산읍 온산로 68"],
                                   "잘못된후보":["울산광역시 울주군 온산읍 산업로 999"]},
           "source_plan":{"ENVINFO":{"start_year":2020,"end_year":2024},
             "PRTR":{"start_year":2020,"end_year":2024},
             "CHEM_STATS":{"years":[2020,2022,2024]},
             "CLEANSYS_AIR":{"start_year":2020,"end_year":2025},
             "SOOSIRO_WATER":{"annual_years":[2020,2021,2022,2023,2024,2025],
                              "daily_years":[2024]}}}
        r=build(p)
        anchors=r["sources"]["PRTR"]["site_address_anchors"]
        self.assertEqual(["울산광역시 울주군 온산읍 온산로 68"],anchors["공식공장ID"])
        self.assertNotIn("온산공장",anchors)
        # If there is no canonical explicit ID, the verified current-site name
        # becomes the single noncanonical address-candidate label.
        without_explicit = dict(p)
        without_explicit.pop("site_address_anchors")
        generated = build(without_explicit)["sources"]["PRTR"]["site_address_anchors"]
        self.assertEqual(["울산광역시 울주군 온산읍 온산로 68"], generated["온산공장"])
        self.assertNotIn("잘못된후보",anchors)
        self.assertNotIn("계열사",anchors)
        # Official address is useful for source-site candidate matching;
        # the generated gate still refuses address-only proof.
        self.assertFalse(r["sources"]["PRTR"]["identity_gate"]["address_only_is_sufficient"])

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
