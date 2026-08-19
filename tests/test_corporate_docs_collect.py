import csv, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"collectors"))
from corporate_docs_collect import collect


class FakeResponse:
    def __init__(self, body=b"%PDF-test", content_type="application/pdf", disposition='attachment; filename="report.pdf"'):
        self.body=body; self.headers={"Content-Type":content_type,"Content-Disposition":disposition,"Content-Length":str(len(body))}
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def raise_for_status(self): return None
    def iter_content(self,size): yield self.body


class CorporateDocsTests(unittest.TestCase):
    def test_request_scope_mismatch_fails_closed_without_network(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); evidence=root/"docs.json"; profile=root/"profile.json"; out=root/"out"
            profile.write_text(json.dumps({"request_id":"REQ-A","company_id":"COMP1"}),encoding="utf-8")
            evidence.write_text(json.dumps({"schema_version":"1.0","request_id":"REQ-B","discovery_status":"COMPLETE","documents":[{"document_id":"D1","document_type":"SUSTAINABILITY_REPORT","title":"Report","source_url":"https://official.example/report.pdf","verification_status":"VERIFIED"}]}),encoding="utf-8")
            with patch("corporate_docs_collect.requests.Session.get") as get:
                status=collect(evidence,profile,out)
                get.assert_not_called()
            self.assertEqual(status["status"],"INVALID_SCOPE")
            rows=list(csv.DictReader((out/"document_index.csv").open(encoding="utf-8-sig")))
            self.assertEqual(rows[0]["collection_status"],"SKIPPED_SCOPE_MISMATCH")

    def test_verified_pdf_is_downloaded_and_hashed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); evidence=root/"docs.json"; profile=root/"profile.json"; out=root/"out"
            profile.write_text(json.dumps({"request_id":"REQ-A","company_id":"COMP1"}),encoding="utf-8")
            evidence.write_text(json.dumps({"schema_version":"1.0","request_id":"REQ-A","discovery_status":"COMPLETE","documents":[{"document_id":"D1","document_type":"SUSTAINABILITY_REPORT","title":"Report","report_year":2024,"source_url":"https://official.example/report.pdf","verification_status":"VERIFIED","importance":"CORE"}]}),encoding="utf-8")
            session=unittest.mock.MagicMock(); session.get.return_value=FakeResponse()
            with patch("corporate_docs_collect.requests.Session",return_value=session):
                status=collect(evidence,profile,out)
            self.assertEqual(status["downloaded"],1)
            rows=list(csv.DictReader((out/"document_index.csv").open(encoding="utf-8-sig")))
            self.assertEqual(rows[0]["collection_status"],"DOWNLOADED")
            self.assertTrue(rows[0]["sha256"])

    def test_executable_extension_is_never_collected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); evidence=root/"docs.json"; profile=root/"profile.json"; out=root/"out"
            profile.write_text(json.dumps({"request_id":"REQ-A","company_id":"COMP1"}),encoding="utf-8")
            evidence.write_text(json.dumps({"schema_version":"1.0","request_id":"REQ-A","discovery_status":"COMPLETE","documents":[{"document_id":"D1","document_type":"OTHER_OFFICIAL_DOCUMENT","title":"Unsafe","source_url":"https://official.example/tool.exe","verification_status":"VERIFIED"}]}),encoding="utf-8")
            session=unittest.mock.MagicMock(); session.get.return_value=FakeResponse(body=b"binary",content_type="application/octet-stream",disposition='attachment; filename="tool.exe"')
            with patch("corporate_docs_collect.requests.Session",return_value=session):
                status=collect(evidence,profile,out)
            self.assertEqual(status["skipped"],1)
            rows=list(csv.DictReader((out/"document_index.csv").open(encoding="utf-8-sig")))
            self.assertEqual(rows[0]["collection_status"],"SKIPPED_FILE_TYPE")


if __name__=="__main__": unittest.main()
