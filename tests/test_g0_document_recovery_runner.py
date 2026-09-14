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

    def test_missing_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                mod.run(td)


if __name__ == '__main__':
    unittest.main()
