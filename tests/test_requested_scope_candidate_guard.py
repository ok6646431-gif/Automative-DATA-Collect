import unittest

from orchestrator.requested_scope_candidate_guard import STATE, unresolved_candidate_rows


class RequestedScopeCandidateGuardTests(unittest.TestCase):
    def test_partial_site_mapping_remains_blocking(self):
        scope = {
            'mode': 'SITE_SET',
            'target_candidate_ids': ['A', 'B', 'C', 'D'],
            'target_canonical_site_ids': {'SITE_A', 'SITE_B', 'SITE_C'},
            'unresolved_candidates': [
                {
                    'candidate_id': 'D',
                    'site_name_raw': '서울센터',
                    'address_raw': '서울특별시 강남구 테스트로 100',
                    'reason': 'NO_CONFIRMED_CANONICAL_SITE_MATCH',
                }
            ],
        }
        rows = unresolved_candidate_rows(scope)
        self.assertEqual(1, len(rows))
        self.assertEqual(STATE, rows[0]['completeness_state'])
        self.assertEqual('D', rows[0]['period'])
        self.assertIn('서울센터', rows[0]['evidence'])
        self.assertIn('NO_CONFIRMED_CANONICAL_SITE_MATCH', rows[0]['evidence'])

    def test_company_scope_does_not_create_site_candidate_blocker(self):
        scope = {
            'mode': 'COMPANY',
            'unresolved_candidates': [
                {'candidate_id': 'X', 'site_name_raw': '센터'}
            ],
        }
        self.assertEqual([], unresolved_candidate_rows(scope))

    def test_fully_bound_site_set_has_no_extra_row(self):
        scope = {
            'mode': 'SITE_SET',
            'target_candidate_ids': ['A', 'B'],
            'target_canonical_site_ids': {'SITE_A', 'SITE_B'},
            'unresolved_candidates': [],
        }
        self.assertEqual([], unresolved_candidate_rows(scope))


if __name__ == '__main__':
    unittest.main()
