import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from orchestrator import public_source_human_delivery as mod


def pdf_bytes():
    out = io.BytesIO()
    pdf = PdfWriter()
    pdf.add_blank_page(width=612, height=792)
    pdf.write(out)
    return out.getvalue()


class PublicHumanDeliveryTests(unittest.TestCase):
    def fixture(self, root, legal_name):
        root = Path(root)
        output = root / "output"
        for source in mod.SOURCES:
            folder = output / source
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "status.json").write_text(
                json.dumps({"status": "DATA_FOUND" if source not in {"CLEANSYS_AIR", "SOOSIRO_WATER"}
                            else "NO_FACILITY_MATCH_CONFIRMED"}, ensure_ascii=False),
                encoding="utf-8")
        env = output / "ENVINFO"
        with (env / "discovery.csv").open("w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows([["year", "compId", "compNm"], [2024, "001", legal_name]])
        html = env / "raw_detail/2024_001_Test.html"
        html.parent.mkdir(parents=True)
        html.write_text("<html><body>공식 공개정보 본문 2024</body></html>", encoding="utf-8")
        (env / "raw_attachments/2024/001").mkdir(parents=True)
        official = env / "raw_attachments/2024/001/policy.pdf"
        official.write_bytes(pdf_bytes())
        with (env / "attachment_index.csv").open("w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows([
                ["year", "compId", "original_filename", "stored_path", "collection_status", "sha256"],
                ["2024", "001", "policy.pdf", "output/ENVINFO/raw_attachments/2024/001/policy.pdf",
                 "DOWNLOADED", mod._sha(official)]
            ])
        with (output / "PRTR/discovery.csv").open("w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows([["search_year", "entrps_id", "entrps_nm"], [2024, "PRTR-001", legal_name]])
        with (output / "CHEM_STATS/discovery.csv").open("w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows([["reportYear", "bplcId", "bplcNm"], [2024, "CHEM-001", legal_name]])
        for source in ("PRTR", "CHEM_STATS"):
            (output / source / "detail_table_rows.jsonl").write_text(
                json.dumps({"search_year": 2024, "cells": ["항목", "값"]}, ensure_ascii=False) + "\n",
                encoding="utf-8")
        report = root / "reports.zip"
        with zipfile.ZipFile(report, "w") as z:
            z.writestr("official/2024.pdf", pdf_bytes())
        return output, report

    def mock_renderer(self, source, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(pdf_bytes())
        return True, ""

    def test_reusable_for_multiple_companies_with_genuine_document_decoders(self):
        for company in ("에쓰오일", "이수페타시스"):
            with self.subTest(company=company), tempfile.TemporaryDirectory() as td:
                source, reports = self.fixture(td, company)
                with patch.object(mod, "render_envinfo_static_pdf", side_effect=self.mock_renderer):
                    result = mod.create(source, Path(td) / "user", company, reports)
                self.assertEqual("USER_PDF_EXCEL_ZIP_READY_WITH_LIMITATIONS", result["status"], result["problems"])
                self.assertEqual(2, len(result["limitations"]))
                self.assertEqual(1, result["envinfo_disclosure_pdf_created"])
                self.assertEqual(1, result["envinfo_attachments_delivered"])
                self.assertEqual(1, result["official_report_pdfs_delivered"])
                with zipfile.ZipFile(result["outputs"]["zip"]) as z:
                    names=z.namelist()
                    self.assertEqual(9, len(names))
                    self.assertTrue(all(x.endswith((".pdf", ".xlsx")) for x in names))
                    self.assertEqual(6, sum(x.endswith(".xlsx") for x in names))

    def test_missing_envinfo_html_does_not_claim_completion(self):
        with tempfile.TemporaryDirectory() as td:
            source, reports = self.fixture(td, "Test")
            (source / "ENVINFO/raw_detail/2024_001_Test.html").unlink()
            result = mod.create(source, Path(td) / "user", "Test", reports)
            self.assertEqual("DELIVERY_REVIEW_REQUIRED", result["status"])
            self.assertIn("ENVINFO_DISCLOSURE_PDF_NOT_COMPLETE", result["problems"])

    def test_missing_attachment_does_not_claim_completion(self):
        with tempfile.TemporaryDirectory() as td:
            source, reports = self.fixture(td, "Test")
            (source / "ENVINFO/raw_attachments/2024/001/policy.pdf").unlink()
            with patch.object(mod, "render_envinfo_static_pdf", side_effect=self.mock_renderer):
                result = mod.create(source, Path(td) / "user", "Test", reports)
            self.assertEqual("DELIVERY_REVIEW_REQUIRED", result["status"])
            self.assertIn("ENVINFO_ATTACHMENT_DELIVERY_NOT_COMPLETE", result["problems"])

    def test_bad_collector_status_is_not_delivery_pass(self):
        with tempfile.TemporaryDirectory() as td:
            source, reports = self.fixture(td, "Test")
            (source / "PRTR/status.json").write_text('{"status":"FAILED"}', encoding="utf-8")
            with patch.object(mod, "render_envinfo_static_pdf", side_effect=self.mock_renderer):
                result = mod.create(source, Path(td) / "user", "Test", reports)
            self.assertEqual("DELIVERY_REVIEW_REQUIRED", result["status"])
            self.assertTrue(any(p.startswith("SOURCE_INCOMPLETE:PRTR") for p in result["problems"]))

    def test_report_missing_not_silently_called_all_sources_complete(self):
        with tempfile.TemporaryDirectory() as td:
            source, reports = self.fixture(td, "Test")
            with patch.object(mod, "render_envinfo_static_pdf", side_effect=self.mock_renderer):
                result = mod.create(source, Path(td) / "user", "Test", "missing.zip")
            self.assertEqual("DELIVERY_REVIEW_REQUIRED", result["status"])
            self.assertIn("REPORT_PDF_ARCHIVE_MISSING", result["problems"])

    def test_reused_source_pdf_still_delivers_each_year_attachment_reference(self):
        with tempfile.TemporaryDirectory() as td:
            source, reports = self.fixture(td, "Test")
            index = source / "ENVINFO/attachment_index.csv"
            with index.open("a", newline="", encoding="utf-8-sig") as file:
                csv.writer(file).writerow([
                    "2023", "001", "policy.pdf",
                    "output/ENVINFO/raw_attachments/2024/001/policy.pdf",
                    "DOWNLOADED",
                    mod._sha(source / "ENVINFO/raw_attachments/2024/001/policy.pdf"),
                ])
            with patch.object(mod, "render_envinfo_static_pdf", side_effect=self.mock_renderer):
                result = mod.create(source, Path(td) / "user", "Test", reports)
            self.assertEqual(2, result["envinfo_source_attachments_downloaded"])
            self.assertEqual(1, result["envinfo_attachment_unique_origins"])
            self.assertEqual(2, result["envinfo_attachments_delivered"])
            with zipfile.ZipFile(result["outputs"]["zip"]) as archive:
                attachments = [x for x in archive.namelist() if x.startswith("ENVINFO_공식첨부자료/")]
                self.assertEqual(2, len(attachments))
                self.assertTrue(any("/2023/" in "/" + x for x in attachments))
                self.assertTrue(any("/2024/" in "/" + x for x in attachments))

    def test_report_years_missing_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            source, reports = self.fixture(td, "Test")
            with patch.object(mod, "render_envinfo_static_pdf", side_effect=self.mock_renderer):
                result = mod.create(source, Path(td) / "user", "Test", reports,
                                    required_report_years=("2023", "2024"))
            self.assertEqual("DELIVERY_REVIEW_REQUIRED", result["status"])
            self.assertIn("OFFICIAL_ANNUAL_REPORT_YEARS_MISSING:2023", result["problems"])

    def test_bad_unknown_status_cannot_become_a_completed_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            source, reports = self.fixture(td, "Test")
            (source / "CHEM_STATS/status.json").write_text('{"status":"COLLECTION_FAILED_RETRY_EXHAUSTED"}', encoding="utf-8")
            with patch.object(mod, "render_envinfo_static_pdf", side_effect=self.mock_renderer):
                result = mod.create(source, Path(td) / "user", "Test", reports)
            self.assertTrue(any(x.startswith("SOURCE_INCOMPLETE:CHEM_STATS") for x in result["problems"]))

    def test_json_internal_qa_never_enters_user_zip(self):
        with tempfile.TemporaryDirectory() as td:
            source, reports = self.fixture(td, "Test")
            with patch.object(mod, "render_envinfo_static_pdf", side_effect=self.mock_renderer):
                result = mod.create(source, Path(td) / "user", "Test", reports)
            with zipfile.ZipFile(result["outputs"]["zip"]) as z:
                self.assertFalse(any(name.endswith((".json", ".html", ".jsonl", ".csv"))
                                     for name in z.namelist()))
            self.assertTrue((Path(td) / "user/Internal_Delivery_QA.json").exists())


if __name__ == "__main__":
    unittest.main()
