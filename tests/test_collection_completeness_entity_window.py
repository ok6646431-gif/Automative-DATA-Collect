import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'orchestrator'))
from collection_completeness import apply_current_entity_period, query_row

class CollectionCompletenessEntityWindowTests(unittest.TestCase):
    def test_pre_entity_years_are_historical_not_blocking_gaps(self):
        rows=[
            query_row('PRTR',2020,False,False,False,'terms=0'),
            query_row('PRTR',2021,False,False,True,'terms=0'),
            query_row('PRTR',2022,True,False,True,'terms=2'),
        ]
        got=apply_current_entity_period(rows,{'legal_entity_active_period':{'start_year':2022}})
        self.assertEqual('OUTSIDE_CURRENT_ENTITY_PERIOD',got[0]['completeness_state'])
        self.assertEqual('N',got[0]['expected'])
        self.assertEqual('NOT_REQUIRED_CURRENT_ENTITY',got[0]['query_state'])
        self.assertEqual('OUTSIDE_CURRENT_ENTITY_PERIOD',got[1]['completeness_state'])
        self.assertEqual('Y',got[1]['data_present'])
        self.assertEqual('HISTORICAL_REFERENCE',got[1]['query_state'])
        self.assertEqual('DATA_PRESENT',got[2]['completeness_state'])
        self.assertEqual('Y',got[2]['expected'])

    def test_without_entity_boundary_existing_semantics_are_unchanged(self):
        rows=[query_row('PRTR',2020,False,False,False,'terms=0')]
        got=apply_current_entity_period(rows,{})
        self.assertEqual('UNQUERIED_PERIOD',got[0]['completeness_state'])
        self.assertEqual('Y',got[0]['expected'])

if __name__=='__main__': unittest.main()
