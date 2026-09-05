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


if __name__ == '__main__':
    unittest.main()
