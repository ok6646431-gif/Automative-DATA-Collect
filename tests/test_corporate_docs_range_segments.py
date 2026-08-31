import re, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"collectors"))
from corporate_docs_collect import download_one


class RangeResponse:
    def __init__(self, body, start, end, total, url="https://official.example/report.pdf"):
        self.body=body
        self.url=url
        self.status_code=206
        self.headers={
            "Content-Type":"application/pdf",
            "Content-Length":str(len(body)),
            "Content-Range":f"bytes {start}-{end}/{total}",
            "Accept-Ranges":"bytes",
        }
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def raise_for_status(self): return None
    def iter_content(self,size):
        for i in range(0,len(self.body),size):
            yield self.body[i:i+size]


class FullResponse:
    def __init__(self, body, url="https://official.example/report.pdf"):
        self.body=body
        self.url=url
        self.status_code=200
        self.headers={"Content-Type":"application/pdf","Content-Length":str(len(body))}
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def raise_for_status(self): return None
    def iter_content(self,size):
        for i in range(0,len(self.body),size):
            yield self.body[i:i+size]


class RangeSegmentTests(unittest.TestCase):
    def test_range_capable_pdf_is_collected_as_contiguous_segments(self):
        import corporate_docs_collect as mod
        full=b"%PDF-" + (b"x" * (mod.RANGE_SEGMENT_BYTES * 2 + 137))
        session=MagicMock()

        def get(url, **kwargs):
            header=kwargs.get("headers",{}).get("Range","")
            m=re.fullmatch(r"bytes=(\d+)-(\d+)",header)
            self.assertIsNotNone(m)
            start=int(m.group(1)); requested_end=int(m.group(2))
            end=min(requested_end,len(full)-1)
            return RangeResponse(full[start:end+1],start,end,len(full),url)

        session.get.side_effect=get
        with tempfile.TemporaryDirectory() as td, patch("corporate_docs_collect.time.sleep"):
            target=Path(td)/"report.pdf"
            _,count,ctype=download_one(session,{"source_url":"https://official.example/report.pdf","expected_extension":"pdf"},target,0)
            self.assertEqual(count,len(full))
            self.assertEqual(target.read_bytes(),full)
            self.assertEqual(ctype,"application/pdf")
            self.assertEqual(session.get.call_count,3)
            calls=[c.kwargs["headers"]["Range"] for c in session.get.call_args_list]
            self.assertEqual(calls[0],f"bytes=0-{mod.RANGE_SEGMENT_BYTES-1}")
            self.assertTrue(calls[1].startswith(f"bytes={mod.RANGE_SEGMENT_BYTES}-"))

    def test_range_ignored_pdf_falls_back_to_single_full_response(self):
        full=b"%PDF-no-range-complete"
        session=MagicMock(); session.get.return_value=FullResponse(full)
        with tempfile.TemporaryDirectory() as td, patch("corporate_docs_collect.time.sleep"):
            target=Path(td)/"report.pdf"
            _,count,_=download_one(session,{"source_url":"https://official.example/report.pdf","expected_extension":"pdf"},target,0)
            self.assertEqual(count,len(full))
            self.assertEqual(target.read_bytes(),full)
            self.assertEqual(session.get.call_count,1)
            self.assertIn("Range",session.get.call_args.kwargs["headers"])


if __name__ == "__main__":
    unittest.main()
