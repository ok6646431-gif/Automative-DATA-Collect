import unittest
from unittest.mock import patch

from orchestrator import g0_kind_sustainability_recovery as mod


class _FakeHttp:
    def __init__(self, *args, **kwargs):
        self.audit = []


class KindSustainabilityRecoveryTests(unittest.TestCase):
    def _discovery(self):
        return {
            'requested_company_name': '테스트전자',
            'current_legal_name': '테스트전자 주식회사',
            'company_aliases': [
                {'name': '테스트전자', 'alias_type': 'requested_name'},
            ],
        }

    def _audit(self):
        return {
            'stages': {
                'legal_identity': {
                    'resolved': {
                        'company_code': '123456',
                        'korean_name': '테스트전자 주식회사',
                    }
                }
            }
        }

    def test_missing_years_excludes_strong_full_report(self):
        documents = {
            'documents': [
                {
                    'document_type': 'SUSTAINABILITY_REPORT',
                    'report_year': 2024,
                    'verification_status': 'SOURCE_VERIFIED',
                }
            ],
            'gaps': [
                {'document_type': 'SUSTAINABILITY_REPORT', 'year': 2023, 'blocking': True},
                {'document_type': 'SUSTAINABILITY_REPORT', 'year': 2024, 'blocking': True},
            ],
        }
        self.assertEqual([2023], mod._missing_years(documents))

    def test_report_name_and_year_are_parsed_fail_closed(self):
        body = '1. 보고서 명칭 : 2024 테스트전자 지속가능경영보고서 2. 검증기관 : 한국표준협회'
        name = mod._report_name(body)
        self.assertIn('2024', name)
        self.assertEqual(2024, mod._report_year(name, [2023, 2024]))
        self.assertIsNone(mod._report_year('지속가능경영보고서', [2024]))

    def test_issuer_must_match_verified_entity(self):
        discovery = self._discovery()
        self.assertTrue(mod._issuer_aligned('테스트전자 주식회사', discovery))
        self.assertFalse(mod._issuer_aligned('테스트전자머티리얼즈 주식회사', discovery))
        self.assertFalse(mod._issuer_aligned('', discovery))

    def test_no_kind_result_preserves_gap_and_never_claims_not_published(self):
        documents = {
            'documents': [],
            'gaps': [
                {
                    'gap_id': 'Y2024',
                    'document_type': 'SUSTAINABILITY_REPORT',
                    'year': 2024,
                    'status': 'DISCOVERY_GAP',
                    'blocking': True,
                }
            ],
        }
        audit = self._audit()
        with patch.object(mod.base, 'Http', _FakeHttp), patch.object(mod.kind, 'search_year', return_value=[]):
            out = mod.enrich(self._discovery(), documents, audit)
        self.assertIs(out, documents)
        self.assertEqual('DISCOVERY_GAP', out['gaps'][0]['status'])
        self.assertTrue(out['gaps'][0]['blocking'])
        self.assertEqual('NO_POSITIVE_RECOVERY', audit['stages']['kind_sustainability_recovery']['status'])

    def test_verified_kind_pdf_recovers_only_missing_year(self):
        documents = {
            'documents': [],
            'gaps': [
                {
                    'gap_id': 'Y2024',
                    'document_type': 'SUSTAINABILITY_REPORT',
                    'year': 2024,
                    'status': 'DISCOVERY_GAP',
                    'blocking': True,
                }
            ],
        }
        audit = self._audit()
        row = {
            'date': '2025-06-20',
            'title': '지속가능경영보고서 등 관련사항(자율공시)',
            'acceptance_no': '20250620000123',
            'issuer': '테스트전자 주식회사',
        }
        body = {
            'text': '1. 보고서 명칭 : 2024 테스트전자 지속가능경영보고서 2. 검증기관 : 한국표준협회',
            'doc_no': '20250620000456',
            'body_url': 'https://kind.krx.co.kr/example/body.htm',
        }
        attachments = [
            {
                'source_url': 'https://kind.krx.co.kr/example/report.pdf',
                'source_locator': 'https://kind.krx.co.kr/example/attach.htm',
                'label': '2024 지속가능경영보고서.pdf',
                'doc_no': '20250620000456',
                'score': '14',
            }
        ]
        with (
            patch.object(mod.base, 'Http', _FakeHttp),
            patch.object(mod.kind, 'search_year', return_value=[row]),
            patch.object(mod.kind, 'fetch_disclosure_body', return_value=body),
            patch.object(mod, '_attachment_candidates', return_value=attachments),
        ):
            out = mod.enrich(self._discovery(), documents, audit)
        recovered = [d for d in out['documents'] if d.get('report_year') == 2024]
        self.assertEqual(1, len(recovered))
        self.assertEqual('KIND_VOLUNTARY_SUSTAINABILITY_DISCLOSURE', recovered[0]['discovery_channel'])
        self.assertEqual('SOURCE_VERIFIED', recovered[0]['verification_status'])
        self.assertEqual('RECOVERED', audit['stages']['kind_sustainability_recovery']['status'])
        # Gap cleanup remains the responsibility of the normal finalizer/refresh pass.
        self.assertEqual('DISCOVERY_GAP', out['gaps'][0]['status'])

    def test_weak_existing_route_is_replaced_but_strong_company_route_is_preserved(self):
        weak = {
            'document_type': 'SUSTAINABILITY_REPORT',
            'report_year': 2024,
            'verification_status': 'UNVERIFIED',
            'source_url': 'https://company.example/weak.pdf',
            'source_locator': 'https://company.example/reports',
        }
        recovered = {
            'document_type': 'SUSTAINABILITY_REPORT',
            'report_year': 2024,
            'verification_status': 'SOURCE_VERIFIED',
            'source_url': 'https://kind.krx.co.kr/verified.pdf',
            'source_locator': 'https://kind.krx.co.kr/attach',
            'expected_extension': 'pdf',
        }
        documents = {'documents': [weak]}
        self.assertEqual('REPLACED_WEAK_PRIMARY', mod._merge_route(documents, recovered))
        self.assertEqual('https://kind.krx.co.kr/verified.pdf', documents['documents'][0]['source_url'])

        strong = {
            'document_type': 'SUSTAINABILITY_REPORT',
            'report_year': 2025,
            'verification_status': 'SOURCE_VERIFIED',
            'source_url': 'https://company.example/official-2025.pdf',
            'source_locator': 'https://company.example/reports',
        }
        recovered_2025 = dict(recovered, report_year=2025, source_url='https://kind.krx.co.kr/verified-2025.pdf')
        documents = {'documents': [strong]}
        self.assertEqual('ADDED_FALLBACK', mod._merge_route(documents, recovered_2025))
        self.assertEqual('https://company.example/official-2025.pdf', documents['documents'][0]['source_url'])
        self.assertEqual('https://kind.krx.co.kr/verified-2025.pdf', documents['documents'][0]['fallback_sources'][0]['source_url'])


if __name__ == '__main__':
    unittest.main()
