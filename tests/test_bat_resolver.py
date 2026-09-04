import csv, json, tempfile, unittest
from datetime import date
from pathlib import Path

from orchestrator.bat_resolver import resolve


def write_csv(path,rows,fields):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def read_rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


class BATResolverTests(unittest.TestCase):
    def _package(self,td):
        p=Path(td)/'assembled'; p.mkdir()
        write_csv(p/'Site_Master.csv',[{
            'canonical_site_id':'SITE_A','canonical_site_name':'테스트 광주공장','identity_status':'CONFIRMED'
        }],['canonical_site_id','canonical_site_name','identity_status'])
        write_csv(p/'Source_Identity.csv',[{
            'source_key':'CHEM_STATS','source_site_id':'A1','canonical_site_id':'SITE_A','match_status':'CONFIRMED'
        },{
            'source_key':'ENVINFO','source_site_id':'E1','canonical_site_id':'SITE_A','match_status':'CONFIRMED'
        }],['source_key','source_site_id','canonical_site_id','match_status'])
        write_csv(p/'output'/'CHEM_STATS'/'discovery.csv',[{
            'bplcId':'A1','induty':'타이어 및 튜브 제조업','ksic':'22111','bplcNm':'테스트타이어 광주공장'
        }],['bplcId','induty','ksic','bplcNm'])
        write_csv(p/'output'/'ENVINFO'/'attachment_index.csv',[{
            'compId':'E1','section_title':'대기 및 에너지 관리','document_category':'ENV_MANAGEMENT','original_filename':'보일러 운영 및 연료사용 관리계획.pdf'
        }],['compId','section_title','document_category','original_filename'])
        (p/'Company_Profile.json').write_text(json.dumps({'request_id':'test','site_candidates':[]}),encoding='utf-8')
        return p

    def test_one_site_can_have_future_primary_and_common_boiler_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            p=self._package(td)
            plan=resolve(p,as_of=date(2026,9,4))
            rows=read_rows(p/'BAT_Applicability_Candidates.csv')
            site=[r for r in rows if r['canonical_site_id']=='SITE_A']
            rubber=[r for r in site if r['catalog_id']=='KBREF_RUBBER_PRODUCTS_PENDING_2029']
            boiler=[r for r in site if r['catalog_id']=='KBREF_COMMON_BOILER_2021']
            electric_steam=[r for r in site if r['catalog_family']=='KBREF_FAMILY_ELECTRIC_STEAM']
            self.assertEqual(len(rubber),1)
            self.assertEqual(rubber[0]['candidate_role'],'PRIMARY')
            self.assertEqual(rubber[0]['candidate_state'],'FUTURE_PRIMARY_CANDIDATE')
            self.assertEqual(rubber[0]['collection_action'],'WAIT_FOR_PUBLICATION')
            self.assertIn('타이어 및 튜브 제조업',rubber[0]['matched_industry_terms'])
            self.assertEqual(len(boiler),1)
            self.assertEqual(boiler[0]['candidate_role'],'COMMON_UTILITY')
            self.assertEqual(boiler[0]['collection_action'],'REVIEW_BEFORE_COLLECTION')
            self.assertEqual(electric_steam,[])
            self.assertGreaterEqual(plan['candidate_count'],2)

    def test_company_name_alone_does_not_create_rubber_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'assembled'; p.mkdir()
            write_csv(p/'Site_Master.csv',[{'canonical_site_id':'SITE_A','canonical_site_name':'금호타이어 광주공장','identity_status':'CONFIRMED'}],['canonical_site_id','canonical_site_name','identity_status'])
            write_csv(p/'Source_Identity.csv',[],['source_key','source_site_id','canonical_site_id','match_status'])
            (p/'Company_Profile.json').write_text(json.dumps({'request_id':'x','company_display_name':'금호타이어'}),encoding='utf-8')
            resolve(p,as_of=date(2026,9,4))
            rows=read_rows(p/'BAT_Applicability_Candidates.csv')
            self.assertFalse(any(r['catalog_id']=='KBREF_RUBBER_PRODUCTS_PENDING_2029' for r in rows))

    def test_diagnostic_rubber_process_can_create_future_secondary_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'assembled'; p.mkdir()
            write_csv(p/'Site_Master.csv',[{'canonical_site_id':'SITE_A','canonical_site_name':'테스트 공장','identity_status':'CONFIRMED'}],['canonical_site_id','canonical_site_name','identity_status'])
            write_csv(p/'Source_Identity.csv',[],['source_key','source_site_id','canonical_site_id','match_status'])
            write_csv(p/'Management_Action_Ledger.csv',[{
                'canonical_site_id':'SITE_A','action_name':'가황 공정 개선','description':'가황 공정 운전조건 개선','disclosed_effect':'','domain':'AIR'
            }],['canonical_site_id','action_name','description','disclosed_effect','domain'])
            (p/'Company_Profile.json').write_text(json.dumps({'request_id':'x'}),encoding='utf-8')
            resolve(p,as_of=date(2026,9,4))
            rows=read_rows(p/'BAT_Applicability_Candidates.csv')
            rubber=[r for r in rows if r['catalog_id']=='KBREF_RUBBER_PRODUCTS_PENDING_2029']
            self.assertEqual(len(rubber),1)
            self.assertEqual(rubber[0]['candidate_role'],'SECONDARY_PROCESS')
            self.assertEqual(rubber[0]['candidate_state'],'FUTURE_TECHNICAL_CANDIDATE')
            self.assertEqual(rubber[0]['collection_action'],'WAIT_FOR_PUBLICATION')

    def test_pure_industry_reference_rejects_process_only_generic_term(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'assembled'; p.mkdir()
            write_csv(p/'Site_Master.csv',[{'canonical_site_id':'SITE_A','canonical_site_name':'타이어 테스트 공장','identity_status':'CONFIRMED'}],['canonical_site_id','canonical_site_name','identity_status'])
            write_csv(p/'Source_Identity.csv',[],['source_key','source_site_id','canonical_site_id','match_status'])
            write_csv(p/'Management_Action_Ledger.csv',[{
                'canonical_site_id':'SITE_A','action_name':'발전 설비 점검','description':'자가발전 설비 정기점검','disclosed_effect':'','domain':'GHG_ENERGY'
            }],['canonical_site_id','action_name','description','disclosed_effect','domain'])
            (p/'Company_Profile.json').write_text(json.dumps({'request_id':'x'}),encoding='utf-8')
            resolve(p,as_of=date(2026,9,4))
            rows=read_rows(p/'BAT_Applicability_Candidates.csv')
            self.assertFalse(any(r['catalog_family']=='KBREF_FAMILY_ELECTRIC_STEAM' for r in rows))

    def test_single_channel_secondary_process_requires_review_before_collection(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'assembled'; p.mkdir()
            write_csv(p/'Site_Master.csv',[{'canonical_site_id':'SITE_A','canonical_site_name':'테스트 공장','identity_status':'CONFIRMED'}],['canonical_site_id','canonical_site_name','identity_status'])
            write_csv(p/'Source_Identity.csv',[],['source_key','source_site_id','canonical_site_id','match_status'])
            write_csv(p/'Management_Action_Ledger.csv',[{
                'canonical_site_id':'SITE_A','action_name':'소각로 개선','description':'사업장 자체 소각로 운전 개선','disclosed_effect':'','domain':'AIR'
            }],['canonical_site_id','action_name','description','disclosed_effect','domain'])
            (p/'Company_Profile.json').write_text(json.dumps({'request_id':'x'}),encoding='utf-8')
            catalog=Path(td)/'catalog.json'
            catalog.write_text(json.dumps({'entries':[{
                'catalog_id':'TEST_INCINERATION','catalog_family':'TEST_FAMILY','preferred':True,'revision_generation':'1',
                'reference_kind':'INDUSTRY_OR_SECONDARY_PROCESS','publication_status':'PUBLISHED','legal_status':'PUBLISHED_REFERENCE',
                'industry_terms':['폐기물 소각업'],'process_terms':['소각로'],'utility_terms':[],
                'default_role':'SECONDARY_PROCESS','industry_match_role':'PRIMARY','process_match_role':'SECONDARY_PROCESS',
                'collection_policy':'COLLECT_WHEN_MATCHED','official_source_locator':'https://example.invalid/test.pdf'
            }]},ensure_ascii=False),encoding='utf-8')
            resolve(p,catalog_path=catalog,as_of=date(2026,9,4))
            rows=read_rows(p/'BAT_Applicability_Candidates.csv')
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['candidate_role'],'SECONDARY_PROCESS')
            self.assertEqual(rows[0]['applicability_state'],'SUPPORTING_CANDIDATE')
            self.assertEqual(rows[0]['collection_action'],'REVIEW_BEFORE_COLLECTION')

    def test_superseded_family_revision_never_becomes_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'assembled'; p.mkdir()
            write_csv(p/'Site_Master.csv',[{'canonical_site_id':'SITE_A','canonical_site_name':'발전 테스트','identity_status':'CONFIRMED'}],['canonical_site_id','canonical_site_name','identity_status'])
            write_csv(p/'Source_Identity.csv',[{'source_key':'CHEM_STATS','source_site_id':'A1','canonical_site_id':'SITE_A','match_status':'CONFIRMED'}],['source_key','source_site_id','canonical_site_id','match_status'])
            write_csv(p/'output'/'CHEM_STATS'/'discovery.csv',[{'bplcId':'A1','induty':'화력 발전업','ksic':'35113'}],['bplcId','induty','ksic'])
            (p/'Company_Profile.json').write_text(json.dumps({'request_id':'x'}),encoding='utf-8')
            resolve(p,as_of=date(2026,9,4))
            rows=read_rows(p/'BAT_Applicability_Candidates.csv')
            family=[r for r in rows if r['catalog_family']=='KBREF_FAMILY_ELECTRIC_STEAM']
            self.assertEqual(len(family),1)
            self.assertEqual(family[0]['catalog_id'],'KBREF_ELECTRIC_STEAM_II_2022')
            self.assertEqual(family[0]['revision_generation'],'II')


if __name__=='__main__': unittest.main()
