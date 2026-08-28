import sys, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'orchestrator'))
from review_selection import series_signal


class TestZeroSemantics(unittest.TestCase):
    def test_cleansys_leading_zero_is_held_for_review(self):
        vals=[(2021,0),(2022,4707),(2023,7622),(2024,36913),(2025,42446)]
        self.assertEqual(series_signal(vals,4,'CLEANSYS_AIR'),'ZERO_SEMANTICS_REVIEW')

    def test_same_numeric_series_is_not_globally_reclassified(self):
        vals=[(2021,0),(2022,4707),(2023,7622),(2024,36913),(2025,42446)]
        self.assertNotEqual(series_signal(vals,4,'ENVINFO'),'ZERO_SEMANTICS_REVIEW')

    def test_all_zero_cleansys_series_is_not_treated_as_registration_jump(self):
        vals=[(2021,0),(2022,0),(2023,0),(2024,0)]
        self.assertEqual(series_signal(vals,4,'CLEANSYS_AIR'),'MIXED_OR_STABLE')


if __name__=='__main__': unittest.main()
