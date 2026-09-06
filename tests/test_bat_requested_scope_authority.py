import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'orchestrator'))
from bat_stage import _filter_plan_to_requested_scope

class BATRequestedScopeAuthorityTests(unittest.TestCase):
    def test_related_entity_cannot_reenter_bat_through_weak_site_rematch(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            profile={
                'company_display_name':'테스트스틸 주식회사',
                'requested_company_name':'테스트스틸',
                'requested_scope':{'mode':'SITE_SET','candidate_ids':['HQ']},
                'site_candidates':[{'candidate_id':'HQ','site_name_raw':'테스트스틸 포항본사','address_raw':'경상북도 포항시 남구 동해안로 1','verification_state':'VERIFIED'}],
            }
            (root/'Company_Profile.json').write_text(json.dumps(profile,ensure_ascii=False),encoding='utf-8')
            (root/'Requested_Scope.json').write_text(json.dumps({'mode':'SITE_SET','target_canonical_site_ids':['SITE_TARGET']},ensure_ascii=False),encoding='utf-8')
            fields=['canonical_site_id','canonical_site_name','canonical_address_key','identity_status']
            with (root/'Site_Master.csv').open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows([
                    {'canonical_site_id':'SITE_TARGET','canonical_site_name':'테스트스틸 포항본사','canonical_address_key':'경북포항시남구동해안로1','identity_status':'CONFIRMED'},
                    {'canonical_site_id':'SITE_RELATED','canonical_site_name':'테스트스틸머티리얼즈 포항양극재공장','canonical_address_key':'경북포항시북구해안로929','identity_status':'CONFIRMED'},
                ])
            plan={'candidates':[
                {'canonical_site_id':'SITE_TARGET','catalog_id':'BAT_A','collection_action':'REVIEW_BEFORE_COLLECTION'},
                {'canonical_site_id':'SITE_RELATED','catalog_id':'BAT_B','collection_action':'WAIT_FOR_PUBLICATION'},
            ]}
            scoped,audit=_filter_plan_to_requested_scope(root,plan)
            self.assertEqual(['SITE_TARGET'],[r['canonical_site_id'] for r in scoped['candidates']])
            self.assertEqual(['SITE_TARGET'],audit['allowed_canonical_site_ids'])
            self.assertEqual(1,audit['removed_out_of_scope_candidates'])

if __name__=='__main__': unittest.main()
