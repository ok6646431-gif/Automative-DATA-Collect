import csv
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'orchestrator'))
from envinfo_zero_qa_gate import reconcile


class EnvinfoZeroGateTests(unittest.TestCase):
    def _coverage(self, root, states):
        with (root / 'Collection_Completeness.csv').open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['source','period_kind','period','expected','query_state','completeness_state'])
            writer.writeheader()
            for i, state in enumerate(states):
                writer.writerow({'source':'ENVINFO','period_kind':'YEAR','period':2023+i,'expected':'Y',
                                 'query_state':'COMPLETE','completeness_state':state})

    def test_zero_without_independent_evidence_does_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = reconcile(tmp, set(), {'expected_items':0,'checked_items':0,'status':'PASS','pass':True})
            self.assertEqual(result['status'], 'REVIEW_REQUIRED_ZERO_EVIDENCE')
            self.assertFalse(result['pass'])

    def test_verified_no_data_is_not_fake_content_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self._coverage(root,['NO_DATA_CONFIRMED','NO_DATA_CONFIRMED'])
            result = reconcile(root, set(), {'expected_items':0,'checked_items':0,'status':'PASS','pass':True})
            self.assertEqual(result['status'], 'NOT_APPLICABLE_VERIFIED_NO_DATA')
            self.assertTrue(result['pass'])

    def test_mapped_business_id_but_zero_disclosures_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self._coverage(root,['NO_DATA_CONFIRMED'])
            result=reconcile(root, {'CM123'}, {'expected_items':0,'status':'PASS','pass':True})
            self.assertFalse(result['pass'])

    def test_existing_positive_content_result_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            original={'expected_items':26,'checked_items':26,'status':'PASS','pass':True}
            self.assertEqual(reconcile(tmp,{'CM123'},original),original)

    def test_failed_query_never_proves_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self._coverage(root,['NO_DATA_CONFIRMED','QUERY_FAILED'])
            result = reconcile(root,set(),{'expected_items':0,'status':'PASS','pass':True})
            self.assertFalse(result['pass'])


if __name__=='__main__': unittest.main()
