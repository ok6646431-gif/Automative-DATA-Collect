import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from orchestrator.bat_catalog_effective import materialize_effective_catalog
from orchestrator.bat_resolver import resolve

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests'/'regression_cases'/'samsung_ds'/'company_discovery.json'


def write_csv(path: Path, fields, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
        w.writeheader(); w.writerows(rows)


class SamsungDSBATContractTests(unittest.TestCase):
    def test_five_requested_ds_sites_resolve_to_current_semiconductor_ii(self):
        fixture=json.loads(FIXTURE.read_text(encoding='utf-8'))
        sites=fixture['domestic_site_candidates']
        requested=set(fixture['requested_scope']['candidate_ids'])
        selected=[s for s in sites if s['candidate_id'] in requested]
        self.assertEqual(len(selected),5)

        with tempfile.TemporaryDirectory() as td:
            pkg=Path(td)
            source_identity=[]; site_master=[]; envinfo=[]
            for index,site in enumerate(selected,1):
                canonical=f'SAMSUNG_DS_{index:02d}'
                source_id=f'ENV_SAMSUNG_DS_{index:02d}'
                source_identity.append({
                    'source_key':'ENVINFO','source_site_id':source_id,
                    'canonical_site_id':canonical,'match_status':'CONFIRMED',
                })
                site_master.append({
                    'canonical_site_id':canonical,
                    'canonical_site_name':site['site_name_raw'],
                    'identity_status':'CONFIRMED',
                })
                envinfo.append({
                    'compId':source_id,
                    'company_name':'삼성전자 주식회사',
                    'site_name':site['site_name_raw'],
                    'industry_name':'반도체 제조업',
                    'industry_code':'26111',
                })

            write_csv(pkg/'Source_Identity.csv',
                      ['source_key','source_site_id','canonical_site_id','match_status'],source_identity)
            write_csv(pkg/'Site_Master.csv',
                      ['canonical_site_id','canonical_site_name','identity_status'],site_master)
            write_csv(pkg/'output'/'ENVINFO'/'discovery.csv',
                      ['compId','company_name','site_name','industry_name','industry_code'],envinfo)
            (pkg/'Company_Profile.json').write_text(json.dumps({
                'request_id':fixture['request_id'],
                'requested_scope':fixture['requested_scope'],
            },ensure_ascii=False),encoding='utf-8')

            effective_path,advisories=materialize_effective_catalog(pkg)
            plan=resolve(pkg,effective_path,date(2026,9,5))

        semi=[r for r in plan['candidates'] if r.get('catalog_family')=='KBREF_FAMILY_SEMICONDUCTOR']
        self.assertEqual(len(semi),5,semi)
        self.assertEqual({r['catalog_id'] for r in semi},{'KBREF_SEMICONDUCTOR_II_2025'})
        self.assertEqual({r['site_name'] for r in semi},{s['site_name_raw'] for s in selected})
        self.assertTrue(all(r['candidate_role']=='PRIMARY' for r in semi),semi)
        self.assertTrue(all(r['applicability_state']=='STRONG_CANDIDATE' for r in semi),semi)
        self.assertTrue(all(r['collection_action']=='COLLECT' for r in semi),semi)
        self.assertNotIn('KBREF_SEMICONDUCTOR_2019',{r['catalog_id'] for r in plan['candidates']})

        by_id={a.get('catalog_id'):a for a in advisories}
        self.assertEqual(by_id['KBREF_SEMICONDUCTOR_II_2025']['reason_code'],'BREFOS_PUBLISHED_REVISION_BYTE_VERIFIED')
        self.assertEqual(by_id['KBREF_SEMICONDUCTOR_2019']['reason_code'],'SUPERSEDED_BY_BREFOS_VERIFIED_REVISION_II')


if __name__=='__main__': unittest.main()
