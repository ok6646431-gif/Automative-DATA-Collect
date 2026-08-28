import csv, json, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'orchestrator'))
from review_report import build_review_report


def write_csv(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


class TestReviewReport(unittest.TestCase):
    def test_builds_human_readable_report_from_review_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            (p/'Company_Profile.json').write_text(json.dumps({'requested_company_name':'테스트기업','site_candidates':[{'site_name_raw':'A','address_raw':'서울'}]},ensure_ascii=False),encoding='utf-8')
            (p/'Requested_Scope.json').write_text(json.dumps({'mode':'SITE_SET','label':'TEST','target_canonical_site_ids':['SITE_A']},ensure_ascii=False),encoding='utf-8')
            (p/'Review_Selection_Summary.json').write_text(json.dumps({'metric_inventory_in_scope':1,'management_actions_in_scope':1,'topic_candidates':1,'deep_dive_candidates':1,'boundaries':['Do not infer causality.']},ensure_ascii=False),encoding='utf-8')
            (p/'Cross_Layer_Review_Summary.json').write_text(json.dumps({'document_semantics':{'pages_scanned':12},'industry_reference_source_state':'UNAVAILABLE'},ensure_ascii=False),encoding='utf-8')
            write_csv(p/'Site_Master.csv',[{'canonical_site_id':'SITE_A','canonical_site_name':'테스트기업 A사업장'}],['canonical_site_id','canonical_site_name'])
            write_csv(p/'Review_Source_Coverage.csv',[{'source':'ENVINFO','requested_scope_years':'2020|2021|2022|2023','requested_scope_year_count':'4'}],['source','requested_scope_years','requested_scope_year_count'])
            write_csv(p/'Source_Availability.csv',[{'source_key':'CORP_DOCS','evidence_family':'INDUSTRY_REFERENCES','availability_state':'UNAVAILABLE','collection_status':'NO_DOCUMENT_DOWNLOADED','declared_count':'1','available_count':'0','failed_count':'1','skipped_count':'0','notes':'failed_document_ids=BAT1'}],['source_key','evidence_family','availability_state','collection_status','declared_count','available_count','failed_count','skipped_count','notes'])
            write_csv(p/'Review_Metric_Inventory.csv',[{'metric_id':'M1','canonical_site_id':'SITE_A','site_name':'A사업장','domain':'AIR','metric':'NOx','comparability':'TREND_ELIGIBLE','in_requested_scope':'YES'}],['metric_id','canonical_site_id','site_name','domain','metric','comparability','in_requested_scope'])
            write_csv(p/'Review_Signal_Registry.csv',[{'metric_id':'M1','site_name':'A사업장','domain':'AIR','metric':'NOx','signal_type':'DIRECTIONAL_UP','values_json':'{"2020":1,"2021":2,"2022":3,"2023":4}'}],['metric_id','site_name','domain','metric','signal_type','values_json'])
            write_csv(p/'Management_Action_Ledger.csv',[{'action_id':'A1','canonical_site_id':'SITE_A','site_name':'A사업장','year':'2023','domain':'AIR','action_name':'방지시설 개선','investment_million_krw':'10','description':'설비 개선','in_requested_scope':'YES'}],['action_id','canonical_site_id','site_name','year','domain','action_name','investment_million_krw','description','in_requested_scope'])
            write_csv(p/'Chemical_Review_Candidates.csv',[],['chemical','display_level'])
            write_csv(p/'Review_Topic_Candidates.csv',[{'topic_id':'T1','canonical_site_id':'SITE_A','site_name':'A사업장','domain':'AIR','candidate_state':'DEEP_DIVE_CANDIDATE','signal_metric_ids':'M1','signal_labels':'NOx:DIRECTIONAL_UP','action_ids':'A1','why_review':'Comparable signal plus action.','limitations':'No causal inference.'}],['topic_id','canonical_site_id','site_name','domain','candidate_state','signal_metric_ids','signal_labels','action_ids','why_review','limitations'])
            write_csv(p/'Evidence_Layer_Registry.csv',[],['evidence_id','layer','domain','statement','source_locator'])
            write_csv(p/'Cross_Layer_Review_Candidates.csv',[{'review_id':'R1','topic_id':'T1','review_state':'MULTI_LAYER_REVIEW','industry_reference_evidence_ids':'','future_direction_evidence_ids':'','industry_source_state':'UNAVAILABLE','industry_evidence_state':'SOURCE_UNAVAILABLE'}],['review_id','topic_id','review_state','industry_reference_evidence_ids','future_direction_evidence_ids','industry_source_state','industry_evidence_state'])
            write_csv(p/'Study_Question_Queue.csv',[{'review_id':'R1','question':'What denominator is needed?','needed_evidence':'production'}],['review_id','question','needed_evidence'])
            s=build_review_report(p,render_pdf=False)
            self.assertEqual(s['deep_dive_topics'],1)
            self.assertEqual(s['industry_reference_source_state'],'UNAVAILABLE')
            text=(p/'Environmental_Review_Brief.html').read_text(encoding='utf-8')
            self.assertIn('테스트기업 환경관리 검토보고서',text)
            self.assertIn('Deep Dive 1',text)
            self.assertIn('No causal inference',text)
            self.assertIn('자료를 찾지 못한 것',text)
            self.assertIn('기술자료 수집 실패. 근거 부재로 해석하지 않으며 재수집이 필요함.',text)
            self.assertIn('INDUSTRY_REFERENCES',text)


if __name__=='__main__': unittest.main()
