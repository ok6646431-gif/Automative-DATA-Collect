import csv, json, tempfile, unittest
from datetime import date
from pathlib import Path

from orchestrator.bat_resolver import resolve


def write_csv(path,rows,fields):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


class BATResolverTests(unittest.TestCase):
    def _package(self,td):
        p=Path(td)/'assembled'; p.mkdir()
        write_csv(p/'Site_Master.csv',[{
            'canonical_site_id':'SITE_A','canonical_site_name':'테스트 광주공장','identity_status':'CONFIRMED'
        }],['canonical_site_id','canonical_site_name','identity_status'])
        write_csv(p/'Source_Identity.csv',[{
            'source_key':'CHEM_STATS','source_site_id':'A1','canonical_site_id':'SITE_A','identity_status':'CONFIRMED'
        },{
            'source_key':'ENVINFO','source_site_id':'E1','canonical_site_id':'SITE_A','identity_status':'CONFIRMED'
        }],['source_key','source_site_id','canonical_site_id','identity_status'])
        write_csv(p/'output'/'CHEM_STATS'/'discovery.csv',[{
            'bplcId':'A1','induty_nm':'타이어 및 튜브 제조업','ksic':'22111','bplcNm':'테스트타이어 광주공장'
        }],['bplcId','induty_nm','ksic','bplcNm'])
        write_csv(p/'output'/'ENVINFO'/'attachment_index.csv',[{
            'compId':'E1','section_title':'대기 및 에너지 관리','document_category':'ENV_MANAGEMENT','original_filename':'보일러 운영 및 연료사용 관리계획.pdf'
        }],['compId','section_title','document_category','original_filename'])
        (p/'Company_Profile.json').write_text(json.dumps({'request_id':'test','site_candidates':[]}),encoding='utf-8')
        return p

    def test_one_site_can_have_future_primary_and_common_utility_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            p=self._package(td)
            plan=resolve(p,as_of=date(2026,9,4))
            rows=list(csv.DictReader((p/'BAT_Applicability_Candidates.csv').open(encoding='utf-8-sig')))
            site=[r for r in rows if r['canonical_site_id']=='SITE_A']
            rubber=[r for r in site if r['catalog_id']=='KBREF_RUBBER_PRODUCTS_PENDING_2029']
            steam=[r for r in site if r['catalog_id']=='KBREF_ELECTRIC_STEAM_II_2022']
            self.assertEqual(len(rubber),1)
            self.assertEqual(rubber[0]['candidate_role'],'PRIMARY')
            self.assertEqual(rubber[0]['candidate_state'],'FUTURE_PRIMARY_CANDIDATE')
            self.assertEqual(rubber[0]['collection_action'],'WAIT_FOR_PUBLICATION')
            self.assertEqual(len(steam),1)
            self.assertEqual(steam[0]['candidate_role'],'COMMON_UTILITY')
            self.assertIn(steam[0]['collection_action'],{'COLLECT','REVIEW_BEFORE_COLLECTION'})
            self.assertGreaterEqual(plan['candidate_count'],2)

    def test_company_name_alone_does_not_create_rubber_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'assembled'; p.mkdir()
            write_csv(p/'Site_Master.csv',[{'canonical_site_id':'SITE_A','canonical_site_name':'금호타이어 광주공장','identity_status':'CONFIRMED'}],['canonical_site_id','canonical_site_name','identity_status'])
            write_csv(p/'Source_Identity.csv',[],['source_key','source_site_id','canonical_site_id','identity_status'])
            (p/'Company_Profile.json').write_text(json.dumps({'request_id':'x','company_display_name':'금호타이어'}),encoding='utf-8')
            resolve(p,as_of=date(2026,9,4))
            rows=list(csv.DictReader((p/'BAT_Applicability_Candidates.csv').open(encoding='utf-8-sig')))
            self.assertFalse(any(r['catalog_id']=='KBREF_RUBBER_PRODUCTS_PENDING_2029' for r in rows))


if __name__=='__main__': unittest.main()
