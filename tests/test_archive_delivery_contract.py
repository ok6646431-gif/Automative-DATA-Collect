import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator"))
sys.path.insert(0, str(ROOT / "tools"))

import archive_acceptance
import prepare_human_archive_delivery


def pdf_bytes(label=b"ok"):
    body = b"%PDF-1.4\n" + label + b"\n" + b"0" * 1200 + b"\n%%EOF\n"
    return body


def xlsx_bytes():
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", "<workbook/>")
        zf.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
    return bio.getvalue()


def build_valid_tree(root: Path):
    for rel in archive_acceptance.REQUIRED_USER_XLSX.values():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(xlsx_bytes())
    sust = root / archive_acceptance.SUSTAINABILITY_FOLDER / "회사_지속가능경영보고서_2024.pdf"
    sust.parent.mkdir(parents=True, exist_ok=True)
    sust.write_bytes(pdf_bytes(b"sustainability"))
    review = root / archive_acceptance.REVIEW_FOLDER / "회사_Environmental_Review_Brief.pdf"
    review.parent.mkdir(parents=True, exist_ok=True)
    review.write_bytes(pdf_bytes(b"review"))
    env = root / "01_사용자자료/03_환경정보공개시스템/회사 광주공장/환경정보공개_회사 광주공장_2024.pdf"
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_bytes(pdf_bytes(b"envinfo"))
    idx = root / "00_자료목록/README_먼저읽기.txt"
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text("read me", encoding="utf-8")


def zip_tree(root: Path, target: Path, archive_name="회사_환경자료"):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=str(Path(archive_name) / p.relative_to(root)))


class ArchiveDeliveryContractTests(unittest.TestCase):
    def test_valid_tree_and_zip_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "archive"
            build_valid_tree(root)
            report = archive_acceptance.validate_archive_tree(root, expected_env_pdf_count=1)
            self.assertEqual(report["status"], "PASS")
            z = Path(td) / "archive.zip"
            zip_tree(root, z)
            zreport = archive_acceptance.validate_archive_zip(z, expected_env_pdf_count=1)
            self.assertEqual(zreport["status"], "PASS")

    def test_machine_readable_file_in_user_layer_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "archive"
            build_valid_tree(root)
            leaked = root / "01_사용자자료/02_화학물질/raw.jsonl"
            leaked.parent.mkdir(parents=True, exist_ok=True)
            leaked.write_text("{}\n", encoding="utf-8")
            report = archive_acceptance.validate_archive_tree(root)
            self.assertEqual(report["status"], "FAIL")
            self.assertFalse(report["checks"]["user_machine_formats_absent"])

    def test_sustainability_year_subfolder_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "archive"
            build_valid_tree(root)
            src = root / archive_acceptance.SUSTAINABILITY_FOLDER / "회사_지속가능경영보고서_2024.pdf"
            nested = root / archive_acceptance.SUSTAINABILITY_FOLDER / "2024" / src.name
            nested.parent.mkdir(parents=True)
            src.replace(nested)
            report = archive_acceptance.validate_archive_tree(root)
            self.assertEqual(report["status"], "FAIL")
            self.assertFalse(report["checks"]["sustainability_shallow_pdf_series"])

    def test_invalid_xlsx_payload_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "archive"
            build_valid_tree(root)
            bad = root / archive_acceptance.REQUIRED_USER_XLSX["PRTR"]
            bad.write_text("not a workbook", encoding="utf-8")
            report = archive_acceptance.validate_archive_tree(root)
            self.assertEqual(report["status"], "FAIL")
            self.assertFalse(report["checks"]["structured_user_exports_valid"])

    def test_delivery_is_byte_preserving_validated_subset(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "archive"
            build_valid_tree(root)
            source = base / "Human_Archive.zip"
            zip_tree(root, source)
            out = base / "delivery"
            manifest = prepare_human_archive_delivery.prepare(source, out, "company", 10 * 1024 * 1024)
            self.assertEqual(manifest["status"], "PASS")
            self.assertEqual(manifest["source_archive_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertGreaterEqual(len(manifest["parts"]), 1)
            with zipfile.ZipFile(source, "r") as src_zip:
                source_bytes = {i.filename: src_zip.read(i) for i in src_zip.infolist() if not i.is_dir()}
            delivered = {}
            for part in manifest["parts"]:
                with zipfile.ZipFile(out / part["name"], "r") as zf:
                    for info in zf.infolist():
                        if not info.is_dir(): delivered[info.filename] = zf.read(info)
            for name, data in delivered.items():
                self.assertEqual(data, source_bytes[name])
            self.assertTrue(all("90_시스템원본/" not in name for name in delivered))


if __name__ == "__main__":
    unittest.main()
