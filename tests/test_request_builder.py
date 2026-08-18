import unittest
from orchestrator.request_builder import build


class TestRequestBuilder(unittest.TestCase):
    def test_predecessor_is_limited_to_active_years(self):
        p={
            "request_id":"x","company_display_name":"테스트화학",
            "aliases":[
                {"term":"테스트화학","scope":"current","year_start":2010,"year_end":"auto"},
                {"term":"구테스트","scope":"predecessor","year_start":2000,"year_end":2016}
            ],
            "source_plan":{
                "ENVINFO":{"start_year":2024,"end_year":2024},
                "PRTR":{"start_year":2015,"end_year":2024},
                "CHEM_STATS":{"years":[2018,2020,2022,2024]},
                "CLEANSYS_AIR":{"start_year":2015,"end_year":2025},
                "SOOSIRO_WATER":{"annual_years":[2019,2020,2021,2022,2023,2024,2025],"daily_years":[2024]}
            }
        }
        r=build(p)
        self.assertEqual(r["sources"]["ENVINFO"]["search_terms"],["테스트화학"])
        pr=r["sources"]["PRTR"]["search_terms"]
        old=[x for x in pr if x["term"]=="구테스트"][0]
        self.assertEqual((old["year_start"],old["year_end"]),(2015,2016))
        self.assertNotIn("구테스트",r["sources"]["CLEANSYS_AIR"]["search_terms"])
        self.assertNotIn("구테스트",r["sources"]["SOOSIRO_WATER"]["search_terms"])


if __name__=="__main__": unittest.main()
