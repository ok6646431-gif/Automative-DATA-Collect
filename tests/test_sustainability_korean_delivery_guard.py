import csv
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'orchestrator'))
from sustainability_korean_delivery_guard import evaluate, _inspect_pdf


class KoreanArchiveAcceptanceTests(unittest.TestCase):
    def _case(self, root, data=b'%PDF-KO', recorded=None):
        package = root / 'package'
        index = package / 'output' / 'CORP_DOCS' / 'document_index.csv'
        index.parent.mkdir(parents=True)
        digest = recorded or hashlib.sha256(data).hexdigest()
        with index.open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['document_type', 'collection_status', 'report_year', 'sha256'])
            w.writeheader()
            w.writerow({'document_type': 'SUSTAINABILITY_REPORT', 'collection_status': 'DOWNLOADED',
                        'report_year': '2024', 'sha256': digest})
        archive = root / 'human'
        p = archive / '01_사용자자료' / '04_지속가능경영보고서' / '기업_지속가능경영보고서_2024.pdf'
        p.parent.mkdir(parents=True)
        p.write_bytes(data)
        return package, archive

    def test_verified_korean_source_passes(self):
        with tempfile.TemporaryDirectory() as td:
            pkg, arc = self._case(Path(td))
            with patch('sustainability_korean_delivery_guard._inspect_pdf',
                       return_value={'hangul_chars': 2000, 'pages': 20}):
                result = evaluate(pkg, arc)
            self.assertEqual(result['status'], 'PASS')
            self.assertEqual(result['checked'], 1)

    def test_old_english_pdf_never_counts_even_with_matching_source_hash(self):
        with tempfile.TemporaryDirectory() as td:
            pkg, arc = self._case(Path(td), data=b'%PDF-ENG')
            with patch('sustainability_korean_delivery_guard._inspect_pdf',
                       side_effect=ValueError('annual report is not verifiably Korean-primary')):
                result = evaluate(pkg, arc)
            self.assertEqual(result['status'], 'REVIEW_REQUIRED')
            self.assertFalse(result['pass'])

    def test_mismatched_source_hash_never_counts(self):
        with tempfile.TemporaryDirectory() as td:
            pkg, arc = self._case(Path(td), recorded='a' * 64)
            with patch('sustainability_korean_delivery_guard._inspect_pdf',
                       return_value={'hangul_chars': 2000, 'pages': 20}) as inspect:
                result = evaluate(pkg, arc)
            self.assertEqual(result['status'], 'REVIEW_REQUIRED')
            inspect.assert_not_called()

    def test_missing_annual_file_fails_not_silent_pass(self):
        with tempfile.TemporaryDirectory() as td:
            pkg, arc = self._case(Path(td))
            for f in arc.rglob('*.pdf'):
                f.unlink()
            result = evaluate(pkg, arc)
            self.assertFalse(result['pass'])

    def test_korean_cover_cannot_hide_english_body(self):
        class Page:
            def __init__(self, text): self.text = text
            def extract_text(self): return self.text
        class FakeReader:
            def __init__(self, *a, **kw):
                self.pages = [Page('가' * 500)] + [Page('English report ' * 500)] * 9
        class FakePypdf:
            PdfReader = FakeReader
        with patch.dict(sys.modules, {'pypdf': FakePypdf()}):
            with self.assertRaisesRegex(ValueError, 'Korean-primary'):
                _inspect_pdf('dummy.pdf')


if __name__ == '__main__':
    unittest.main()
