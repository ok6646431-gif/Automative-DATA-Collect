import csv, json, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'orchestrator'))
from document_semantics import run_document_semantics


class TestDocumentSemantics(unittest.TestCase):
    def test_page_grounded_bat_and_company_candidates_are_separated(self):
        with tempfile.TemporaryDirectory() as td:
            pkg=Path(td); corp=pkg/'output'/'CORP_DOCS'; raw=corp/'raw_documents'; raw.mkdir(parents=True)
            bat=raw/'BAT_REFERENCE'/'2020'; bat.mkdir(parents=True)
            sus=raw/'SUSTAINABILITY_REPORT'/'2026'; sus.mkdir(parents=True)
            bat_file=bat/'BAT1_semiconductor.html'
            bat_file.write_text('<html><body>반도체 폐수의 불소는 중화 및 침전 처리를 통해 저감할 수 있으며 폐수처리 공정의 운전조건을 검토한다.</body></html>',encoding='utf-8')
            sus_file=sus/'SUS1_report.html'
            sus_file.write_text('<html><body>회사는 2030년까지 용수 재이용을 확대할 계획이며 재이용 설비를 단계적으로 도입한다.</body></html>',encoding='utf-8')
            rows=[
                {'document_id':'BAT1','document_type':'BAT_REFERENCE','report_year':'2020','stored_path':str(bat_file.relative_to(pkg)),'source_locator':'https://example.com/bat','source_url':'https://example.com/bat','collection_status':'DOWNLOADED'},
                {'document_id':'SUS1','document_type':'SUSTAINABILITY_REPORT','report_year':'2026','stored_path':str(sus_file.relative_to(pkg)),'source_locator':'https://example.com/sus','source_url':'https://example.com/sus','collection_status':'DOWNLOADED'},
            ]
            fields=['document_id','document_type','report_year','stored_path','source_locator','source_url','collection_status']
            with (corp/'document_index.csv').open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
            (pkg/'Company_Profile.json').write_text(json.dumps({'request_id':'REQ1'},ensure_ascii=False),encoding='utf-8')
            summary=run_document_semantics(pkg)
            candidates=list(csv.DictReader((pkg/'Document_Semantic_Candidates.csv').open(encoding='utf-8-sig')))
            self.assertTrue(any(r['layer']=='INDUSTRY_TECHNICAL' and r['domain']=='WATER' for r in candidates))
            self.assertTrue(any(r['layer']=='FUTURE_DIRECTION' and r['domain']=='WATER_RESOURCES' for r in candidates))
            generated=json.loads((pkg/'Generated_Semantic_Evidence.json').read_text(encoding='utf-8'))
            self.assertEqual(generated['request_id'],'REQ1')
            self.assertTrue(generated['facts'])
            self.assertTrue(all(f['layer']=='INDUSTRY_TECHNICAL' for f in generated['facts']))
            self.assertTrue(all('#page=' in f['source_locator'] for f in generated['facts']))
            self.assertGreaterEqual(summary['generated_industry_facts'],1)


if __name__=='__main__': unittest.main()
