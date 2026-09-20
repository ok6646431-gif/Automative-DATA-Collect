import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orchestrator.document_language_preference import prefer_korean_sustainability, route_language


class KoreanAnnualReportPolicyTest(unittest.TestCase):
    def doc(self, year, url, **kw):
        return {'document_id': 'DOC_'+str(year), 'document_type': 'SUSTAINABILITY_REPORT',
                'report_year': year, 'source_url': url,
                'verification_status': 'SOURCE_VERIFIED', **kw}

    def test_concrete_english_pdf_overrides_korean_page_title(self):
        doc = self.doc(2024, 'https://issuer.example/Hanwha_2024_ENG.pdf', title='2024 지속가능경영보고서 국문')
        self.assertEqual(route_language(doc), 'EN')
        result, meta = prefer_korean_sustainability({}, [doc])
        self.assertEqual(result[0]['verification_status'], 'LANGUAGE_REVIEW_REQUIRED')
        self.assertEqual(meta['korean_route_unverified_years'], [2024])

    def test_korean_fallback_promoted_but_english_never_used_as_fallback(self):
        doc = self.doc(2025, 'https://issuer.example/report_2025_ENG.pdf', fallback_sources=[
            {'source_url': 'https://issuer.example/report_2025_KOR.pdf', 'verification_status': 'SOURCE_VERIFIED'},
            {'source_url': 'https://issuer.example/another_2025_ENG.pdf', 'verification_status': 'SOURCE_VERIFIED'},
        ])
        out, metadata = prefer_korean_sustainability({}, [doc])
        self.assertEqual(out[0]['source_url'], 'https://issuer.example/report_2025_KOR.pdf')
        self.assertEqual(out[0]['fallback_sources'], [])
        self.assertFalse(metadata['korean_route_unverified_years'])

    def test_only_english_never_counts_as_verified_annual_report(self):
        out, metadata = prefer_korean_sustainability({}, [self.doc(2026, 'https://issuer.example/2026_ENG.pdf')])
        self.assertEqual(out[0]['verification_status'], 'LANGUAGE_REVIEW_REQUIRED')
        self.assertEqual(out[0]['fallback_sources'], [])
        self.assertEqual(metadata['status'], 'REVIEW_REQUIRED')

    def test_other_company_docs_not_affected(self):
        doc = {'document_type': 'ENVIRONMENTAL_MANAGEMENT', 'report_year': 2026,
               'source_url': 'https://issuer.example/english-page', 'verification_status': 'SOURCE_VERIFIED'}
        out, _ = prefer_korean_sustainability({}, [doc])
        self.assertEqual(out, [doc])


if __name__ == '__main__':
    unittest.main()
