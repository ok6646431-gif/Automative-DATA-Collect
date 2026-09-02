import csv
import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.requested_scope import resolve_requested_scope, apply_requested_scope


def write_csv(path, rows, fields):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


class RequestedScopeRenameBridgeTests(unittest.TestCase):
    def make_package(self):
        td=tempfile.TemporaryDirectory(); root=Path(td.name)
        profile={
            "company_display_name":"에이치디현대삼호 주식회사",
            "requested_company_name":"HD현대삼호",
            "current_legal_name_active_period":{"start_year":2024},
            "legal_entity_active_period":{"start_year":1998},
            "corporate_restructuring_evidence":[{"event_type":"rename","effective_period":{"start_year":2024,"end_year":2024}}],
            "requested_scope":{"mode":"SITE_SET","label":"주요 사업장","candidate_ids":["OFFICIAL"]},
            "aliases":[
                {"term":"에이치디현대삼호 주식회사","scope":"current","alias_type":"current_legal_name","year_start":2024,"year_end":"auto","verification_state":"VERIFIED"},
                {"term":"HD현대삼호","scope":"current","alias_type":"requested_name","year_start":2024,"year_end":"auto","verification_state":"VERIFIED"},
                {"term":"현대삼호중공업","scope":"historical","alias_type":"former_legal_name","year_start":2020,"year_end":2024,"verification_state":"VERIFIED"},
            ],
            "site_candidates":[{
                "candidate_id":"OFFICIAL","site_name_raw":"HD현대삼호 주요 사업장",
                "address_raw":"전남광주통합특별시 영암군 삼호읍 대불로 93",
                "identity_status":"CONFIRMED","verification_state":"VERIFIED",
            }],
            "related_entity_exclusions":[],
        }
        (root/"Company_Profile.json").write_text(json.dumps(profile,ensure_ascii=False),encoding="utf-8")
        write_csv(root/"Site_Master.csv",[
            {"canonical_site_id":"SITE_OFFICIAL","canonical_site_name":"HD현대삼호 주요 사업장","canonical_address_key":"전남광주통합특별시영암군삼호읍대불로93","identity_status":"CONFIRMED"},
            {"canonical_site_id":"SITE_MAIN","canonical_site_name":"에이치디현대삼호","canonical_address_key":"전남영암군삼호읍대불로93","identity_status":"CONFIRMED"},
            {"canonical_site_id":"SITE_D3","canonical_site_name":"현대삼호중공업(주) 대불3공장","canonical_address_key":"전남영암군삼호읍대불산단3로36","identity_status":"CONFIRMED"},
        ],["canonical_site_id","canonical_site_name","canonical_address_key","identity_status"])
        write_csv(root/"Source_Identity.csv",[
            {"source_key":"ENVINFO","source_site_id":"ENV_MAIN","canonical_site_id":"SITE_MAIN","source_site_name_raw":"에이치디현대삼호","source_address_raw":"전남 영암군 삼호읍 대불로 93","match_status":"CONFIRMED"},
            {"source_key":"PRTR","source_site_id":"PRTR_MAIN","canonical_site_id":"SITE_MAIN","source_site_name_raw":"현대삼호중공업(주)","source_address_raw":"전라남도 영암군 삼호읍 대불로 93","match_status":"CONFIRMED"},
            {"source_key":"CHEM_STATS","source_site_id":"CHEM_MAIN","canonical_site_id":"SITE_MAIN","source_site_name_raw":"현대삼호중공업주식회사","source_address_raw":"전라남도 영암군 삼호읍 대불로 93 현대삼호중공업","match_status":"CONFIRMED"},
            {"source_key":"CHEM_STATS","source_site_id":"CHEM_D1","canonical_site_id":"CAND_D1","source_site_name_raw":"현대삼호중공업(주) 대불1공장","source_address_raw":"전라남도 영암군 삼호읍 대불로 93 현대삼호중공업(주)","match_status":"REVIEW_REQUIRED"},
            {"source_key":"PRTR","source_site_id":"PRTR_D3","canonical_site_id":"SITE_D3","source_site_name_raw":"현대삼호중공업(주) 대불3공장","source_address_raw":"전라남도 영암군 삼호읍 대불산단3로 36","match_status":"CONFIRMED"},
        ],["source_key","source_site_id","canonical_site_id","source_site_name_raw","source_address_raw","match_status"])
        write_csv(root/"Analysis_Ready_Index.csv",[
            {"analysis_id":"A","canonical_site_id":"SITE_MAIN","source_key":"ENVINFO","source_site_id":"ENV_MAIN","time_key":"2020","event_link_ids":"","analysis_readiness":"READY","analysis_eligible":"True","notes":""},
            {"analysis_id":"B","canonical_site_id":"SITE_MAIN","source_key":"PRTR","source_site_id":"PRTR_MAIN","time_key":"2022","event_link_ids":"","analysis_readiness":"READY","analysis_eligible":"True","notes":""},
            {"analysis_id":"C","canonical_site_id":"SITE_MAIN","source_key":"CHEM_STATS","source_site_id":"CHEM_MAIN","time_key":"2024","event_link_ids":"","analysis_readiness":"READY","analysis_eligible":"True","notes":""},
            {"analysis_id":"X","canonical_site_id":"SITE_D3","source_key":"PRTR","source_site_id":"PRTR_D3","time_key":"2024","event_link_ids":"","analysis_readiness":"READY","analysis_eligible":"True","notes":""},
        ],["analysis_id","canonical_site_id","source_key","source_site_id","time_key","event_link_ids","analysis_readiness","analysis_eligible","notes"])
        write_csv(root/"Coverage_Event_Links.csv",[],["link_id","source_key","canonical_site_id"])
        return td,root

    def test_admin_name_change_and_verified_former_legal_name_bind_main_source_ids(self):
        td,root=self.make_package()
        try:
            scope=resolve_requested_scope(root)
            self.assertIn("SITE_MAIN",scope["target_canonical_site_ids"])
            self.assertEqual(scope["target_source_ids"]["ENVINFO"],{"ENV_MAIN"})
            self.assertEqual(scope["target_source_ids"]["PRTR"],{"PRTR_MAIN"})
            self.assertEqual(scope["target_source_ids"]["CHEM_STATS"],{"CHEM_MAIN"})
            self.assertNotIn("CHEM_D1",scope["target_source_ids"]["CHEM_STATS"])
            self.assertNotIn("PRTR_D3",scope["target_source_ids"]["PRTR"])
            self.assertEqual(scope["current_legal_entity_active_period"],{"start_year":1998,"end_year":None})
        finally:
            td.cleanup()

    def test_pre_rename_rows_from_same_legal_entity_remain_in_analysis(self):
        td,root=self.make_package()
        try:
            result=apply_requested_scope(root)
            self.assertEqual(result["analysis_rows_before"],4)
            self.assertEqual(result["analysis_rows_after"],3)
            self.assertEqual(result["temporal_rows_held"],0)
            with (root/"Analysis_Ready_Index.csv").open(encoding="utf-8-sig",newline="") as f:
                rows=list(csv.DictReader(f))
            self.assertEqual({r["analysis_id"] for r in rows},{"A","B","C"})
        finally:
            td.cleanup()


if __name__=="__main__":
    unittest.main()
