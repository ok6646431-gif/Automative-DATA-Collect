import csv, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"collectors"))
from corporate_docs_collect import DOWNLOAD_ATTEMPTS, DOWNLOAD_TIMEOUT, PREFLIGHT_TIMEOUT, collect


class FakeResponse:
    def __init__(self, body=b"%PDF-test", content_type="application/pdf", disposition='attachment; filename="report.pdf"', url="https://official.example/report.pdf"):
        self.body=body; self.url=url
        self.headers={"Content-Type":content_type,"Content-Disposition":disposition,"Content-Length":str(len(body))}
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def raise_for_status(self): return None
    def iter_content(self,size): yield self.body


class CorporateDocsTests(unittest.TestCase):
    def test_runtime_budget_is_bounded(self):
        self.assertLessEqual(DOWNLOAD_ATTEMPTS,2)
        self.assertLessEqual(PREFLIGHT_TIMEOUT[1],10)
        self.assertLessEqual(DOWNLOAD_TIMEOUT[1],25)

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
            evidence.write_text(json.dumps({"schema_version":"1.0","request_id":"REQ-A","discovery_status":"COMPLETE","documents":[{"document_id":"D1","document_type":"SUSTAINABILITY_REPORT","title":"Report","report_year":2024,"source_url":"https://official.example/report.pdf","expected_extension":"pdf","verification_status":"VERIFIED","importance":"CORE"}]}),encoding="utf-8")
            session=unittest.mock.MagicMock(); session.get.return_value=FakeResponse()
            with patch("corporate_docs_collect.requests.Session",return_value=session):
                status=collect(evidence,profile,out)
            self.assertEqual(status["downloaded"],1)
            self.assertEqual(status["fallback_downloaded"],0)
            rows=list(csv.DictReader((out/"document_index.csv").open(encoding="utf-8-sig")))
            self.assertEqual(rows[0]["collection_status"],"DOWNLOADED")
            self.assertTrue(rows[0]["sha256"])
            attempts=list(csv.DictReader((out/"download_attempts.csv").open(encoding="utf-8-sig")))
            self.assertEqual(attempts[0]["source_role"],"PRIMARY")
            self.assertEqual(attempts[0]["attempt_status"],"DOWNLOADED")

    def test_expected_pdf_rejects_html_error_payload(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); evidence=root/"docs.json"; profile=root/"profile.json"; out=root/"out"
            profile.write_text(json.dumps({"request_id":"REQ-A","company_id":"COMP1"}),encoding="utf-8")
            evidence.write_text(json.dumps({"schema_version":"1.0","request_id":"REQ-A","discovery_status":"COMPLETE","documents":[{"document_id":"D1","document_type":"SUSTAINABILITY_REPORT","title":"Report","source_url":"https://official.example/download/1","expected_extension":"pdf","verification_status":"VERIFIED"}]}),encoding="utf-8")
            session=unittest.mock.MagicMock(); session.get.return_value=FakeResponse(body=b"<html>blocked</html>",content_type="text/html",disposition="",url="https://official.example/download/1")
            with patch("corporate_docs_collect.requests.Session",return_value=session), patch("corporate_docs_collect.time.sleep"):
                status=collect(evidence,profile,out)
            self.assertEqual(status["downloaded"],0)
            self.assertEqual(status["failed"],1)
            self.assertEqual(session.get.call_count,DOWNLOAD_ATTEMPTS)
            rows=list(csv.DictReader((out/"document_index.csv").open(encoding="utf-8-sig")))
            self.assertEqual(rows[0]["collection_status"],"DOWNLOAD_FAILED")
            self.assertIn("expected PDF payload",rows[0]["notes"])
            self.assertFalse(any((out/"raw_documents").rglob("*.pdf")))

    def test_verified_fallback_is_used_only_after_primary_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); evidence=root/"docs.json"; profile=root/"profile.json"; out=root/"out"
            profile.write_text(json.dumps({"request_id":"REQ-A","company_id":"COMP1"}),encoding="utf-8")
            doc={
                "document_id":"D1","document_type":"SUSTAINABILITY_REPORT","title":"Report","report_year":2025,
                "source_url":"https://company.example/report.pdf","expected_extension":"pdf","verification_status":"VERIFIED","importance":"CORE",
                "fallback_sources":[{
                    "source_url":"https://exchange.example/report.pdf","source_locator":"https://exchange.example/disclosure",
                    "expected_extension":"pdf","verification_status":"VERIFIED","source_role":"official_exchange_attachment"
                }]
            }
            evidence.write_text(json.dumps({"schema_version":"1.0","request_id":"REQ-A","discovery_status":"COMPLETE","documents":[doc]}),encoding="utf-8")
            blocked=FakeResponse(body=b"<html>temporary error</html>",content_type="text/html",disposition="",url="https://company.example/report.pdf")
            fallback=FakeResponse(body=b"%PDF-fallback",content_type="application/pdf",disposition='attachment; filename="fallback.pdf"',url="https://exchange.example/report.pdf")
            source_page=FakeResponse(body=b"<html>disclosure</html>",content_type="text/html",disposition="",url="https://exchange.example/disclosure")
            session=unittest.mock.MagicMock(); session.get.side_effect=[blocked,blocked,source_page,fallback]
            with patch("corporate_docs_collect.requests.Session",return_value=session), patch("corporate_docs_collect.time.sleep"):
                status=collect(evidence,profile,out)
            self.assertEqual(status["downloaded"],1)
            self.assertEqual(status["fallback_downloaded"],1)
            rows=list(csv.DictReader((out/"document_index.csv").open(encoding="utf-8-sig")))
            self.assertEqual(rows[0]["collection_status"],"DOWNLOADED")
            self.assertEqual(rows[0]["source_url"],"https://exchange.example/report.pdf")
            self.assertIn("source_selection=FALLBACK_1",rows[0]["notes"])
            attempts=list(csv.DictReader((out/"download_attempts.csv").open(encoding="utf-8-sig")))
            self.assertEqual([(r["source_role"],r["attempt_status"]) for r in attempts],[
                ("PRIMARY","DOWNLOAD_FAILED"),("FALLBACK_1","DOWNLOADED")
            ])

    def test_unverified_fallback_is_never_used(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); evidence=root/"docs.json"; profile=root/"profile.json"; out=root/"out"
            profile.write_text(json.dumps({"request_id":"REQ-A","company_id":"COMP1"}),encoding="utf-8")
            doc={
                "document_id":"D1","document_type":"SUSTAINABILITY_REPORT","title":"Report",
                "source_url":"https://company.example/report.pdf","expected_extension":"pdf","verification_status":"VERIFIED",
                "fallback_sources":[{"source_url":"https://mirror.example/report.pdf","verification_status":"UNVERIFIED"}]
            }
            evidence.write_text(json.dumps({"schema_version":"1.0","request_id":"REQ-A","discovery_status":"PARTIAL","documents":[doc]}),encoding="utf-8")
            blocked=FakeResponse(body=b"<html>error</html>",content_type="text/html",disposition="",url="https://company.example/report.pdf")
            session=unittest.mock.MagicMock(); session.get.side_effect=[blocked,blocked]
            with patch("corporate_docs_collect.requests.Session",return_value=session), patch("corporate_docs_collect.time.sleep"):
                status=collect(evidence,profile,out)
            self.assertEqual(status["downloaded"],0)
            self.assertEqual(status["fallback_downloaded"],0)
            self.assertEqual(status["failed"],1)
            self.assertEqual(session.get.call_count,DOWNLOAD_ATTEMPTS)
            attempts=list(csv.DictReader((out/"download_attempts.csv").open(encoding="utf-8-sig")))
            self.assertEqual(attempts[-1]["attempt_status"],"SKIPPED_UNVERIFIED_SOURCE")

    def test_source_locator_is_preflighted_and_used_as_referer(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); evidence=root/"docs.json"; profile=root/"profile.json"; out=root/"out"
            profile.write_text(json.dumps({"request_id":"REQ-A","company_id":"COMP1"}),encoding="utf-8")
            evidence.write_text(json.dumps({"schema_version":"1.0","request_id":"REQ-A","discovery_status":"COMPLETE","documents":[{"document_id":"D1","document_type":"SUSTAINABILITY_REPORT","title":"Report","source_url":"https://official.example/download/1","source_locator":"https://official.example/post/1","expected_extension":"pdf","verification_status":"SOURCE_VERIFIED"}]}),encoding="utf-8")
            page=FakeResponse(body=b"<html>source page</html>",content_type="text/html",disposition="",url="https://official.example/post/1")
            pdf=FakeResponse(url="https://official.example/download/1")
            session=unittest.mock.MagicMock(); session.get.side_effect=[page,pdf]
            with patch("corporate_docs_collect.requests.Session",return_value=session):
                status=collect(evidence,profile,out)
            self.assertEqual(status["downloaded"],1)
            self.assertEqual(session.get.call_count,2)
            _,kwargs=session.get.call_args_list[1]
            self.assertEqual(kwargs["headers"]["Referer"],"https://official.example/post/1")

    def test_shared_source_locator_is_preflighted_once(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); evidence=root/"docs.json"; profile=root/"profile.json"; out=root/"out"
            profile.write_text(json.dumps({"request_id":"REQ-A","company_id":"COMP1"}),encoding="utf-8")
            docs=[]
            for idx in (1,2):
                docs.append({"document_id":f"D{idx}","document_type":"SUSTAINABILITY_REPORT","title":f"Report {idx}","source_url":f"https://official.example/download/{idx}","source_locator":"https://official.example/reports","expected_extension":"pdf","verification_status":"SOURCE_VERIFIED"})
            evidence.write_text(json.dumps({"schema_version":"1.0","request_id":"REQ-A","discovery_status":"COMPLETE","documents":docs}),encoding="utf-8")
            page=FakeResponse(body=b"<html>source page</html>",content_type="text/html",disposition="",url="https://official.example/reports")
            pdf1=FakeResponse(url="https://official.example/download/1")
            pdf2=FakeResponse(url="https://official.example/download/2")
            session=unittest.mock.MagicMock(); session.get.side_effect=[page,pdf1,pdf2]
            with patch("corporate_docs_collect.requests.Session",return_value=session):
                status=collect(evidence,profile,out)
            self.assertEqual(status["downloaded"],2)
            self.assertEqual(session.get.call_count,3)
            self.assertEqual(session.get.call_args_list[0].args[0],"https://official.example/reports")
            self.assertEqual(session.get.call_args_list[1].kwargs["headers"]["Referer"],"https://official.example/reports")
            self.assertEqual(session.get.call_args_list[2].kwargs["headers"]["Referer"],"https://official.example/reports")

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
