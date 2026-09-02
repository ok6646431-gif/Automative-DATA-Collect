import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.bootstrap_inputs import bootstrap_inputs
from orchestrator.sustainability_coverage import evaluate


def source_policy():
    return {
        "ENVINFO":{"requested_window":{"start_year":2020,"end_year":2024},"prefer_full_history":False},
        "PRTR":{"requested_window":{"start_year":2020,"end_year":2024},"prefer_full_history":False},
        "CHEM_STATS":{"available_survey_rounds":[2020,2022,2024],"requested_survey_rounds":[2020,2022,2024],"prefer_full_history":True},
        "CLEANSYS_AIR":{"requested_window":{"start_year":2020,"end_year":2025},"prefer_full_history":False},
        "SOOSIRO_WATER":{"requested_window":{"start_year":2020,"end_year":2025},"daily_available_years":[2024],"prefer_full_history":False},
    }


class RenameContinuityContractTests(unittest.TestCase):
    def discovery(self):
        return {
            "schema_version":"1.0","request_id":"rename-continuity","requested_company_name":"새이름",
            "current_legal_name":"새이름 주식회사","current_legal_name_active_period":{"start_year":2024},
            "legal_entity_active_period":{"start_year":1998},
            "company_verification_state":"VERIFIED","confidence":"HIGH",
            "requested_scope":{"mode":"COMPANY","label":"새이름"},
            "company_aliases":[{"name":"새이름","alias_type":"requested_name","active_period":{"start_year":2024},"verification_state":"VERIFIED"}],
            "historical_legal_names":[{"name":"옛이름","alias_type":"former_legal_name","active_period":{"start_year":2020,"end_year":2024},"verification_state":"VERIFIED"}],
            "corporate_restructuring_evidence":[{"event_type":"rename","effective_period":{"start_year":2024,"end_year":2024}}],
            "domestic_site_candidates":[],"identity_evidence":[],"related_entity_exclusions":[],"unresolved_items":[],"event_evidence_references":[],
            "collection_policy":{"minimum_history_years":5,"requested_history_window":{"start_year":2020,"end_year":2026},"sources":source_policy()},
        }

    def test_bootstrap_preserves_entity_age_separately_from_current_name_age(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); d=root/"d.json"; fallback=root/"fallback.json"; po=root/"p.json"; ro=root/"r.json"; so=root/"s.json"
            d.write_text(json.dumps(self.discovery(),ensure_ascii=False),encoding="utf-8")
            result=bootstrap_inputs(d,fallback,po,ro,so)
            profile=json.loads(po.read_text(encoding="utf-8"))
            self.assertEqual(profile["current_legal_name_active_period"],{"start_year":2024})
            self.assertEqual(profile["legal_entity_active_period"],{"start_year":1998})
            self.assertEqual(profile["requested_history_window"]["start_year"],2020)
            self.assertEqual(profile["requested_history_window"]["end_year"],2026)
            self.assertEqual(result["legal_entity_active_period"],{"start_year":1998})

    def test_report_coverage_uses_entity_age_not_rename_year(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); delivered=[]
            for year in range(2020,2026):
                p=root/f"report_{year}.pdf"; p.write_bytes(b"%PDF-test"); delivered.append(p)
            rows=[{
                "document_type":"SUSTAINABILITY_REPORT","title":f"report {year}","report_year":year,
                "verification_status":"VERIFIED","collection_status":"DOWNLOADED",
            } for year in range(2020,2026)]
            profile={
                "minimum_history_years":5,
                "current_legal_name_active_period":{"start_year":2024},
                "legal_entity_active_period":{"start_year":1998},
                "requested_history_window":{"start_year":2020,"end_year":2026},
            }
            result=evaluate(profile,rows,delivered)
            self.assertEqual(result["target_report_years"],list(range(2020,2027)))
            self.assertEqual(result["missing_target_years"],[2026])
            self.assertEqual(result["state"],"FILE_COVERAGE_PARTIAL")


if __name__=="__main__":
    unittest.main()
