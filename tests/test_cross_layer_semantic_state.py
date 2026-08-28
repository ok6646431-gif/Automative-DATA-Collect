import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'orchestrator'))

from cross_layer_review import company_action_layer
from document_semantics import company_document_access


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


class CrossLayerSemanticStateTests(unittest.TestCase):
    def test_company_index_context_does_not_enter_action_or_future_layer(self):
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td)
            write_csv(pkg / 'Management_Action_Ledger.csv', [], [
                'canonical_site_id','domain','site_name','year','action_name','description','disclosed_effect','source_file','action_id'
            ])
            write_csv(pkg / 'Event_Registry.csv', [], [
                'canonical_site_id','analysis_role','event_title','event_description','event_type','event_date_start','site_name','source_key','source_locator','event_id'
            ])
            write_csv(pkg / 'Document_Semantic_Candidates.csv', [
                {
                    'layer':'COMPANY_ACTION','domain':'CHEMICALS','report_year':'2026','document_id':'INDEX_DOC','page':'1',
                    'statement':'정책 목록에서 화학물질 관리 정책을 제공한다.','source_key':'CORP_DOCS','source_locator':'https://example.com/index',
                    'semantic_state':'REFERENCE_INDEX_CONTEXT','interpretation_boundary':'index only','semantic_id':'SEM_INDEX'
                },
                {
                    'layer':'FUTURE_DIRECTION','domain':'GHG_ENERGY','report_year':'2026','document_id':'STRATEGY_DOC','page':'1',
                    'statement':'2030년까지 온실가스 감축을 추진할 계획이다.','source_key':'CORP_DOCS','source_locator':'https://example.com/strategy',
                    'semantic_state':'PAGE_GROUNDED_EXTRACT','interpretation_boundary':'plan only','semantic_id':'SEM_STRATEGY'
                },
            ], [
                'layer','domain','report_year','document_id','page','statement','source_key','source_locator',
                'semantic_state','interpretation_boundary','semantic_id'
            ])
            rows = company_action_layer(pkg, {'mode':'COMPANY'})
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['layer'], 'FUTURE_DIRECTION')
            self.assertEqual(rows[0]['title'], 'STRATEGY_DOC p.1')
            self.assertEqual(rows[0]['semantic_state'], 'PAGE_GROUNDED_EXTRACT')

    def test_declared_policy_index_is_not_substantive_company_document(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'index.html'
            path.write_text('<html><body>환경 정책 감축 목표 관리 지침</body></html>', encoding='utf-8')
            row = {
                'document_type':'ENVIRONMENTAL_POLICY',
                'title':'ESG 정책 및 지침서',
                'notes':'Policy index only. Individual policies require separate evidence.'
            }
            self.assertEqual(company_document_access(row, path), 'COMPANY_INDEX_ONLY')
            substantive = {
                'document_type':'CLIMATE_ENERGY_POLICY',
                'title':'기후변화 대응',
                'notes':'Official climate response strategy page.'
            }
            self.assertEqual(company_document_access(substantive, path), 'SUBSTANTIVE')


if __name__ == '__main__':
    unittest.main()
