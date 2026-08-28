import csv, json, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'orchestrator'))
from cross_layer_review import run_cross_layer_review


def write_csv(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


class TestCrossLayerReview(unittest.TestCase):
    def fixture(self,root):
        pkg=root/'pkg'; pkg.mkdir()
        (pkg/'Company_Profile.json').write_text(json.dumps({'request_id':'REQ1'},ensure_ascii=False),encoding='utf-8')
        (pkg/'Requested_Scope.json').write_text(json.dumps({'mode':'SITE_SET','target_canonical_site_ids':['SITE_A']},ensure_ascii=False),encoding='utf-8')
        write_csv(pkg/'Review_Signal_Registry.csv',[
            {'metric_id':'MET1','years':'2020|2021|2022|2023|2024','metric':'NOX','signal_type':'DIRECTIONAL_UP'}
        ],['metric_id','years','metric','signal_type'])
        write_csv(pkg/'Review_Topic_Candidates.csv',[
            {'topic_id':'TOP1','canonical_site_id':'SITE_A','site_name':'A사업장','domain':'AIR','signal_metric_ids':'MET1','signal_labels':'NOX:DIRECTIONAL_UP'},
            {'topic_id':'TOP2','canonical_site_id':'SITE_B','site_name':'B사업장','domain':'AIR','signal_metric_ids':'MET1','signal_labels':'NOX:DIRECTIONAL_UP'}
        ],['topic_id','canonical_site_id','site_name','domain','signal_metric_ids','signal_labels'])
        write_csv(pkg/'Management_Action_Ledger.csv',[
            {'action_id':'ACT1','canonical_site_id':'SITE_A','site_name':'A사업장','year':'2023','domain':'AIR','action_name':'대기 방지시설 개선','description':'NOx 저감설비 개선','disclosed_effect':'','source_file':'ENVINFO/a.html'},
            {'action_id':'ACT2','canonical_site_id':'SITE_B','site_name':'B사업장','year':'2023','domain':'AIR','action_name':'다른 사업장 설비','description':'NOx','disclosed_effect':'','source_file':'ENVINFO/b.html'}
        ],['action_id','canonical_site_id','site_name','year','domain','action_name','description','disclosed_effect','source_file'])
        write_csv(pkg/'Event_Registry.csv',[
            {'event_id':'EV1','canonical_site_id':'','event_date_start':'2022-09-15','event_title':'신환경전략','event_description':'2050 탄소중립 및 대기오염물질 최소화 목표','event_type':'ENVIRONMENT_STRATEGY_CHANGE','analysis_role':'','source_key':'OFFICIAL','source_locator':'https://example.com/strategy'}
        ],['event_id','canonical_site_id','event_date_start','event_title','event_description','event_type','analysis_role','source_key','source_locator'])
        write_csv(pkg/'output'/'CORP_DOCS'/'document_index.csv',[
            {'document_id':'BAT1','collection_status':'DOWNLOADED','document_type':'BAT_REFERENCE','title':'업종 최적가용기법 기준서','report_year':'2020','source_locator':'https://example.com/bat','source_url':'https://example.com/bat.pdf','notes':''}
        ],['document_id','collection_status','document_type','title','report_year','source_locator','source_url','notes'])
        (pkg/'output'/'CORP_DOCS'/'status.json').write_text(json.dumps({
            'status':'DATA_FOUND','documents_declared':1,'downloaded':1,'failed':0,'skipped':0
        }),encoding='utf-8')
        return pkg

    def test_reference_document_does_not_become_bat_semantic_claim(self):
        with tempfile.TemporaryDirectory() as td:
            pkg=self.fixture(Path(td))
            summary=run_cross_layer_review(pkg)
            rows=list(csv.DictReader((pkg/'Cross_Layer_Review_Candidates.csv').open(encoding='utf-8-sig')))
            self.assertEqual(len(rows),1)  # requested scope filters SITE_B
            self.assertEqual(rows[0]['industry_semantic_ready'],'REFERENCE_ONLY')
            self.assertEqual(rows[0]['industry_source_state'],'AVAILABLE')
            self.assertEqual(rows[0]['industry_evidence_state'],'REFERENCE_ONLY')
            self.assertEqual(rows[0]['review_state'],'MULTI_LAYER_REVIEW')
            qs=list(csv.DictReader((pkg/'Study_Question_Queue.csv').open(encoding='utf-8-sig')))
            self.assertIn('INDUSTRY_SEMANTIC_GAP',{q['question_type'] for q in qs})
            availability=list(csv.DictReader((pkg/'Source_Availability.csv').open(encoding='utf-8-sig')))
            industry=[r for r in availability if r['evidence_family']=='INDUSTRY_REFERENCES'][0]
            self.assertEqual(industry['availability_state'],'AVAILABLE')
            self.assertEqual(summary['industry_reference_source_state'],'AVAILABLE')
            self.assertEqual(summary['four_layer_ready'],0)

    def test_page_level_bat_fact_upgrades_to_four_layer_ready(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); pkg=self.fixture(root)
            semantic=root/'semantic.json'
            semantic.write_text(json.dumps({
                'request_id':'REQ1',
                'facts':[{
                    'fact_id':'BAT_FACT_1','layer':'INDUSTRY_TECHNICAL','domain':'AIR','year':2020,
                    'title':'BAT 대기관리 근거','statement':'업종 기준서에서 대기 배출 관리기술을 기술한다.',
                    'source_key':'BAT_KBREF','source_locator':'https://example.com/bat#page=10',
                    'interpretation_boundary':'Industry reference only; company application not confirmed.'
                }]
            },ensure_ascii=False),encoding='utf-8')
            summary=run_cross_layer_review(pkg,semantic)
            rows=list(csv.DictReader((pkg/'Cross_Layer_Review_Candidates.csv').open(encoding='utf-8-sig')))
            self.assertEqual(rows[0]['industry_semantic_ready'],'YES')
            self.assertEqual(rows[0]['industry_evidence_state'],'SEMANTIC_READY')
            self.assertEqual(rows[0]['review_state'],'FOUR_LAYER_READY')
            self.assertEqual(summary['four_layer_ready'],1)

    def test_context_only_events_do_not_fill_action_or_future_layers(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); pkg=self.fixture(root)
            write_csv(pkg/'Management_Action_Ledger.csv',[],[
                'action_id','canonical_site_id','site_name','year','domain','action_name','description','disclosed_effect','source_file'
            ])
            write_csv(pkg/'Event_Registry.csv',[
                {
                    'event_id':'EV_BUILD','canonical_site_id':'SITE_A','event_date_start':'2021-02-01',
                    'event_title':'신규 Fab 완공','event_description':'생산능력 확대를 위한 신규 공장을 완공했다.',
                    'event_type':'PRODUCTION_CAPACITY_CHANGE','analysis_role':'CONTEXT_MARKER',
                    'source_key':'OFFICIAL','source_locator':'https://example.com/build'
                },
                {
                    'event_id':'EV_PLAN','canonical_site_id':'SITE_A','event_date_start':'2024-04-24',
                    'event_title':'신규 Fab 투자계획','event_description':'향후 생산능력 확대를 위한 투자 계획을 발표했다.',
                    'event_type':'PRODUCTION_CAPACITY_PLAN','analysis_role':'CONTEXT_MARKER',
                    'source_key':'OFFICIAL','source_locator':'https://example.com/plan'
                }
            ],['event_id','canonical_site_id','event_date_start','event_title','event_description','event_type','analysis_role','source_key','source_locator'])
            semantic=root/'semantic.json'
            semantic.write_text(json.dumps({
                'request_id':'REQ1',
                'facts':[{
                    'fact_id':'BAT_FACT_1','layer':'INDUSTRY_TECHNICAL','domain':'AIR','year':2020,
                    'title':'BAT 대기관리 근거','statement':'업종 기준서에서 대기 배출 관리기술을 기술한다.',
                    'source_key':'BAT_KBREF','source_locator':'https://example.com/bat#page=10',
                    'interpretation_boundary':'Industry reference only; company application not confirmed.'
                }]
            },ensure_ascii=False),encoding='utf-8')
            summary=run_cross_layer_review(pkg,semantic)
            rows=list(csv.DictReader((pkg/'Cross_Layer_Review_Candidates.csv').open(encoding='utf-8-sig')))
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['company_action_evidence_ids'],'')
            self.assertEqual(rows[0]['future_direction_evidence_ids'],'')
            self.assertEqual(rows[0]['review_state'],'CONTEXT_ONLY')
            qs=list(csv.DictReader((pkg/'Study_Question_Queue.csv').open(encoding='utf-8-sig')))
            qtypes={q['question_type'] for q in qs}
            self.assertIn('COMPANY_ACTION_GAP',qtypes)
            self.assertIn('FUTURE_DIRECTION_GAP',qtypes)
            self.assertEqual(summary['four_layer_ready'],0)

    def test_failed_industry_download_is_not_reported_as_no_reference(self):
        with tempfile.TemporaryDirectory() as td:
            pkg=self.fixture(Path(td))
            write_csv(pkg/'output'/'CORP_DOCS'/'document_index.csv',[
                {
                    'document_id':'BAT_FAIL','collection_status':'DOWNLOAD_FAILED','document_type':'BAT_REFERENCE',
                    'title':'업종 최적가용기법 기준서','report_year':'2020','source_locator':'https://example.com/bat',
                    'source_url':'https://example.com/bat.pdf','notes':'ConnectTimeout'
                }
            ],['document_id','collection_status','document_type','title','report_year','source_locator','source_url','notes'])
            (pkg/'output'/'CORP_DOCS'/'status.json').write_text(json.dumps({
                'status':'NO_DOCUMENT_DOWNLOADED','documents_declared':1,'downloaded':0,'failed':1,'skipped':0
            }),encoding='utf-8')
            summary=run_cross_layer_review(pkg)
            rows=list(csv.DictReader((pkg/'Cross_Layer_Review_Candidates.csv').open(encoding='utf-8-sig')))
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['industry_source_state'],'UNAVAILABLE')
            self.assertEqual(rows[0]['industry_evidence_state'],'SOURCE_UNAVAILABLE')
            self.assertIn('not treated as evidence absence',rows[0]['why_review'])
            qs=list(csv.DictReader((pkg/'Study_Question_Queue.csv').open(encoding='utf-8-sig')))
            qtypes={q['question_type'] for q in qs}
            self.assertIn('INDUSTRY_SOURCE_UNAVAILABLE',qtypes)
            self.assertNotIn('INDUSTRY_REFERENCE_GAP',qtypes)
            availability=list(csv.DictReader((pkg/'Source_Availability.csv').open(encoding='utf-8-sig')))
            industry=[r for r in availability if r['evidence_family']=='INDUSTRY_REFERENCES'][0]
            self.assertEqual(industry['availability_state'],'UNAVAILABLE')
            self.assertEqual(industry['failed_count'],'1')
            self.assertEqual(summary['industry_reference_source_state'],'UNAVAILABLE')


if __name__=='__main__': unittest.main()
