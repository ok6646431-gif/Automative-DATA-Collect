import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator import human_delivery_gate as mod


class HumanDeliveryGateTests(unittest.TestCase):
    def fixture(self, root, *, with_pdf=True, with_xlsx=True, with_json=False):
        root = Path(root)
        zpath = root / "Human_Archive.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            if with_xlsx:
                for i in range(4):
                    zf.writestr(f"Test/01_사용자자료/02_화학물질/테스트{i}.xlsx", b"DUMMY_XLSX")
            if with_pdf:
                zf.writestr("Test/01_사용자자료/03_환경정보공개시스템/"
                            "이수페타시스/환경정보공개_이수페타시스_2024_전체내용정적재현본.pdf",
                            b"DUMMY_PDF")
            if with_json:
                zf.writestr("Test/01_사용자자료/내부데이터.json", b'{"metadata_only":true}')
        digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
        summary = {
            "envinfo_content_qa": {"expected_items": 1, "pass": True},
            "sustainability_korean_delivery_qa": {"pass": True},
            "acceptance_checks": {
                "envinfo_content_fidelity": True,
                "sustainability_korean_pdf_fidelity": True,
            },
            "zip_sha256": digest,
        }
        manifest = {
            "validation": "PASS",
            "human_archive": {"status": "PASS", "zip_file": "Human_Archive.zip"},
        }
        (root / "Archive_Summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (root / "Master_Manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (root / "Collection_Completeness.json").write_text(
            json.dumps({"status": "COMPLETE"}), encoding="utf-8")
        return zpath

    def check(self, root):
        # Test format-specific gate logic separately from actual binary decoder.
        # A real archive job supplies pypdf/openpyxl and never mocks either.
        xlsx = SimpleNamespace(sheetnames=["Sheet1"], close=lambda: None)
        pdf = SimpleNamespace(is_encrypted=False, pages=[object()])
        with patch.object(mod, "validate_archive_zip",
                          return_value={"status": "PASS", "archive_root": "Test", "failures": []}):
            with patch("pypdf.PdfReader", return_value=pdf):
                with patch("openpyxl.load_workbook", return_value=xlsx):
                    return mod.check_archive(Path(root) / "Human_Archive.zip",
                                             Path(root) / "Archive_Summary.json",
                                             Path(root) / "Master_Manifest.json")

    def test_real_parseable_pdf_and_four_excel_workbooks_pass_unmocked(self):
        import io
        import xlsxwriter
        from pypdf import PdfWriter
        from orchestrator.archive_acceptance import REQUIRED_USER_XLSX

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.fixture(td)
            pdf_mem = io.BytesIO()
            pdf = PdfWriter()
            # Production archive acceptance requires >=1000 PDF bytes.
            # Multiple real pages keep this a readable PDF without fake padding.
            for _ in range(8):
                pdf.add_blank_page(width=612, height=792)
            pdf.write(pdf_mem)
            content = io.BytesIO()
            wb = xlsxwriter.Workbook(content, {"in_memory": True})
            ws = wb.add_worksheet("수집현황")
            ws.write(0, 0, "자료원")
            ws.write(1, 0, "실제 엑셀")
            wb.close()
            path = root / "Human_Archive.zip"
            with zipfile.ZipFile(path, "w") as zf:
                for relative in REQUIRED_USER_XLSX.values():
                    zf.writestr("Test/" + relative, content.getvalue())
                zf.writestr(
                    "Test/01_사용자자료/03_환경정보공개시스템/"
                    "이수페타시스/환경정보공개_이수페타시스_2024_전체내용정적재현본.pdf",
                    pdf_mem.getvalue(),
                )
            summary = json.loads((root / "Archive_Summary.json").read_text(encoding="utf-8"))
            summary["zip_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            (root / "Archive_Summary.json").write_text(json.dumps(summary), encoding="utf-8")
            result = mod.check_archive(
                path, root / "Archive_Summary.json", root / "Master_Manifest.json")
            self.assertEqual("HUMAN_ARCHIVE_READY", result["status"], result.get("problems"))
            self.assertEqual(4, result["human_files"]["XLSX"])
            self.assertEqual(1, result["human_files"]["ENVINFO_BODY_PDF"])

    def test_complete_document_archive_is_ready_and_needs_upload_to_publish(self):
        with tempfile.TemporaryDirectory() as td:
            self.fixture(td)
            ready = self.check(td)
            self.assertEqual("HUMAN_ARCHIVE_READY", ready["status"])
            self.assertEqual(1, ready["human_files"]["ENVINFO_BODY_PDF"])
            self.assertEqual(4, ready["human_files"]["XLSX"])
            self.assertEqual("DELIVERY_NOT_READY",
                             mod.confirm_publication(ready, "", "https://github.com/org/repo/actions/runs/1")["status"])
            confirmed = mod.confirm_publication(ready, "123456", "https://github.com/org/repo/actions/runs/1")
            self.assertEqual("USER_ARCHIVE_AVAILABLE", confirmed["status"])
            self.assertEqual("ZIP_WITH_PDF_XLSX_AND_OPTIONAL_READABLE_ATTACHMENTS", confirmed["file_type"])

    def test_json_only_never_qualifies_as_completed_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            self.fixture(td, with_pdf=False, with_xlsx=False, with_json=True)
            result = self.check(td)
            self.assertEqual("DELIVERY_NOT_READY", result["status"])
            self.assertIn("NO_PDF_OR_EXCEL_USER_FILES", result["problems"])
            self.assertIn("ENVINFO_BODY_PDF_DELIVERY_INCOMPLETE", result["problems"])

    def test_missing_envinfo_disclosure_pdf_rejected_even_if_attachments_present(self):
        with tempfile.TemporaryDirectory() as td:
            self.fixture(td, with_pdf=False)
            with zipfile.ZipFile(Path(td) / "Human_Archive.zip", "a") as zf:
                zf.writestr("Test/01_사용자자료/03_환경정보공개시스템/"
                            "이수페타시스/첨부자료/외부원본.pdf", b"DUMMY_PDF")
            (Path(td) / "Archive_Summary.json").write_text(
                json.dumps({"envinfo_content_qa": {"expected_items": 1, "pass": True}}), encoding="utf-8")
            result = self.check(td)
            self.assertEqual("DELIVERY_NOT_READY", result["status"])
            self.assertIn("ENVINFO_BODY_PDF_DELIVERY_INCOMPLETE", result["problems"])

    def test_json_leak_is_rejected_as_non_user_format(self):
        with tempfile.TemporaryDirectory() as td:
            self.fixture(td, with_json=True)
            result = self.check(td)
            self.assertEqual("DELIVERY_NOT_READY", result["status"])
            self.assertIn("MACHINE_OR_UNSUPPORTED_USER_FILE_IN_USER_LAYER", result["problems"])

    def test_readable_source_images_and_text_not_mistaken_for_json(self):
        with tempfile.TemporaryDirectory() as td:
            self.fixture(td)
            root = Path(td)
            with zipfile.ZipFile(root / "Human_Archive.zip", "a") as zf:
                zf.writestr("Test/01_사용자자료/03_환경정보공개시스템/"
                            "이수페타시스/첨부자료/현장사진.jpg", b"IMAGE_TEST_ONLY")
                zf.writestr("Test/01_사용자자료/03_환경정보공개시스템/"
                            "이수페타시스/환경정보출처.txt", b"SOURCE_NOTICE")
            summary = json.loads((root / "Archive_Summary.json").read_text(encoding="utf-8"))
            summary["zip_sha256"] = hashlib.sha256(
                (root / "Human_Archive.zip").read_bytes()).hexdigest()
            (root / "Archive_Summary.json").write_text(json.dumps(summary), encoding="utf-8")
            report = self.check(td)
            self.assertEqual("HUMAN_ARCHIVE_READY", report["status"], report["problems"])
            self.assertEqual(2, report["human_files"]["AUXILIARY"])
            self.assertEqual(4, report["human_files"]["XLSX"])

    def test_missing_zip_or_audit_must_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual("DELIVERY_NOT_READY",
                             mod.check_archive(Path(td) / "Human_Archive.zip",
                                               Path(td) / "Archive_Summary.json",
                                               Path(td) / "Master_Manifest.json")["status"])

    def test_collection_only_qa_pass_does_not_count_as_published_zip(self):
        receipt = mod.confirm_publication(
            {"status": "COLLECTION_PASS", "human_files": {}},
            "1234", "https://github.com/org/repo/actions/runs/1")
        self.assertEqual("DELIVERY_NOT_READY", receipt["status"])

    def test_partial_collection_cannot_be_described_as_fully_complete(self):
        with tempfile.TemporaryDirectory() as td:
            self.fixture(td)
            (Path(td) / "Collection_Completeness.json").write_text(
                json.dumps({"status": "REVIEW_REQUIRED"}), encoding="utf-8")
            ready = self.check(td)
            self.assertEqual("HUMAN_ARCHIVE_READY_WITH_LIMITATIONS", ready["status"])
            confirmed = mod.confirm_publication(ready, "123", "https://github.com/org/repo/actions/runs/1")
            self.assertEqual("USER_ARCHIVE_AVAILABLE_WITH_LIMITATIONS", confirmed["status"])
            self.assertTrue(confirmed["limitations"])

    def test_archive_hash_change_prevents_completion(self):
        with tempfile.TemporaryDirectory() as td:
            self.fixture(td)
            p = Path(td) / "Human_Archive.zip"
            with zipfile.ZipFile(p, "a") as zf:
                zf.writestr("Test/00_자료목록/placeholder.txt", b"changed after acceptance")
            r = self.check(td)
            self.assertIn("HUMAN_ZIP_SHA256_MISMATCH", r["problems"])
            self.assertEqual("DELIVERY_NOT_READY", r["status"])


if __name__ == "__main__":
    unittest.main()
