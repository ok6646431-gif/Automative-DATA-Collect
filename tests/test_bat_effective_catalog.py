import csv, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
ORCH=ROOT/'orchestrator'
if str(ORCH) not in sys.path: sys.path.insert(0,str(ORCH))

from orchestrator.bat_catalog_effective import build_effective_catalog
import bat_stage


class BATEffectiveCatalogTests(unittest.TestCase):
    def test_unverified_newer_revision_does_not_supersede_last_verified_publication(self):
        catalog,advisories=build_effective_catalog()
        entries={e.get('catalog_id'):e for e in catalog.get('entries',[])}
        self.assertIn('KBREF_SEMICONDUCTOR_2019',entries)
        self.assertNotIn('KBREF_SEMICONDUCTOR_II_2025',entries)
        current=entries['KBREF_SEMICONDUCTOR_2019']
        self.assertTrue(current.get('preferred'))
        self.assertEqual(current.get('supersession_status'),'CURRENT_VERIFIED_PUBLICATION')
        self.assertEqual(current.get('collection_policy'),'COLLECT_WHEN_MATCHED')
        by_id={a.get('catalog_id'):a for a in advisories}
        self.assertEqual(by_id['KBREF_SEMICONDUCTOR_II_2025']['reason_code'],'NEWER_REVISION_PUBLICATION_NOT_VERIFIED')
        self.assertFalse(by_id['KBREF_SEMICONDUCTOR_II_2025']['include_in_effective_catalog'])

    def test_site_set_scope_removes_out_of_scope_bat_candidates_before_collection(self):
        plan={
            'schema_version':'test','candidates':[
                {'catalog_id':'BAT_A','canonical_site_id':'SITE_A','collection_action':'COLLECT'},
                {'catalog_id':'BAT_A','canonical_site_id':'SITE_B','collection_action':'COLLECT'},
                {'catalog_id':'BAT_RUBBER','canonical_site_id':'SITE_X','collection_action':'WAIT_FOR_PUBLICATION'},
            ],
            'candidate_count':3,'site_count':3,'collect_catalog_ids':['BAT_A'],
            'boundaries':[],
        }
        profile={'requested_scope':{'mode':'SITE_SET','candidate_ids':['CAND_A','CAND_B']}}
        inverse={'SITE_A':['CAND_A'],'SITE_B':['CAND_B']}
        with tempfile.TemporaryDirectory() as td:
            package=Path(td)
            with patch.object(bat_stage,'_canonical_candidate_map',return_value=(profile,inverse)):
                scoped,audit=bat_stage._filter_plan_to_requested_scope(package,plan)
            self.assertTrue(audit['applied'])
            self.assertEqual(audit['removed_out_of_scope_candidates'],1)
            self.assertEqual(scoped['candidate_count'],2)
            self.assertEqual(scoped['site_count'],2)
            self.assertEqual({r['canonical_site_id'] for r in scoped['candidates']},{'SITE_A','SITE_B'})
            self.assertNotIn('BAT_RUBBER',{r['catalog_id'] for r in scoped['candidates']})
            rows=list(csv.DictReader((package/'BAT_Applicability_Candidates.csv').open(encoding='utf-8-sig')))
            self.assertEqual(len(rows),2)
            persisted=json.loads((package/'BAT_Collection_Plan.json').read_text(encoding='utf-8'))
            self.assertEqual(persisted['requested_scope_filter']['candidate_count_after'],2)


if __name__=='__main__': unittest.main()
