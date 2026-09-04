# Regression trigger: validates current/preferred matching plus superseded revision archival on the latest BAT catalog.
import csv, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.bat_collector import collect


CANDIDATE_FIELDS=[
    'candidate_id','catalog_id','catalog_family','revision_generation','canonical_site_id','site_name','candidate_role','candidate_state',
    'applicability_state','publication_status','legal_status','effective_from','matched_ksic_prefixes','matched_industry_terms',
    'matched_process_terms','matched_utility_terms','evidence_channels','evidence_basis','collection_action','official_source_locator'
]


def write_csv(path,rows,fields):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def current_candidate(catalog_id='BAT_NEW',family='BAT_FAMILY',action='COLLECT'):
    return {
        'candidate_id':'C1','catalog_id':catalog_id,'catalog_family':family,'revision_generation':'II',
        'canonical_site_id':'SITE_A','site_name':'테스트사업장','candidate_role':'PRIMARY','candidate_state':'PRIMARY_CANDIDATE',
        'applicability_state':'STRONG_CANDIDATE','publication_status':'PUBLISHED','legal_status':'PUBLISHED_REFERENCE',
        'collection_action':action,'official_source_locator':'https://ieps.nier.go.kr/web/board/5/999/'
    }


class BATRevisionCollectionTests(unittest.TestCase):
    def _setup(self,td,catalog,candidate):
        package=Path(td)/'assembled'; package.mkdir()
        catalog_path=Path(td)/'catalog.json'
        catalog_path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
        write_csv(package/'BAT_Applicability_Candidates.csv',[candidate],CANDIDATE_FIELDS)
        return package,catalog_path

    def test_matched_family_collects_current_and_superseded_revisions(self):
        catalog={'schema_version':'test','entries':[
            {'catalog_id':'BAT_OLD','catalog_family':'BAT_FAMILY','preferred':False,'revision_generation':'I','publication_year':2018,
             'publication_status':'PUBLISHED','title':'테스트 BAT 구판','official_document_page':'https://ieps.nier.go.kr/web/board/5/1/','domains':['AIR']},
            {'catalog_id':'BAT_NEW','catalog_family':'BAT_FAMILY','preferred':True,'revision_generation':'II','publication_year':2024,
             'publication_status':'PUBLISHED','title':'테스트 BAT 신판','official_document_page':'https://ieps.nier.go.kr/web/board/5/2/','domains':['AIR']},
        ]}
        with tempfile.TemporaryDirectory() as td:
            package,catalog_path=self._setup(td,catalog,current_candidate())
            with patch('orchestrator.bat_collector.fetch_pdf_from_spec',return_value=('https://ieps.nier.go.kr/file.pdf',b'%PDF-1.4\n%%EOF','TEST')):
                status=collect(package,catalog_path)
            rows=read_csv(package/'output'/'BAT_REFERENCES'/'document_index.csv')
            self.assertEqual(len(rows),2)
            old=[r for r in rows if r['catalog_id']=='BAT_OLD'][0]
            new=[r for r in rows if r['catalog_id']=='BAT_NEW'][0]
            self.assertEqual(old['collection_status'],'DOWNLOADED')
            self.assertEqual(old['revision_status'],'SUPERSEDED_ARCHIVE_ONLY')
            self.assertEqual(old['preferred_for_matching'],'false')
            self.assertEqual(new['collection_status'],'DOWNLOADED')
            self.assertEqual(new['preferred_for_matching'],'true')
            self.assertIn('BAT_FAMILY',old['stored_path'])
            self.assertIn('2018_I',old['stored_path'])
            self.assertIn('2024_II',new['stored_path'])
            self.assertEqual(status['current_downloaded'],1)
            self.assertEqual(status['superseded_downloaded'],1)
            self.assertEqual(status['status'],'DATA_FOUND')

    def test_old_revision_does_not_substitute_when_latest_locator_is_pending(self):
        catalog={'schema_version':'test','entries':[
            {'catalog_id':'BAT_OLD','catalog_family':'BAT_FAMILY','preferred':False,'revision_generation':'I','publication_year':2018,
             'publication_status':'PUBLISHED','title':'테스트 BAT 구판','official_document_page':'https://ieps.nier.go.kr/web/board/5/1/','domains':['AIR']},
            {'catalog_id':'BAT_NEW','catalog_family':'BAT_FAMILY','preferred':True,'revision_generation':'II','publication_year':2024,
             'publication_status':'PUBLISHED','title':'테스트 BAT 신판','collection_policy':'WAIT_FOR_LATEST_LOCATOR','domains':['AIR']},
        ]}
        with tempfile.TemporaryDirectory() as td:
            package,catalog_path=self._setup(td,catalog,current_candidate(action='WAIT_FOR_LATEST_LOCATOR'))
            with patch('orchestrator.bat_collector.fetch_pdf_from_spec',return_value=('https://ieps.nier.go.kr/old.pdf',b'%PDF-1.4\n%%EOF','TEST')) as mocked:
                status=collect(package,catalog_path)
            rows=read_csv(package/'output'/'BAT_REFERENCES'/'document_index.csv')
            old=[r for r in rows if r['catalog_id']=='BAT_OLD'][0]
            new=[r for r in rows if r['catalog_id']=='BAT_NEW'][0]
            self.assertEqual(old['collection_status'],'DOWNLOADED')
            self.assertEqual(new['collection_status'],'LATEST_LOCATOR_PENDING')
            self.assertEqual(status['current_downloaded'],0)
            self.assertEqual(status['superseded_downloaded'],1)
            self.assertEqual(status['status'],'LATEST_LOCATOR_PENDING_WITH_ARCHIVE')
            self.assertEqual(mocked.call_count,1)

    def test_multi_volume_revision_keeps_parts_separate(self):
        catalog={'schema_version':'test','entries':[
            {'catalog_id':'BAT_NEW','catalog_family':'BAT_FAMILY','preferred':True,'revision_generation':'II','publication_year':2024,
             'publication_status':'PUBLISHED','title':'다권 BAT','domains':['AIR'],
             'official_documents':[
                 {'document_part':'1','volume_no':'I','title':'다권 BAT 제1권','official_document_page':'https://ieps.nier.go.kr/web/board/5/11/'},
                 {'document_part':'2','volume_no':'II','title':'다권 BAT 제2권','official_document_page':'https://ieps.nier.go.kr/web/board/5/12/'},
             ]}
        ]}
        with tempfile.TemporaryDirectory() as td:
            package,catalog_path=self._setup(td,catalog,current_candidate())
            with patch('orchestrator.bat_collector.fetch_pdf_from_spec',return_value=('https://ieps.nier.go.kr/volume.pdf',b'%PDF-1.4\n%%EOF','TEST')):
                status=collect(package,catalog_path)
            rows=read_csv(package/'output'/'BAT_REFERENCES'/'document_index.csv')
            self.assertEqual(len(rows),2)
            self.assertEqual({r['document_part'] for r in rows},{'1','2'})
            self.assertEqual({r['volume_no'] for r in rows},{'I','II'})
            self.assertEqual(status['current_downloaded'],2)
            self.assertNotEqual(rows[0]['stored_path'],rows[1]['stored_path'])


if __name__=='__main__': unittest.main()
