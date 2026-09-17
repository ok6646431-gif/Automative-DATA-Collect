import unittest
from orchestrator.document_language_preference import prefer_korean_sustainability, route_language


class DocumentLanguagePreferenceTests(unittest.TestCase):
    def test_detects_strong_language_route_signals(self):
        self.assertEqual(route_language({'source_url':'https://issuer.example/reports/SR_2024_kr.pdf'}),'KO')
        self.assertEqual(route_language({'source_url':'https://issuer.example/en/report_2024.pdf'}),'EN')
        self.assertEqual(route_language({'source_url':'https://issuer.example/report_2024.pdf'}),'UNKNOWN')

    def test_korean_fallback_replaces_english_primary_for_korean_issuer(self):
        discovery={'current_legal_name':'예시 주식회사'}
        docs=[{
            'document_id':'R2024','document_type':'SUSTAINABILITY_REPORT','report_year':2024,
            'verification_status':'SOURCE_VERIFIED','source_url':'https://issuer.example/en/SR_2024_en.pdf',
            'expected_extension':'pdf','fallback_sources':[{
                'source_url':'https://issuer.example/kr/SR_2024_kr.pdf','source_locator':'https://issuer.example/reports',
                'expected_extension':'pdf','verification_status':'SOURCE_VERIFIED'
            }]
        }]
        out,audit=prefer_korean_sustainability(discovery,docs)
        self.assertEqual(out[0]['source_url'],'https://issuer.example/kr/SR_2024_kr.pdf')
        self.assertEqual(out[0]['language_preference'],'KO_PREFERRED')
        self.assertTrue(any(x.get('source_url','').endswith('_en.pdf') for x in out[0]['fallback_sources']))
        self.assertEqual(audit['changes'][0]['action'],'PROMOTED_KOREAN_FALLBACK')

    def test_dedupes_same_year_to_korean_verified_primary(self):
        discovery={'requested_company_name':'예시회사'}
        docs=[
            {'document_id':'EN','document_type':'SUSTAINABILITY_REPORT','report_year':2023,'verification_status':'VERIFIED','source_url':'https://issuer.example/en/2023_report_en.pdf','expected_extension':'pdf'},
            {'document_id':'KO','document_type':'SUSTAINABILITY_REPORT','report_year':2023,'verification_status':'VERIFIED','source_url':'https://issuer.example/kr/2023_report_kr.pdf','expected_extension':'pdf'},
        ]
        out,audit=prefer_korean_sustainability(discovery,docs)
        annual=[d for d in out if d.get('document_type')=='SUSTAINABILITY_REPORT']
        self.assertEqual(len(annual),1)
        self.assertEqual(route_language(annual[0]),'KO')
        self.assertTrue(any(x.get('source_url','').endswith('_en.pdf') for x in annual[0].get('fallback_sources',[])))
        self.assertTrue(any(x['action']=='DEDUPED_TO_KOREAN_PRIMARY' for x in audit['changes']))

    def test_non_korean_issuer_is_unchanged(self):
        discovery={'current_legal_name':'Example Corp.'}
        docs=[{'document_type':'SUSTAINABILITY_REPORT','report_year':2024,'verification_status':'VERIFIED','source_url':'https://issuer.example/en/report_en.pdf'}]
        out,audit=prefer_korean_sustainability(discovery,docs)
        self.assertEqual(out,docs)
        self.assertEqual(audit['status'],'NOT_APPLICABLE_NON_KOREAN_ISSUER')


if __name__=='__main__':
    unittest.main()
