import csv, json, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'orchestrator'))
from review_selection import run_review_selection, series_signal


def write_jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows)+'\n',encoding='utf-8')


class TestReviewSelection(unittest.TestCase):
    def test_long_term_signal_requires_four_observations(self):
        self.assertEqual(series_signal([(2022,1),(2023,2),(2024,3)]),'SHORT_SERIES')
        self.assertIn('DIRECTIONAL_UP',series_signal([(2021,1),(2022,2),(2023,3),(2024,4)]))

    def test_water_inventory_does_not_preselect_tn(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); src=root/'src'; pkg=root/'pkg'; pkg.mkdir()
            rows=[]
            for y in range(2020,2026):
                rows.append({'YEAR':str(y),'FACT_CODE':'W1','FACT_FNAME':'Test Water','WAST_NO':1,
                    'SS_AVRG_DNSTY':str(1+y-2020),'TN_AVRG_DNSTY':str(2+y-2020),'TP_AVRG_DNSTY':str(.1+y*.001),
                    'COD_AVRG_DNSTY':str(5+y-2020) if y<=2021 else '-',
                    'TOC_AVRG_DNSTY':str(3+y-2023) if y>=2023 else '-'})
            write_jsonl(src/'SOOSIRO_WATER'/'annual_rows.jsonl',rows)
            (src/'SOOSIRO_WATER'/'daily_rows.jsonl').write_text('',encoding='utf-8')
            for s in ['ENVINFO','PRTR','CHEM_STATS','CLEANSYS_AIR']: (src/s).mkdir(parents=True,exist_ok=True)
            for s in ['ENVINFO','PRTR','CHEM_STATS']: (src/s/'discovery.csv').write_text('search_year\n',encoding='utf-8')
            (src/'CLEANSYS_AIR'/'annual_rows.jsonl').write_text('',encoding='utf-8')
            (src/'PRTR'/'detail_table_rows.jsonl').write_text('',encoding='utf-8')
            (src/'CHEM_STATS'/'detail_table_rows.jsonl').write_text('',encoding='utf-8')
            run_review_selection(src,pkg,ROOT/'orchestrator'/'review_selection_protocol.json')
            inv=list(csv.DictReader((pkg/'Review_Metric_Inventory.csv').open(encoding='utf-8-sig')))
            metrics={r['metric']:r for r in inv if r['source']=='SOOSIRO_WATER'}
            self.assertTrue({'SS_CONC','TN_CONC','TP_CONC','COD_CONC','TOC_CONC'}.issubset(metrics))
            self.assertEqual(metrics['TN_CONC']['comparability'],'TREND_ELIGIBLE')
            self.assertEqual(metrics['COD_CONC']['comparability'],'CONTEXT_ONLY')
            self.assertIn('Do not stitch',metrics['COD_CONC']['definition_note'])

    def test_envinfo_action_ledger_uses_all_available_years(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); src=root/'src'; pkg=root/'pkg'; pkg.mkdir(); raw=src/'ENVINFO'/'raw_detail'; raw.mkdir(parents=True)
            html='''<html><table><caption>본사 / 사업장 현황</caption><tr><th>구분</th><th>사업장명</th></tr><tr><td>사업장</td><td>테스트사업장</td></tr></table><table><caption>대기·수질, 폐기물 및 화학물질 관련 투자 및 기술 도입 현황</caption><tr><td>설비명</td><td>PFC Scrubber NOx 저감장치</td><td>총사업기간</td><td>{year}.01.01 - {year}.12.31</td><td>총투자비</td><td>100 백만원</td><td>사업내용</td><td>NOx 저감</td><td>효과(절감량)</td><td>회사 공개효과</td></tr></table></html>'''
            for y in [2022,2023,2024]: (raw/f'{y}_S1_test.html').write_text(html.format(year=y),encoding='utf-8')
            (src/'ENVINFO'/'discovery.csv').write_text('year\n2022\n2023\n2024\n',encoding='utf-8')
            for s in ['PRTR','CHEM_STATS','CLEANSYS_AIR','SOOSIRO_WATER']: (src/s).mkdir(parents=True,exist_ok=True)
            for s in ['PRTR','CHEM_STATS']: (src/s/'discovery.csv').write_text('search_year\n',encoding='utf-8')
            for p in [src/'PRTR'/'detail_table_rows.jsonl',src/'CHEM_STATS'/'detail_table_rows.jsonl',src/'CLEANSYS_AIR'/'annual_rows.jsonl',src/'SOOSIRO_WATER'/'annual_rows.jsonl',src/'SOOSIRO_WATER'/'daily_rows.jsonl']: p.write_text('',encoding='utf-8')
            run_review_selection(src,pkg,ROOT/'orchestrator'/'review_selection_protocol.json')
            acts=list(csv.DictReader((pkg/'Management_Action_Ledger.csv').open(encoding='utf-8-sig')))
            self.assertEqual({r['year'] for r in acts},{'2022','2023','2024'})
            self.assertTrue(all('AIR' in r['domain'] for r in acts))
            self.assertEqual(len({r['action_id'] for r in acts}),3)
            self.assertTrue(all(r['in_requested_scope']=='YES' for r in acts))

    def test_site_set_scope_preserves_inventory_but_filters_display_and_topics(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); src=root/'src'; pkg=root/'pkg'; pkg.mkdir()
            rows=[]
            for y in range(2020,2026):
                rows.append({'YEAR':str(y),'FACT_CODE':'W1','FACT_FNAME':'Target Site','WAST_NO':1,'TN_AVRG_DNSTY':str(y-2019)})
            for y in range(2018,2026):
                rows.append({'YEAR':str(y),'FACT_CODE':'W2','FACT_FNAME':'Other Site','WAST_NO':1,'TN_AVRG_DNSTY':str(y-2017)})
            write_jsonl(src/'SOOSIRO_WATER'/'annual_rows.jsonl',rows)
            (src/'SOOSIRO_WATER'/'daily_rows.jsonl').write_text('',encoding='utf-8')
            for s in ['ENVINFO','PRTR','CHEM_STATS','CLEANSYS_AIR']: (src/s).mkdir(parents=True,exist_ok=True)
            for s in ['ENVINFO','PRTR','CHEM_STATS']: (src/s/'discovery.csv').write_text('search_year\n',encoding='utf-8')
            (src/'CLEANSYS_AIR'/'annual_rows.jsonl').write_text('',encoding='utf-8')
            (src/'PRTR'/'detail_table_rows.jsonl').write_text('',encoding='utf-8')
            (src/'CHEM_STATS'/'detail_table_rows.jsonl').write_text('',encoding='utf-8')
            (pkg/'Requested_Scope.json').write_text(json.dumps({'mode':'SITE_SET','label':'Target only','target_canonical_site_ids':[],'target_source_ids':{'SOOSIRO_WATER':['W1']}},ensure_ascii=False),encoding='utf-8')
            summary=run_review_selection(src,pkg,ROOT/'orchestrator'/'review_selection_protocol.json')
            inv=list(csv.DictReader((pkg/'Review_Metric_Inventory.csv').open(encoding='utf-8-sig')))
            self.assertEqual({r['source_site_id'] for r in inv},{'W1','W2'})
            self.assertTrue(all(r['in_requested_scope']=='YES' for r in inv if r['source_site_id']=='W1'))
            self.assertTrue(all(r['in_requested_scope']=='NO' for r in inv if r['source_site_id']=='W2'))
            plan=list(csv.DictReader((pkg/'Review_Display_Plan.csv').open(encoding='utf-8-sig')))
            self.assertEqual({r['site_name'] for r in plan},{'Target Site'})
            topics=list(csv.DictReader((pkg/'Review_Topic_Candidates.csv').open(encoding='utf-8-sig')))
            self.assertEqual({r['site_name'] for r in topics},{'Target Site'})
            cov=list(csv.DictReader((pkg/'Review_Source_Coverage.csv').open(encoding='utf-8-sig')))
            water=[r for r in cov if r['source']=='SOOSIRO_WATER'][0]
            self.assertEqual(water['raw_years'],'2018|2019|2020|2021|2022|2023|2024|2025')
            self.assertEqual(water['requested_scope_years'],'2020|2021|2022|2023|2024|2025')
            self.assertEqual(summary['scope_mode'],'SITE_SET')

    def test_current_entity_period_excludes_pre_start_years_from_target_series(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); src=root/'src'; pkg=root/'pkg'; pkg.mkdir()
            annual=[
                {'YEAR':str(y),'FACT_CODE':'W1','FACT_FNAME':'Target Site','WAST_NO':1,'TN_AVRG_DNSTY':str(y-2019)}
                for y in range(2020,2026)
            ]
            write_jsonl(src/'SOOSIRO_WATER'/'annual_rows.jsonl',annual)
            write_jsonl(src/'SOOSIRO_WATER'/'daily_rows.jsonl',[
                {'query_year':2021,'FACT_CODE':'W1','FACT_FNAME':'Target Site','WAST_NO':1,'TN_AVRG_DNSTY':'100'},
                {'query_year':2024,'FACT_CODE':'W1','FACT_FNAME':'Target Site','WAST_NO':1,'TN_AVRG_DNSTY':'10'},
            ])
            for s in ['ENVINFO','PRTR','CHEM_STATS','CLEANSYS_AIR']: (src/s).mkdir(parents=True,exist_ok=True)
            for s in ['ENVINFO','PRTR','CHEM_STATS']: (src/s/'discovery.csv').write_text('search_year\n',encoding='utf-8')
            (src/'CLEANSYS_AIR'/'annual_rows.jsonl').write_text('',encoding='utf-8')
            (src/'PRTR'/'detail_table_rows.jsonl').write_text('',encoding='utf-8')
            (src/'CHEM_STATS'/'detail_table_rows.jsonl').write_text('',encoding='utf-8')
            (pkg/'Requested_Scope.json').write_text(json.dumps({
                'mode':'SITE_SET','label':'Current company only','target_canonical_site_ids':[],
                'target_source_ids':{'SOOSIRO_WATER':['W1']},
                'current_legal_entity_active_period':{'start_year':2022,'end_year':None},
            },ensure_ascii=False),encoding='utf-8')

            summary=run_review_selection(src,pkg,ROOT/'orchestrator'/'review_selection_protocol.json')
            inv=list(csv.DictReader((pkg/'Review_Metric_Inventory.csv').open(encoding='utf-8-sig')))
            tn=[r for r in inv if r['source']=='SOOSIRO_WATER' and r['source_site_id']=='W1' and r['metric']=='TN_CONC'][0]
            self.assertEqual(tn['years'],'2022|2023|2024|2025')
            self.assertEqual(tn['observation_count'],'4')
            self.assertEqual(tn['in_requested_scope'],'YES')
            self.assertIn('legal entity active period',tn['definition_note'])

            cov=list(csv.DictReader((pkg/'Review_Source_Coverage.csv').open(encoding='utf-8-sig')))
            water=[r for r in cov if r['source']=='SOOSIRO_WATER'][0]
            self.assertEqual(water['raw_years'],'2020|2021|2022|2023|2024|2025')
            self.assertEqual(water['requested_scope_years'],'2022|2023|2024|2025')

            daily=list(csv.DictReader((pkg/'Water_Daily_Stats.csv').open(encoding='utf-8-sig')))
            tn_daily=[r for r in daily if r['source_site_id']=='W1' and r['metric']=='TN_CONC'][0]
            self.assertEqual(tn_daily['n'],'1')
            self.assertEqual(float(tn_daily['mean']),10.0)
            self.assertEqual(summary['current_legal_entity_active_period'],{'start_year':2022,'end_year':None})


if __name__=='__main__': unittest.main()
