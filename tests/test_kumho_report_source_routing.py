import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.promote_kumho_stable_report_sources as promote


class KumhoReportSourceRoutingTest(unittest.TestCase):
    def _fixture(self):
        return {
            'documents': [
                {
                    'document_id': 'KUMHO_SUSTAINABILITY_2020',
                    'source_url': 'https://www.kkpc.com/download/?seq=4017',
                    'source_locator': promote.LANDING,
                    'expected_extension': 'pdf',
                    'verification_status': 'VERIFIED',
                },
                {
                    'document_id': 'KUMHO_SUSTAINABILITY_2021',
                    'source_url': 'https://www.kkpc.com/download/?seq=5173',
                    'source_locator': promote.LANDING,
                    'expected_extension': 'pdf',
                    'verification_status': 'VERIFIED',
                },
                {
                    'document_id': 'KUMHO_SUSTAINABILITY_2022',
                    'source_url': 'https://www.kkpc.com/download/?seq=6252',
                    'source_locator': promote.LANDING,
                    'expected_extension': 'pdf',
                    'verification_status': 'VERIFIED',
                },
                {
                    'document_id': 'KUMHO_SUSTAINABILITY_2023',
                    'source_url': 'https://www.kkpc.com/download/?seq=7019',
                    'source_locator': promote.LANDING,
                    'expected_extension': 'pdf',
                    'verification_status': 'VERIFIED',
                    'fallback_sources': [{
                        'source_url': promote.PROMOTIONS['KUMHO_SUSTAINABILITY_2023'],
                        'source_locator': promote.LANDING,
                        'expected_extension': 'pdf',
                        'verification_status': 'VERIFIED',
                    }],
                },
            ]
        }

    def test_promotes_verified_transport_routes_and_retains_old_primary(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'evidence.json'
            path.write_text(json.dumps(self._fixture()), encoding='utf-8')
            with patch.object(promote, 'PATH', path):
                promote.main()
            data = json.loads(path.read_text(encoding='utf-8'))
            by_id = {d['document_id']: d for d in data['documents']}
            expected_old = {
                'KUMHO_SUSTAINABILITY_2020': 'https://www.kkpc.com/download/?seq=4017',
                'KUMHO_SUSTAINABILITY_2021': 'https://www.kkpc.com/download/?seq=5173',
                'KUMHO_SUSTAINABILITY_2022': 'https://www.kkpc.com/download/?seq=6252',
                'KUMHO_SUSTAINABILITY_2023': 'https://www.kkpc.com/download/?seq=7019',
            }
            for did, preferred in promote.PROMOTIONS.items():
                doc = by_id[did]
                self.assertEqual(doc['source_url'], preferred)
                self.assertEqual(doc['verification_status'], 'VERIFIED')
                fallback_urls = [x['source_url'] for x in doc.get('fallback_sources', [])]
                self.assertIn(expected_old[did], fallback_urls)
                self.assertNotIn(preferred, fallback_urls)

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'evidence.json'
            path.write_text(json.dumps(self._fixture()), encoding='utf-8')
            with patch.object(promote, 'PATH', path):
                promote.main()
                once = path.read_text(encoding='utf-8')
                promote.main()
                twice = path.read_text(encoding='utf-8')
            self.assertEqual(once, twice)


if __name__ == '__main__':
    unittest.main()
