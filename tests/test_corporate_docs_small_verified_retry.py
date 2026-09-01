import tempfile, unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import requests
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'collectors'))
from corporate_docs_collect import download_one, DOWNLOAD_TIMEOUT


class SmallVerifiedRetryTests(unittest.TestCase):
    def test_small_verified_pdf_gets_extended_retry_after_valid_headers(self):
        body=b'%PDF-small-policy-document'

        class SlowFirst:
            status_code=200
            url='https://official.example/policy.pdf'
            headers={
                'Content-Type':'application/pdf',
                'Content-Length':str(len(body)),
                'Content-Disposition':'attachment; filename="policy.pdf"'
            }
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def raise_for_status(self): return None
            def iter_content(self,size):
                raise requests.exceptions.ReadTimeout('first transfer stalled')
                yield b''

        class GoodSecond:
            status_code=200
            url='https://official.example/policy.pdf'
            headers={
                'Content-Type':'application/pdf',
                'Content-Length':str(len(body)),
                'Content-Disposition':'attachment; filename="policy.pdf"'
            }
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def raise_for_status(self): return None
            def iter_content(self,size): yield body

        session=MagicMock()
        session.get.side_effect=[SlowFirst(),GoodSecond()]
        with tempfile.TemporaryDirectory() as td, patch('corporate_docs_collect.time.sleep'):
            target=Path(td)/'policy.pdf'
            _,count,ctype=download_one(session,{
                'source_url':'https://official.example/policy.pdf',
                'expected_extension':'pdf'
            },target,0)
            self.assertEqual(count,len(body))
            self.assertEqual(target.read_bytes(),body)
            self.assertEqual(ctype,'application/pdf')
        first_timeout=session.get.call_args_list[0].kwargs['timeout'][1]
        second_timeout=session.get.call_args_list[1].kwargs['timeout'][1]
        self.assertLessEqual(first_timeout,DOWNLOAD_TIMEOUT[1])
        self.assertGreater(second_timeout,DOWNLOAD_TIMEOUT[1])


if __name__=='__main__':
    unittest.main()
