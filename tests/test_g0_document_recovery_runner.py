import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator import g0_document_recovery_runner as mod


class FreshProcessDocumentRecoveryTests(unittest.TestCase):
    def test_blocking_years_ignore_nonblocking_and_strongly_delivered_years(self):
        documents = {
            'documents': [
                {
                    'document_type': 'SUSTAINABILITY_REPORT',
                    'report_year': 2024,
                    'verification_status': 'SOURCE_VERIFIED',
                    'source_url': 'https://official.example/2024.pdf',
                }
            ],
            'gaps': [
                {'document_type': 'SUSTAINABILITY_REPORT', 'year': 2023, 'blocking': True},
                {'document_type': 'SUSTAINABILITY_REPORT', 'year': 2024, 'blocking': True},
                {'document_type': 'SUSTAINABILITY_REPORT', 'year': 2025, 'blocking': False},
                {'document_type': 'OTHER', 'year': 2022, 'blocking': True},
            ],
        }
        self.assertEqual([2023], mod.blocking_sustainability_years(documents))

    def test_no_blocking_report_gap_skips_all_live_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            company = {'current_legal_name': '테스트 주식회사'}
            documents = {
                'documents': [
                    {
                        'document_type': 'SUSTAINABILITY_REPORT',
                        'report_year': 2024,
                        'verification_status': 'SOURCE_VERIFIED',
                        'source_url': 'https://official.example/2024.pdf',
                    }
                ],
                'gaps': [
                    {'document_type': 'SUSTAINABILITY_REPORT', 'year': 2025, 'blocking': False},
                ],
            }
            audit = {'stages': {}, 'gate_status': 'PASS'}
            (root / 'company_discovery.json').write_text(json.dumps(company), encoding='utf-8')
            (root / 'document_evidence.json').write_text(json.dumps(documents), encoding='utf-8')
            (root / 'Discovery_Audit.json').write_text(json.dumps(audit), encoding='utf-8')

            with patch.object(mod.g0_generic_js_report_recovery, 'enrich') as live_recovery:
                result = mod.run(root, budget_seconds=17)

            self.assertEqual('NOT_NEEDED', result['status'])
            self.assertEqual([], result['blocking_years_before'])
            live_recovery.assert_not_called()
            written = json.loads((root / 'Discovery_Audit.json').read_text(encoding='utf-8'))
            stage = written['stages']['fresh_process_document_recovery']
            self.assertEqual(17, stage['budget_seconds'])
            self.assertEqual('NOT_NEEDED', stage['status'])

    def test_final_gate_keeps_report_gaps_deferred_but_identity_fail_closed(self):
        from contextlib import ExitStack

        identity_cases = [([], 'PASS'),
                          ([{'code': 'LEGAL_ENTITY_AMBIGUOUS', 'detail': 'two entities'}],
                           'REVIEW_REQUIRED')]
        for blockers, expected in identity_cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                discovery = {
                    'current_legal_name': '테스트 주식회사',
                    'company_verification_state': 'VERIFIED',
                    'unresolved_items': list(blockers),
                }
                documents = {'documents': [], 'gaps': [{
                    'gap_id': 'G2025', 'document_type': 'SUSTAINABILITY_REPORT',
                    'year': 2025, 'status': 'DISCOVERY_GAP', 'blocking': True,
                }]}
                audit = {'stages': {'official_site': {'resolved_official_root':
                          'https://official.example'}}, 'gate_status': 'REVIEW_REQUIRED'}
                (root / 'company_discovery.json').write_text(json.dumps(discovery), encoding='utf-8')
                (root / 'document_evidence.json').write_text(json.dumps(documents), encoding='utf-8')
                (root / 'Discovery_Audit.json').write_text(json.dumps(audit), encoding='utf-8')
                # Do not call the network or rewrite documentary evidence in this
                # test: it isolates the actual post-recovery gate-write ordering.
                document_steps = [
                    (mod.g0_report_entity_policy, 'normalize'),
                    (mod.runtime, '_merge_verified_document_routes'),
                    (mod.document_language_preference, 'recover_verified_korean_siblings'),
                    (mod.g0_report_finalizer, 'finalize'),
                    (mod.g0_report_catalog_policy, 'normalize_verified_catalog_gaps'),
                    (mod.g0_first_publication_recovery, 'recover'),
                    (mod.g0_entity_window_normalization, 'normalize'),
                ]
                with ExitStack() as stack:
                    stack.enter_context(patch.object(
                        mod, '_seeded_generic_js_recovery',
                        side_effect=lambda d, docs, a, stage: docs))
                    stack.enter_context(patch.object(
                        mod, '_target_years_remaining', return_value=[]))
                    for module, name in document_steps:
                        stack.enter_context(patch.object(
                            module, name, side_effect=lambda d, docs, a: docs))
                    result = mod.run(root, budget_seconds=5)
                written_audit = json.loads((root / 'Discovery_Audit.json').read_text(encoding='utf-8'))
                written_discovery = json.loads((root / 'company_discovery.json').read_text(encoding='utf-8'))
                written_documents = json.loads((root / 'document_evidence.json').read_text(encoding='utf-8'))
                self.assertEqual(expected, written_audit['gate_status'])
                self.assertEqual(expected, result['final_gate_status'])
                self.assertEqual(1, written_audit['stages']['promotion_policy']['deferred_review_count'])
                self.assertEqual(blockers, written_discovery['unresolved_items'])
                self.assertTrue(written_documents['gaps'][0]['blocking'])

    def test_missing_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                mod.run(td)


if __name__ == '__main__':
    unittest.main()
