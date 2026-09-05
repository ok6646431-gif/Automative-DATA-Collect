import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.bat_catalog_audit import audit_catalog


class BATCatalogAuditTests(unittest.TestCase):
    def test_production_catalog_has_no_hard_integrity_errors(self):
        payload = audit_catalog()
        self.assertEqual(payload['status'], 'PASS', payload['errors'])
        self.assertEqual(payload['summary']['error_count'], 0)
        self.assertGreater(payload['summary']['family_count'], 0)

    def _audit(self, entries):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = root / 'catalog.json'
            overrides = root / 'missing-overrides.json'
            catalog.write_text(json.dumps({'schema_version':'test','entries':entries}, ensure_ascii=False), encoding='utf-8')
            return audit_catalog(catalog, overrides)

    @staticmethod
    def _entry(catalog_id, family='FAMILY_A', preferred=True, sha=''):
        return {
            'catalog_id': catalog_id,
            'catalog_family': family,
            'preferred': preferred,
            'revision_generation': 'I',
            'publication_year': 2024,
            'title': catalog_id,
            'authority': '국립환경과학원',
            'publication_status': 'PUBLISHED',
            'collection_policy': 'COLLECT_WHEN_MATCHED' if preferred else 'AUDIT_ONLY_SUPERSEDED',
            'official_source_locator': 'https://example.invalid/official',
            'official_document_page': 'https://example.invalid/official',
            'official_pdf_url': 'https://example.invalid/file.pdf' if sha else '',
            'official_pdf_sha256': sha,
        }

    def test_duplicate_catalog_id_is_hard_error(self):
        payload = self._audit([self._entry('BAT_A'), self._entry('BAT_A', preferred=False)])
        self.assertEqual(payload['status'], 'FAIL')
        self.assertIn('DUPLICATE_CATALOG_ID', {e['code'] for e in payload['errors']})

    def test_multiple_preferred_revision_generations_are_hard_error(self):
        a = self._entry('BAT_A')
        b = self._entry('BAT_B')
        b['revision_generation'] = 'II'
        b['publication_year'] = 2025
        payload = self._audit([a, b])
        self.assertIn('MULTIPLE_PREFERRED_REVISIONS', {e['code'] for e in payload['errors']})

    def test_missing_pdf_hash_is_warning_not_hard_error(self):
        payload = self._audit([self._entry('BAT_A')])
        self.assertEqual(payload['status'], 'PASS')
        self.assertIn('PREFERRED_PUBLISHED_PDF_NOT_BYTE_VERIFIED', {w['code'] for w in payload['warnings']})

    def test_complete_multi_part_revision_counts_as_byte_verified(self):
        e = self._entry('BAT_MULTI')
        e['official_documents'] = [
            {
                'document_part': f'PART_{i}',
                'title': f'part {i}',
                'official_pdf_url': f'https://example.invalid/part-{i}.pdf',
                'official_pdf_sha256': chr(96+i) * 64,
            }
            for i in range(1, 5)
        ]
        payload = self._audit([e])
        codes = {w['code'] for w in payload['warnings']}
        self.assertEqual(payload['status'], 'PASS', payload['errors'])
        self.assertNotIn('PREFERRED_PUBLISHED_PDF_NOT_BYTE_VERIFIED', codes)
        self.assertEqual(payload['summary']['effective_byte_verified_preferred_count'], 1)

    def test_incomplete_multi_part_revision_remains_visible(self):
        e = self._entry('BAT_MULTI')
        e['official_documents'] = [
            {
                'document_part': 'PART_1',
                'official_pdf_url': 'https://example.invalid/part-1.pdf',
                'official_pdf_sha256': 'a' * 64,
            },
            {
                'document_part': 'PART_2',
                'official_pdf_url': 'https://example.invalid/part-2.pdf',
                'official_pdf_sha256': '',
            },
        ]
        payload = self._audit([e])
        codes = {w['code'] for w in payload['warnings']}
        self.assertEqual(payload['status'], 'PASS')
        self.assertIn('PDF_URL_NOT_BYTE_VERIFIED', codes)
        self.assertIn('PREFERRED_PUBLISHED_PDF_NOT_BYTE_VERIFIED', codes)
        self.assertEqual(payload['summary']['effective_byte_verified_preferred_count'], 0)

    def test_invalid_sha_inside_multi_part_revision_is_hard_error(self):
        e = self._entry('BAT_MULTI')
        e['official_documents'] = [{
            'document_part': 'PART_1',
            'official_pdf_url': 'https://example.invalid/part-1.pdf',
            'official_pdf_sha256': 'not-a-sha',
        }]
        payload = self._audit([e])
        self.assertEqual(payload['status'], 'FAIL')
        self.assertIn('INVALID_PDF_SHA256', {x['code'] for x in payload['errors']})


if __name__ == '__main__':
    unittest.main()
