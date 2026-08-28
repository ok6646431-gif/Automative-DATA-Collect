import csv, json, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'orchestrator'))
from cross_layer_review import run_cross_layer_review


def write_csv(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


class TestIndustryReferenceApplicability(unittest.TestCase):
    def fixture(self,root):
        pkg=root/'pkg'; pkg.mkdir()
        profile={
            'request_id':'REQ_APP',
            'company_display_name':'테스트회사',
            'requested_scope':{'mode':'SITE_SET','candidate_ids':['energy-1','chem-1']},
            'site_candidates':[
                {'candidate_id':'energy-1','site_name_raw':'여수에너지','address_raw':'전라남도 여수시 에너지로 1'},
                {'candidate_id':'chem-1','site_name_raw':'여수화학','address_raw':'전라남도 여수시 화학로 2'}
            ]
        }
        (pkg/'Company_Profile.json').write_text(json.dumps(profile,ensure_ascii=False),encoding='utf-8')
        (pkg/'Requested_Scope.json').write_text(json.dumps({'mode':'SITE_SET','label':'TEST','target_canonical_site_ids':['SITE_ENERGY','SITE_CHEM']},ensure_ascii=False),encoding='utf-8')
        write_csv(pkg/'Site_Master.csv',[
            {'canonical_site_id':'SITE_ENERGY','canonical_site_name':'여수에너지','canonical_address_key':'전라남도 여수시 에너지로 1','identity_status':'CONFIRMED'},
            {'canonical_site_id':'SITE_CHEM','canonical_site_name':'여수화학','canonical_address_key':'전라남도 여수시 화학로 2','identity_status':'CONFIRMED'}
        ],['canonical_site_id','canonical_site_name','canonical_address_key','identity_status'])
        write_csv(pkg/'Review_Signal_Registry.csv',[
            {'metric_id':'MET_E','years':'2020|2021|2022|2023|2024','metric':'NOX','signal_type':'DIRECTIONAL_UP'},
            {'metric_id':'MET_C','years':'2020|2021|2022|2023|2024','metric':'NOX','signal_type':'DIRECTIONAL_UP'}
        ],['metric_id','years','metric','signal_type'])
        write_csv(pkg/'Review_Topic_Candidates.csv',[
            {'topic_id':'TOP_E','canonical_site_id':'SITE_ENERGY','site_name':'여수에너지','domain':'AIR','signal_metric_ids':'MET_E','signal_labels':'NOX:DIRECTIONAL_UP','scope_label':'TEST'},
            {'topic_id':'TOP_C','canonical_site_id':'SITE_CHEM','site_name':'여수화학','domain':'AIR','signal_metric_ids':'MET_C','signal_labels':'NOX:DIRECTIONAL_UP','scope_label':'TEST'}
        ],['topic_id','canonical_site_id','site_name','domain','signal_metric_ids','signal_labels','scope_label'])
        write_csv(pkg/'Management_Action_Ledger.csv',[
            {'action_id':'ACT_E','canonical_site_id':'SITE_ENERGY','site_name':'여수에너지','year':'2024','domain':'AIR','action_name':'저감설비','description':'대기 저감설비 운영','disclosed_effect':'','source_file':'e.html'},
            {'action_id':'ACT_C','canonical_site_id':'SITE_CHEM','site_name':'여수화학','year':'2024','domain':'AIR','action_name':'저감설비','description':'대기 저감설비 운영','disclosed_effect':'','source_file':'c.html'}
        ],['action_id','canonical_site_id','site_name','year','domain','action_name','description','disclosed_effect','source_file'])
        write_csv(pkg/'Event_Registry.csv',[
            {'event_id':'FUT','canonical_site_id':'','event_date_start':'2025','event_title':'대기 배출 저감 목표','event_description':'향후 대기오염물질 저감 목표를 추진한다.','event_type':'ENVIRONMENT_STRATEGY_CHANGE','analysis_role':'','source_key':'OFFICIAL','source_locator':'https://example.com/future'}
        ],['event_id','canonical_site_id','event_date_start','event_title','event_description','event_type','analysis_role','source_key','source_locator'])
        for source in ['ENVINFO','PRTR','CHEM_STATS','CLEANSYS_AIR','SOOSIRO_WATER']:
            (pkg/'output'/source).mkdir(parents=True,exist_ok=True)
            status='DATA_FOUND' if source=='ENVINFO' else 'NO_DATA'
            (pkg/'output'/source/'status.json').write_text(json.dumps({'status':status}),encoding='utf-8')
        write_csv(pkg/'output'/'CORP_DOCS'/'document_index.csv',[
            {'document_id':'ENERGY_KBREF_II','collection_status':'DOWNLOADED','document_type':'BAT_REFERENCE','title':'전기 및 증기 생산시설 최적가용기법 기준서','report_year':'2022','source_locator':'https://example.com/energy-bat','source_url':'https://example.com/energy-bat.pdf','notes':''}
        ],['document_id','collection_status','document_type','title','report_year','source_locator','source_url','notes'])
        (pkg/'output'/'CORP_DOCS'/'status.json').write_text(json.dumps({'status':'DATA_FOUND','documents_declared':1,'downloaded':1,'failed':0,'skipped':0}),encoding='utf-8')
        app=root/'app.json'
        app.write_text(json.dumps({
            'request_id':'REQ_APP','references':[{
                'document_id':'ENERGY_KBREF_II','applicability_state':'VERIFIED','candidate_ids':['energy-1'],
                'basis':'Energy reference applies only to the verified energy unit.','source_locator':'https://example.com/energy-bat'
            }]
        }),encoding='utf-8')
        return pkg,app

    def test_reference_is_site_scoped_and_does_not_bleed_to_other_unit(self):
        with tempfile.TemporaryDirectory() as td:
            pkg,app=self.fixture(Path(td))
            summary=run_cross_layer_review(pkg,applicability_path=app)
            rows={r['canonical_site_id']:r for r in csv.DictReader((pkg/'Cross_Layer_Review_Candidates.csv').open(encoding='utf-8-sig'))}
            self.assertEqual(rows['SITE_ENERGY']['industry_evidence_state'],'REFERENCE_ONLY')
            self.assertEqual(rows['SITE_CHEM']['industry_evidence_state'],'NO_EVIDENCE_FOUND')
            industry=[r for r in csv.DictReader((pkg/'Evidence_Layer_Registry.csv').open(encoding='utf-8-sig')) if r['layer']=='INDUSTRY_TECHNICAL']
            self.assertTrue(industry)
            self.assertEqual({r['canonical_site_id'] for r in industry},{'SITE_ENERGY'})
            app_rows=list(csv.DictReader((pkg/'Industry_Reference_Applicability.csv').open(encoding='utf-8-sig')))
            self.assertEqual(app_rows[0]['applicability_state'],'VERIFIED')
            self.assertEqual(app_rows[0]['canonical_site_ids'],'SITE_ENERGY')
            self.assertEqual(summary['industry_reference_applicability_counts'],{'VERIFIED':1})

    def test_semantic_fact_is_promoted_only_inside_verified_applicability(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); pkg,app=self.fixture(root)
            semantic=root/'semantic.json'
            semantic.write_text(json.dumps({
                'request_id':'REQ_APP','facts':[{
                    'fact_id':'FACT1','document_id':'ENERGY_KBREF_II','layer':'INDUSTRY_TECHNICAL','domain':'AIR','year':2022,
                    'title':'에너지 BAT 대기관리','statement':'전기 및 증기 생산시설의 대기오염 관리기법을 설명한다.',
                    'source_key':'BAT','source_locator':'https://example.com/energy-bat#page=10',
                    'interpretation_boundary':'Industry reference only; company application not confirmed.'
                }]
            },ensure_ascii=False),encoding='utf-8')
            summary=run_cross_layer_review(pkg,semantic_path=semantic,applicability_path=app)
            rows={r['canonical_site_id']:r for r in csv.DictReader((pkg/'Cross_Layer_Review_Candidates.csv').open(encoding='utf-8-sig'))}
            self.assertEqual(rows['SITE_ENERGY']['industry_semantic_ready'],'YES')
            self.assertEqual(rows['SITE_ENERGY']['review_state'],'FOUR_LAYER_READY')
            self.assertEqual(rows['SITE_CHEM']['industry_semantic_ready'],'NO')
            self.assertNotEqual(rows['SITE_CHEM']['review_state'],'FOUR_LAYER_READY')
            self.assertEqual(summary['four_layer_ready'],1)

    def test_unresolved_applicability_is_not_promoted(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); pkg,app=self.fixture(root)
            app.write_text(json.dumps({'request_id':'REQ_APP','references':[{
                'document_id':'ENERGY_KBREF_II','applicability_state':'REVIEW_REQUIRED','candidate_ids':[],
                'basis':'Exact site applicability not yet verified.','source_locator':'https://example.com/energy-bat'
            }]}),encoding='utf-8')
            run_cross_layer_review(pkg,applicability_path=app)
            industry=[r for r in csv.DictReader((pkg/'Evidence_Layer_Registry.csv').open(encoding='utf-8-sig')) if r['layer']=='INDUSTRY_TECHNICAL']
            self.assertEqual(industry,[])
            app_row=list(csv.DictReader((pkg/'Industry_Reference_Applicability.csv').open(encoding='utf-8-sig')))[0]
            self.assertEqual(app_row['applicability_state'],'REVIEW_REQUIRED')


if __name__=='__main__': unittest.main()
