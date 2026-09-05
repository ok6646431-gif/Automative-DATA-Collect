import json, tempfile, unittest
from pathlib import Path

from orchestrator.brefos_catalog_reconcile import core_title, brefos_generation, reconcile


class BREFOSCatalogReconcileTests(unittest.TestCase):
    def test_title_normalization_and_generation(self):
        self.assertEqual(core_title('[2기] 철강 제조업의 환경오염방지 및 통합환경관리를 위한 최적가용기법 기준서'), core_title('철강 제조업 최적가용기법 기준서(Ⅱ)'))
        self.assertEqual(brefos_generation('[2기-part 3] 유기화학산업의 환경오염방지 및 통합환경관리를 위한 최적가용기법 기준서'),2)

    def test_multi_part_current_revision_groups_all_parts(self):
        catalog={'schema_version':'test','entries':[
            {'catalog_id':'ORG_II','catalog_family':'ORG','preferred':True,'revision_generation':'II','publication_year':2024,'publication_status':'PUBLISHED','title':'유기화학산업 최적가용기법 기준서(Ⅱ)'},
        ]}
        registry={'status':'PASS','verified_pdf_count':4,'documents':[
            {'status':'VERIFIED_PDF','atch_file_id':str(i),'ntt_id':str(100+i),'title':f'[2기-part {i}] 유기화학산업의 환경오염방지 및 통합환경관리를 위한 최적가용기법 기준서','viewer_pdf_url':f'https://ieps.nier.go.kr/brefos/common/file/pdfDocPdf.do?atchFileId={i}','bytes':100+i,'sha256':str(i)*64}
            for i in range(1,5)
        ]}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'catalog.json'; p.write_text(json.dumps(catalog,ensure_ascii=False),encoding='utf-8')
            out=reconcile(registry,p)
        row=out['master_matches'][0]
        self.assertEqual(row['match_state'],'AUTO_MATCH')
        self.assertEqual(row['matched_document_count'],4)
        self.assertEqual({d['atch_file_id'] for d in row['matched_documents']},{'1','2','3','4'})

    def test_generation_mismatch_is_not_auto_match(self):
        catalog={'schema_version':'test','entries':[
            {'catalog_id':'STEEL_II','catalog_family':'STEEL','preferred':True,'revision_generation':'II','publication_year':2023,'publication_status':'PUBLISHED','title':'철강 제조업 최적가용기법 기준서(Ⅱ)'},
        ]}
        registry={'status':'PASS','verified_pdf_count':1,'documents':[
            {'status':'VERIFIED_PDF','atch_file_id':'1','title':'[1기] 철강 제조업의 환경오염방지 및 통합환경관리를 위한 최적가용기법 기준서','viewer_pdf_url':'https://ieps.nier.go.kr/brefos/common/file/pdfDocPdf.do?atchFileId=1','bytes':100,'sha256':'a'*64}
        ]}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'catalog.json'; p.write_text(json.dumps(catalog,ensure_ascii=False),encoding='utf-8')
            out=reconcile(registry,p)
        self.assertNotEqual(out['master_matches'][0]['match_state'],'AUTO_MATCH')


if __name__=='__main__': unittest.main()
