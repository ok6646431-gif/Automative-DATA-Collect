import csv, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"collectors"))
from corporate_docs_collect import DOWNLOAD_ATTEMPTS, TRANSFER_ATTEMPTS, DOWNLOAD_TIMEOUT, PREFLIGHT_TIMEOUT, ATTACHMENT_DISCOVERY_TIMEOUT, BASE_DOCUMENT_WALL_SECONDS, MAX_DOCUMENT_WALL_SECONDS, wall_budget_for_length, download_one, collect


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
        self.assertLessEqual(TRANSFER_ATTEMPTS,4)
        self.assertLessEqual(PREFLIGHT_TIMEOUT[1],15)
        self.assertLessEqual(DOWNLOAD_TIMEOUT[1],60)
        self.assertLessEqual(ATTACHMENT_DISCOVERY_TIMEOUT[0],20)
        self.assertLessEqual(ATTACHMENT_DISCOVERY_TIMEOUT[1],60)
        self.assertLessEqual(BASE_DOCUMENT_WALL_SECONDS,120)
        self.assertLessEqual(MAX_DOCUMENT_WALL_SECONDS,360)
        self.assertGreater(MAX_DOCUMENT_WALL_SECONDS,BASE_DOCUMENT_WALL_SECONDS)

    def test_large_declared_file_gets_bounded_size_aware_budget(self):
        small = wall_budget_for_length(2 * 1024 * 1024)
        large = wall_budget_for_length(32 * 1024 * 1024)
        huge = wall_budget_for_length(100 * 1024 * 1024)
        self.assertEqual(small, BASE_DOCUMENT_WALL_SECONDS)
        self.assertGreater(large, BASE_DOCUMENT_WALL_SECONDS)
        self.assertLessEqual(large, MAX_DOCUMENT_WALL_SECONDS)
        self.assertEqual(huge, MAX_DOCUMENT_WALL_SECONDS)

    def test_slow_drip_download_hits_total_wall_clock_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); evidence=root/"docs.json"; profile=root/"profile.json"; out=root/"out"
            profile.write_text(json.dumps({"request_id":"REQ-A","company_id":"COMP1"}),encoding="utf-8")
            evidence.write_text(json.dumps({"schema_version":"1.0","request_id":"REQ-A","discovery_status":"COMPLETE","documents":[{"document_id":"D1","document_type":"SUSTAINABILITY_REPORT","title":"Slow report","source_url":"https://official.example/slow.pdf","expected_extension":"pdf","verification_status":"VERIFIED"}]}),encoding="utf-8")
            session=unittest.mock.MagicMock(); session.get.return_value=FakeResponse(body=b"%PDF-slow")
            ticks=iter([0.0, 0.0, 121.0, 121.0, 121.0])
            with patch("corporate_docs_collect.requests.Session",return_value=session), patch("corporate_docs_collect.time.monotonic",side_effect=lambda: next(ticks)), patch("corporate_docs_collect.time.sleep"):
                status=collect(evidence,profile,out)
            self.assertEqual(status["downloaded"],0)
            self.assertEqual(status["failed"],1)
            rows=list(csv.DictReader((out/"document_index.csv").open(encoding="utf-8-sig")))
            self.assertIn("wall-clock budget exceeded",rows[0]["notes"])

    def test_interrupted_transfer_resumes_with_http_range(self):
        import requests
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/"resume.pdf"
            full=b"%PDF-abcdefghijklmno"
            cut=8

            class Interrupted(FakeResponse):
                status_code=200
                def __init__(self):
                    super().__init__(body=full, url="https://official.example/report.pdf")
                    self.headers["Content-Length"]=str(len(full))
                def iter_content(self,size):
                    yield full[:cut]
                    raise requests.exceptions.ConnectionError("stream interrupted")

            class Resumed(FakeResponse):
                status_code=206
                def __init__(self):
                    super().__init__(body=full[cut:], url="https://official.example/report.pdf")
                    self.headers["Content-Length"]=str(len(full)-cut)
                    self.headers["Content-Range"]=f"bytes {cut}-{len(full)-1}/{len(full)}"

            session=unittest.mock.MagicMock(); session.get.side_effect=[Interrupted(),Resumed()]
            with patch("corporate_docs_collect.time.sleep"):
                _,count,ctype=download_one(session,{"source_url":"https://official.example/report.pdf","expected_extension":"pdf"},target,0)
            self.assertEqual(count,len(full))
            self.assertEqual(target.read_bytes(),full)
            self.assertEqual(ctype,"application/pdf")
            self.assertEqual(session.get.call_args_list[1].kwargs["headers"]["Range"],f"bytes={cut}-")

    def test_range_ignored_restarts_without_corrupt_append(self):
        import requests
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/"restart.pdf"
            full=b"%PDF-restart-complete"
            cut=7

            class Interrupted(FakeResponse):
                status_code=200
                def __init__(self):
                    super().__init__(body=full, url="https://official.example/report.pdf")
                    self.headers["Content-Length"]=str(len(full))
                def iter_content(self,size):
                    yield full[:cut]
                    raise requests.exceptions.ConnectionError("stream interrupted")

            second=FakeResponse(body=full,url="https://official.example/report.pdf")
            second.status_code=200
            session=unittest.mock.MagicMock(); session.get.side_effect=[Interrupted(),second]
            with patch("corporate_docs_collect.time.sleep"):
                _,count,_=download_one(session,{"source_url":"https://official.example/report.pdf","expected_extension":"pdf"},target,0)
            self.assertEqual(count,len(full))
            self.assertEqual(target.read_bytes(),full)
            self.assertIn("Range",session.get.call_args_list[1].kwargs["headers"])

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
            self.assertEqual(session.get.call_count,1)
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
            session=unittest.mock.MagicMock(); session.get.side_effect=[blocked,source_page,fallback]
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
            session=unittest.mock.MagicMock(); session.get.side_effect=[blocked]
            with patch("corporate_docs_collect.requests.Session",return_value=session), patch("corporate_docs_collect.time.sleep"):
                status=collect(evidence,profile,out)
            self.assertEqual(status["downloaded"],0)
            self.assertEqual(status["fallback_downloaded"],0)
            self.assertEqual(status["failed"],1)
            self.assertEqual(session.get.call_count,1)
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

    def test_verified_landing_page_discovers_unique_same_host_pdf_attachment(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); evidence=root/"docs.json"; profile=root/"profile.json"; out=root/"out"
            profile.write_text(json.dumps({"request_id":"REQ-A","company_id":"COMP1"}),encoding="utf-8")
            doc={
                "document_id":"BAT1","document_type":"BAT_REFERENCE","title":"반도체 최적가용기법 기준서",
                "source_url":"https://official.example/board/664","source_locator":"https://official.example/board/664",
                "expected_extension":"pdf","verification_status":"VERIFIED",
                "attachment_discovery":{"match_terms":["반도체","최적가용기법","기준서"],"same_host_only":True}
            }
            evidence.write_text(json.dumps({"schema_version":"1.0","request_id":"REQ-A","discovery_status":"COMPLETE","documents":[doc]}),encoding="utf-8")
            html='<html><a href="/jfile/readDownloadFile.do?fileId=16&fileSeq=2">반도체 제조업의 환경오염방지 및 통합관리를 위한 최적가용기법 기준서.pdf</a></html>'
            page=FakeResponse(body=html.encode("utf-8"),content_type="text/html",disposition="",url="https://official.example/board/664")
            pdf=FakeResponse(body=b"%PDF-kbref",content_type="application/pdf",disposition='attachment; filename="kbref.pdf"',url="https://official.example/jfile/readDownloadFile.do?fileId=16&fileSeq=2")
            session=unittest.mock.MagicMock(); session.get.side_effect=[page,pdf]
            with patch("corporate_docs_collect.requests.Session",return_value=session):
                status=collect(evidence,profile,out)
            self.assertEqual(status["downloaded"],1)
            self.assertEqual(status["failed"],0)
            rows=list(csv.DictReader((out/"document_index.csv").open(encoding="utf-8-sig")))
            self.assertEqual(rows[0]["collection_status"],"DOWNLOADED")
            self.assertIn("readDownloadFile.do",rows[0]["source_url"])
            self.assertIn("source_selection=DISCOVERED_ATTACHMENT",rows[0]["notes"])
            attempts=list(csv.DictReader((out/"download_attempts.csv").open(encoding="utf-8-sig")))
            self.assertEqual(attempts[0]["source_role"],"DISCOVERED_ATTACHMENT")

    def test_attachment_landing_page_retries_once_after_transient_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); evidence=root/"docs.json"; profile=root/"profile.json"; out=root/"out"
            profile.write_text(json.dumps({"request_id":"REQ-A","company_id":"COMP1"}),encoding="utf-8")
            doc={"document_id":"BAT1","document_type":"BAT_REFERENCE","title":"반도체 최적가용기법 기준서","source_url":"https://official.example/board/664","source_locator":"https://official.example/board/664","expected_extension":"pdf","verification_status":"VERIFIED","attachment_discovery":{"match_terms":["반도체","기준서"]}}
            evidence.write_text(json.dumps({"schema_version":"1.0","request_id":"REQ-A","discovery_status":"COMPLETE","documents":[doc]}),encoding="utf-8")
            html='<html><a href="/download?id=1">반도체 최적가용기법 기준서.pdf</a></html>'
            page=FakeResponse(body=html.encode("utf-8"),content_type="text/html",disposition="",url="https://official.example/board/664")
            pdf=FakeResponse(body=b"%PDF-kbref",content_type="application/pdf",disposition='attachment; filename="kbref.pdf"',url="https://official.example/download?id=1")
            session=unittest.mock.MagicMock(); session.get.side_effect=[RuntimeError("transient timeout"),page,pdf]
            with patch("corporate_docs_collect.requests.Session",return_value=session), patch("corporate_docs_collect.time.sleep"):
                status=collect(evidence,profile,out)
            self.assertEqual(status["downloaded"],1)
            self.assertEqual(status["failed"],0)
            self.assertEqual(session.get.call_count,3)

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
