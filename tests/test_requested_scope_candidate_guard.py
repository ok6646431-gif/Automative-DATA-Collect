import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator import requested_scope_candidate_guard as mod

STATE = mod.STATE
unresolved_candidate_rows = mod.unresolved_candidate_rows


class RequestedScopeCandidateGuardTests(unittest.TestCase):
    def _partial_scope(self):
        return {
            'mode': 'SITE_SET',
            'label': '테스트 국내 사업장',
            'target_candidate_ids': ['A', 'B', 'C', 'D'],
            'target_canonical_site_ids': {'SITE_A', 'SITE_B', 'SITE_C'},
            'target_source_ids': {},
            'unresolved_candidates': [
                {
                    'candidate_id': 'D',
                    'site_name_raw': '서울센터',
                    'address_raw': '서울특별시 강남구 테스트로 100',
                    'reason': 'NO_CONFIRMED_CANONICAL_SITE_MATCH',
                }
            ],
        }

    def _colocated_profile(self):
        return {
            'company_id': 'COMP_TEST',
            'company_display_name': '테스트화학 주식회사',
            'requested_company_name': '테스트화학',
            'site_candidates': [
                {
                    'candidate_id': 'R',
                    'site_name_raw': '울산고무공장',
                    'address_raw': '울산광역시 남구 상개로 64',
                    'verification_state': 'VERIFIED',
                    'identity_status': 'CONFIRMED',
                },
                {
                    'candidate_id': 'L',
                    'site_name_raw': '울산 LATEX공장',
                    'address_raw': '울산광역시 남구 상개로64',
                    'verification_state': 'VERIFIED',
                    'identity_status': 'CONFIRMED',
                },
            ],
            'requested_scope': {'mode': 'SITE_SET', 'candidate_ids': ['R', 'L']},
        }

    def _colocated_scope(self):
        return {
            'mode': 'SITE_SET',
            'label': '울산 공식 거점',
            'target_candidate_ids': ['R', 'L'],
            'target_canonical_site_ids': {'SITE_R'},
            'target_source_ids': {'ENVINFO': {'E1'}, 'PRTR': {'P1'}},
            'unresolved_candidates': [
                {
                    'candidate_id': 'L',
                    'site_name_raw': '울산 LATEX공장',
                    'address_raw': '울산광역시 남구 상개로64',
                    'reason': 'COLOCATED_OFFICIAL_UNIT_NOT_DISTINCTLY_CONFIRMED',
                }
            ],
        }

    def _write_table(self, path, rows):
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _write_colocated_evidence(self, root, include_prtr=True, include_latex=False):
        self._write_table(root / 'Site_Master.csv', [
            {
                'canonical_site_id': 'SITE_R',
                'canonical_site_name': '테스트화학 울산고무',
                'canonical_address_key': '울산남구상개로64',
                'identity_status': 'CONFIRMED',
            }
        ])
        rows = [
            {
                'source_key': 'ENVINFO', 'source_site_id': 'E1',
                'source_site_name_raw': '테스트화학 울산고무',
                'source_address_raw': '울산광역시 남구 상개로 64',
                'canonical_site_id': 'SITE_R', 'match_status': 'CONFIRMED',
            }
        ]
        if include_prtr:
            rows.append({
                'source_key': 'PRTR', 'source_site_id': 'P1',
                'source_site_name_raw': '테스트화학(주)울산고무공장',
                'source_address_raw': '울산광역시 남구 상개로 64',
                'canonical_site_id': 'SITE_R', 'match_status': 'CONFIRMED',
            })
        if include_latex:
            rows.append({
                'source_key': 'CHEM_STATS', 'source_site_id': 'C1',
                'source_site_name_raw': '테스트화학 울산 LATEX공장',
                'source_address_raw': '울산광역시 남구 상개로 64',
                'canonical_site_id': '', 'match_status': 'REVIEW_REQUIRED',
            })
        self._write_table(root / 'Source_Identity.csv', rows)

    def test_partial_site_mapping_remains_blocking(self):
        rows = unresolved_candidate_rows(self._partial_scope())
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

    def test_colocated_unit_can_resolve_collection_scope_without_identity_merge(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            profile = self._colocated_profile()
            self._write_colocated_evidence(root)
            relations, remaining = mod.resolve_collection_relations(
                root, profile, self._colocated_scope()
            )

            self.assertEqual([], remaining)
            self.assertEqual(1, len(relations))
            relation = relations[0]
            self.assertEqual('L', relation['candidate_id'])
            self.assertEqual(mod.RELATION, relation['relation_type'])
            self.assertEqual('COLLECTION_ONLY', relation['resolution_scope'])
            self.assertFalse(relation['identity_merge'])
            self.assertEqual('SITE_R', relation['coverage_canonical_site_id'])
            self.assertEqual(['ENVINFO', 'PRTR'], relation['corroborating_source_keys'])

    def test_colocated_relation_stays_unresolved_with_only_one_address_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            profile = self._colocated_profile()
            self._write_colocated_evidence(root, include_prtr=False)
            relations, remaining = mod.resolve_collection_relations(
                root, profile, self._colocated_scope()
            )

            self.assertEqual([], relations)
            self.assertEqual('L', remaining[0]['candidate_id'])

    def test_colocated_relation_stays_unresolved_when_distinct_source_row_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            profile = self._colocated_profile()
            self._write_colocated_evidence(root, include_latex=True)
            relations, remaining = mod.resolve_collection_relations(
                root, profile, self._colocated_scope()
            )

            self.assertEqual([], relations)
            self.assertEqual('L', remaining[0]['candidate_id'])

    def test_archive_audit_cannot_report_complete_with_one_unresolved_requested_site(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            profile = root / 'Company_Profile.json'
            profile.write_text(json.dumps({
                'company_id': 'COMP_TEST',
                'company_display_name': '테스트 주식회사',
            }, ensure_ascii=False), encoding='utf-8')
            (root / 'Integration_Summary.json').write_text(
                json.dumps({'company_id': 'COMP_TEST'}, ensure_ascii=False), encoding='utf-8'
            )
            (root / 'Master_Manifest.json').write_text(
                json.dumps({'package_health': 'PASS'}, ensure_ascii=False), encoding='utf-8'
            )
            (root / 'REVIEW_REQUIRED.json').write_text('[]', encoding='utf-8')

            def fake_base_audit(package_root, profile_path, request_path=None, evidence_path=None):
                row = {
                    'source': 'ENVINFO', 'period_kind': 'YEAR', 'period': '2024',
                    'expected': 'Y', 'query_state': 'COMPLETE', 'data_present': 'Y',
                    'completeness_state': 'DATA_PRESENT', 'evidence': 'ok', 'user_note': '',
                }
                mod.base.write_csv(root / 'Collection_Completeness.csv', [row])
                mod.base.write_csv(root / 'Collection_No_Data.csv', [])
                summary = {
                    'schema_version': '1.2', 'status': 'COMPLETE', 'scope_mode': 'SITE_SET',
                    'scope_label': '테스트 국내 사업장', 'target_candidate_ids': ['A', 'B', 'C', 'D'],
                    'target_canonical_site_ids': ['SITE_A', 'SITE_B', 'SITE_C'],
                    'checked_items': 1, 'complete_items': 1, 'incomplete_items': 0,
                    'warning_items': 0, 'no_data_confirmed_items': 0,
                    'outside_current_entity_items': 0, 'incomplete_keys': [],
                    'warnings': [], 'no_data_confirmed': [], 'outside_current_entity': [],
                    'envinfo_attachment_scope': {
                        'company_raw_failed': 0, 'requested_scope_failed': 0,
                        'outside_scope_failed': 0,
                    },
                    'principles': [],
                }
                (root / 'Collection_Completeness.json').write_text(
                    json.dumps(summary, ensure_ascii=False), encoding='utf-8'
                )
                return summary

            with (
                patch.object(mod.base, 'audit_collection_for_requested_scope', side_effect=fake_base_audit),
                patch.object(mod, 'resolve_requested_scope', return_value=self._partial_scope()),
            ):
                result = mod.audit_collection_for_requested_scope(root, profile)

            self.assertEqual('REVIEW_REQUIRED', result['status'])
            self.assertEqual(1, result['incomplete_items'])
            self.assertTrue(any(STATE in key for key in result['incomplete_keys']))
            self.assertEqual('D', result['unresolved_requested_candidates'][0]['candidate_id'])
            manifest = json.loads((root / 'Master_Manifest.json').read_text(encoding='utf-8'))
            self.assertEqual('DEGRADED', manifest['package_health'])
            self.assertEqual('REVIEW_REQUIRED', manifest['validation'])
            review = json.loads((root / 'REVIEW_REQUIRED.json').read_text(encoding='utf-8'))
            self.assertTrue(any(item.get('issue_type') == STATE for item in review))


if __name__ == '__main__':
    unittest.main()
