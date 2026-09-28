import unittest
from orchestrator.document_language_preference import (
    prefer_korean_sustainability,
    recover_verified_korean_siblings,
    route_language,
)


class FakeResponse:
    def __init__(self, url, body=b"%PDF-test", status_code=200, content_type="application/pdf"):
        self.url=url
        self.status_code=status_code
        self.headers={"Content-Type":content_type}
        self.body=body
    def iter_content(self, chunk_size=16):
        yield self.body
    def close(self):
        pass


class FakeHttp:
    def __init__(self, responses):
        self.responses=responses
        self.calls=[]
    def get(self, url, **kwargs):
        self.calls.append((url,kwargs))
        return self.responses.get(url)


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
        self.assertEqual(out[0]['language_preference'],'KO_REQUIRED_VERIFIED_ROUTE')
        self.assertFalse(any(x.get('source_url','').endswith('_en.pdf') for x in out[0]['fallback_sources']))
        self.assertEqual(audit['changes'][0]['action'],'PROMOTED_KOREAN_PRIMARY_DROPPED_NON_KOREAN_FALLBACKS')

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
        self.assertFalse(any(x.get('source_url','').endswith('_en.pdf') for x in annual[0].get('fallback_sources',[])))
        self.assertTrue(any(x['action']=='DEDUPED_TO_KOREAN_PRIMARY' for x in audit['changes']))

    def test_english_only_non_korean_issuer_is_not_an_exception_to_user_preference(self):
        discovery={'current_legal_name':'Example Corp.'}
        docs=[{'document_type':'SUSTAINABILITY_REPORT','report_year':2024,'verification_status':'VERIFIED','source_url':'https://issuer.example/en/report_en.pdf'}]
        out,audit=prefer_korean_sustainability(discovery,docs)
        self.assertEqual(out[0]['verification_status'],'UNVERIFIED')
        self.assertEqual(out[0]['language_preference'],'KO_REQUIRED_NOT_VERIFIED')
        self.assertEqual(audit['korean_route_unverified_years'],[2024])


    def test_same_host_verified_english_pdf_recovers_korean_sibling(self):
        eng='https://issuer.example/assets/REPORT_2024_eng.pdf'
        kor='https://issuer.example/assets/REPORT_2024_kor.pdf'
        http=FakeHttp({kor:FakeResponse(kor)})
        docs={'documents':[{
            'document_id':'R2024','document_type':'SUSTAINABILITY_REPORT','report_year':2024,
            'verification_status':'SOURCE_VERIFIED','source_url':eng,
            'source_locator':'https://issuer.example/reports','expected_extension':'pdf',
        }], 'gaps':[]}
        audit={}
        out=recover_verified_korean_siblings({},docs,audit,http=http)
        doc=out['documents'][0]
        self.assertEqual(doc['source_url'],kor)
        self.assertEqual(doc['verification_status'],'SOURCE_VERIFIED')
        self.assertEqual(doc['language_preference'],'KO_REQUIRED_VERIFIED_ROUTE')
        self.assertEqual(doc['fallback_sources'],[])
        self.assertEqual(audit['stages']['korean_sibling_route_recovery']['recovered_years'],[2024])
        self.assertEqual(http.calls[0][0],kor)
        self.assertEqual(http.calls[0][1]['headers']['Range'],'bytes=0-15')

    def test_language_sibling_candidate_must_return_real_pdf(self):
        eng='https://issuer.example/assets/REPORT_2024_eng.pdf'
        kor='https://issuer.example/assets/REPORT_2024_kor.pdf'
        kr='https://issuer.example/assets/REPORT_2024_kr.pdf'
        http=FakeHttp({
            kor:FakeResponse(kor,body=b'<html>missing</html>',content_type='text/html'),
            kr:FakeResponse(kr,body=b'<html>missing</html>',content_type='text/html'),
        })
        docs={'documents':[{
            'document_id':'R2024','document_type':'SUSTAINABILITY_REPORT','report_year':2024,
            'verification_status':'SOURCE_VERIFIED','source_url':eng,'expected_extension':'pdf',
        }], 'gaps':[]}
        out=recover_verified_korean_siblings({},docs,{},http=http)
        self.assertEqual(out['documents'][0]['source_url'],eng)
        self.assertEqual(out['documents'][0]['verification_status'],'SOURCE_VERIFIED')
        self.assertEqual(len(http.calls),2)

    def test_opaque_pdf_without_explicit_english_token_is_not_guessed(self):
        url='https://issuer.example/download.do?fid=123'
        http=FakeHttp({})
        docs={'documents':[{
            'document_id':'R2024','document_type':'SUSTAINABILITY_REPORT','report_year':2024,
            'verification_status':'SOURCE_VERIFIED','source_url':url,'expected_extension':'pdf',
        }], 'gaps':[]}
        out=recover_verified_korean_siblings({},docs,{},http=http)
        self.assertEqual(out['documents'][0]['source_url'],url)
        self.assertEqual(http.calls,[])

if __name__=='__main__':
    unittest.main()
