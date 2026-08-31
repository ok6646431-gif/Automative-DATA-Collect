import csv, json, tempfile, unittest
from pathlib import Path
from orchestrator.learning_cards import run_learning_cards

def wc(p,rows):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

class TestLearningCards(unittest.TestCase):
    def base(self,root,industry=True):
        wc(root/'Site_Master.csv',[{'canonical_site_id':'SITE_P','canonical_site_name':'평택사업장','identity_status':'CONFIRMED'}])
        wc(root/'Review_Topic_Candidates.csv',[{'topic_id':'T1','canonical_site_id':'SITE_P','site_name':'평택사업장','domain':'GHG_ENERGY','scope_label':'x'}])
        sig=[]
        for metric,values,stype in [
            ('GHG_SCOPE1',{'2022':2963576,'2024':939256.22},'DIRECTIONAL_DOWN|LEVEL_SHIFT_CANDIDATE'),
            ('GHG_SCOPE2',{'2022':3658070,'2024':5453585.551},'DIRECTIONAL_UP'),
            ('GHG_TOTAL',{'2022':6621646,'2024':6392841.771},'LEVEL_SHIFT_CANDIDATE')]:
            sig.append({'signal_id':'S_'+metric,'canonical_site_id':'SITE_P','metric':metric,'signal_type':stype,'years':'2022|2024','values_json':json.dumps(values),'in_requested_scope':'YES','interpretation_boundary':'not causal'})
        wc(root/'Review_Signal_Registry.csv',sig)
        wc(root/'Management_Action_Ledger.csv',[{'action_id':'A1','canonical_site_id':'SITE_P','in_requested_scope':'YES','year':'2022','domain':'GHG_ENERGY','action_name':'RCS 증설','description':'생산공정 중 발생하는 온실가스에 대한 촉매 저감장치 설치','disclosed_effect':'온실가스 배출량 감축','source_file':'ENVINFO/x.html','statement_boundary':'company disclosed'}])
        layers=[]
        if industry:
            layers=[{'evidence_id':'E1','layer':'INDUSTRY_TECHNICAL','domain':'GHG_ENERGY','canonical_site_id':'SITE_P','site_name':'평택사업장','time_key':'2019','title':'NF3 처리','statement':'웨이퍼 가공에서 Burn-Wet Scrubber로 NF3를 처리할 수 있다.','source_key':'JKSEE','source_locator':'https://example.com/paper.pdf','semantic_state':'SEMANTIC_FACT','interpretation_boundary':'secondary summary'}]
        wc(root/'Evidence_Layer_Registry.csv',layers)
        (root/'Legal_Evidence.json').write_text(json.dumps({'references':[{'legal_id':'L1','domain':'GHG_ENERGY','law':'법','article':'제24조','title':'보고','statement':'보고한다','source_locator':'https://law.go.kr/x','applicability_boundary':'generic'}]},ensure_ascii=False),encoding='utf-8')
    def test_ready_card_requires_all_evidence_layers(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.base(root,True)
            s=run_learning_cards(root,root/'Legal_Evidence.json')
            self.assertEqual(s['ready_cards'],1); self.assertEqual(s['selected_site'],'평택사업장')
            card=json.loads((root/'Environmental_Learning_Cards.json').read_text(encoding='utf-8'))['cards'][0]
            self.assertEqual(card['state'],'READY'); self.assertTrue(card['company_actual_action']); self.assertTrue(card['law']); self.assertIn('인과관계가 아니다',card['interpretation_boundary'])
    def test_missing_industry_layer_never_invents_ready_card(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.base(root,False)
            s=run_learning_cards(root,root/'Legal_Evidence.json')
            self.assertEqual(s['ready_cards'],0)
            card=json.loads((root/'Environmental_Learning_Cards.json').read_text(encoding='utf-8'))['cards'][0]
            self.assertEqual(card['state'],'NEEDS_EVIDENCE'); self.assertIn('INDUSTRY_TECHNICAL_EVIDENCE',card['missing_evidence'])

if __name__=='__main__': unittest.main()
