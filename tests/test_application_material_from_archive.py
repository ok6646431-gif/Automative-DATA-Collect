import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.build_application_material_from_archive import build_from_human_archive


class ApplicationMaterialFromArchiveTests(unittest.TestCase):
    def make_human_archive(self, path: Path, *, completeness="COMPLETE", blocking_ok=True):
        root = "주식회사 테스트기업_환경자료"
        manifest = {
            "schema_version": "2.0",
            "company_id": "COMP_TEST",
            "company_display_name": "주식회사 테스트기업",
            "archive_root": root,
            "archive_completeness": completeness,
            "blocking_acceptance_checks": {
                "user_excel_exports": blocking_ok,
                "envinfo_pdf_complete": True,
                "collection_completeness_complete": True,
            },
            "target_site_tokens": ["A공장"],
        }
        scope = {
            "schema_version": "1.1",
            "mode": "SITE_SET",
            "label": "테스트기업 A공장",
            "target_source_ids": {
                "ENVINFO": ["ENV-A"],
                "PRTR": [],
                "CHEM_STATS": [],
                "CLEANSYS_AIR": [],
                "SOOSIRO_WATER": [],
            },
            "excluded_source_ids": [],
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(
                f"{root}/00_자료목록/Archive_Manifest.json",
                json.dumps(manifest, ensure_ascii=False),
            )
            z.writestr(
                f"{root}/00_자료목록/Requested_Scope.json",
                json.dumps(scope, ensure_ascii=False),
            )
            z.writestr(
                f"{root}/01_사용자자료/03_환경정보공개시스템/A공장/환경정보공개_A공장_2024.pdf",
                b"%PDF-record",
            )
            z.writestr(
                f"{root}/01_사용자자료/03_환경정보공개시스템/A공장/첨부자료/2024_첨부.pdf",
                b"%PDF-attachment",
            )

    def test_complete_archive_builds_and_validates_generic_package(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "Human_Archive.zip"
            self.make_human_archive(source)
            result = build_from_human_archive(str(source), str(root / "delivery"), "12345")

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["company"], "주식회사 테스트기업")
            self.assertEqual(result["package_label"], "테스트기업")
            self.assertEqual(result["source_archive_completeness"], "COMPLETE")
            self.assertEqual(result["envinfo_disclosure_records"], 1)
            self.assertEqual(result["envinfo_attachment_references"], 1)
            self.assertEqual(result["envinfo_unique_attachments"], 1)
            self.assertEqual(result["envinfo_physical_files"], 2)
            self.assertTrue(Path(result["output_zip"]).exists())
            self.assertIn("VERIFIED_EXCLUSION_RECHECK", result["validation_checks"])

    def test_package_label_can_be_overridden_without_changing_legal_company(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "Human_Archive.zip"
            self.make_human_archive(source)
            result = build_from_human_archive(
                str(source), str(root / "delivery"), "12345", "테스트 브랜드"
            )
            self.assertEqual(result["company"], "주식회사 테스트기업")
            self.assertEqual(result["package_label"], "테스트 브랜드")
            self.assertTrue(result["output_zip"].endswith("테스트 브랜드_지원용_환경자료.zip"))

    def test_incomplete_archive_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "Human_Archive.zip"
            self.make_human_archive(source, completeness="INCOMPLETE")
            with self.assertRaisesRegex(RuntimeError, "not verified COMPLETE"):
                build_from_human_archive(str(source), str(Path(td) / "delivery"), "12345")

    def test_failed_blocking_acceptance_check_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "Human_Archive.zip"
            self.make_human_archive(source, blocking_ok=False)
            with self.assertRaisesRegex(RuntimeError, "failed blocking acceptance checks"):
                build_from_human_archive(str(source), str(Path(td) / "delivery"), "12345")


if __name__ == "__main__":
    unittest.main()
