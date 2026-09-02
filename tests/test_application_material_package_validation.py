import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.validate_application_material_package import validate_package


class ApplicationMaterialPackageValidationTests(unittest.TestCase):
    def make_package(self, path: Path, *, site="A공장", excluded_payload="", count_delta=0):
        root = "테스트기업_지원용_환경자료"
        record_path = f"02_환경인허가_ENVINFO/{site}/환경정보공개_{site}_2024.pdf"
        attachment_path = f"02_환경인허가_ENVINFO/{site}/첨부자료/2024_자료.pdf"
        attachment = b"%PDF-test-attachment"
        digest = hashlib.sha256(attachment).hexdigest()

        summary = {
            "schema_version": "application-material-package-1.2",
            "company": "테스트기업",
            "system_originals_included": False,
            "web_endpoint_extensions_unresolved": 0,
            "envinfo_disclosure_records": 1 + count_delta,
            "envinfo_attachment_references": 1,
            "envinfo_source_attachment_paths": 1,
            "envinfo_unique_attachments": 1,
            "envinfo_duplicate_attachment_references": 0,
            "envinfo_source_duplicate_attachment_references": 0,
            "envinfo_physical_files": 2,
            "envinfo_site_count": 1,
        }
        scope = {
            "schema_version": "1.1",
            "label": "A공장",
            "target_source_ids": {"ENVINFO": ["TARGET-ENVINFO"]},
            "excluded_source_ids": [
                {
                    "source_key": "CHEM_STATS",
                    "source_site_id": "AAI756N",
                    "source_site_name_raw": "제외계열사(주)",
                    "reason": "SOURCE_ENTITY_NAME_EXTENDS_CURRENT_COMPANY",
                },
                {
                    "source_key": "PRTR",
                    "source_site_id": "860",
                    "source_site_name_raw": "짧은ID계열사(주)",
                    "reason": "SOURCE_ENTITY_NAME_EXTENDS_CURRENT_COMPANY",
                },
            ],
        }
        archive_manifest = {
            "schema_version": "2.0",
            "company_display_name": "테스트기업",
            "target_site_tokens": ["A공장"],
        }
        counts = [
            {"항목": "환경정보_공개레코드", "값": 1 + count_delta, "설명": ""},
            {"항목": "환경정보_첨부관계", "값": 1, "설명": ""},
            {"항목": "환경정보_고유첨부파일", "값": 1, "설명": ""},
            {"항목": "환경정보_중복첨부참조", "값": 0, "설명": ""},
            {"항목": "환경정보_물리파일", "값": 2, "설명": ""},
            {"항목": "환경정보_사업장", "값": 1, "설명": ""},
        ]
        count_io = io.StringIO(newline="")
        writer = csv.DictWriter(count_io, fieldnames=["항목", "값", "설명"])
        writer.writeheader()
        writer.writerows(counts)

        refs_io = io.StringIO(newline="")
        writer = csv.DictWriter(
            refs_io,
            fieldnames=[
                "logical_path",
                "stored_path",
                "site",
                "year",
                "bytes",
                "sha256",
                "reference_type",
                "source_archive_path",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "logical_path": attachment_path,
                "stored_path": attachment_path,
                "site": site,
                "year": "2024",
                "bytes": len(attachment),
                "sha256": digest,
                "reference_type": "STORED_FILE",
                "source_archive_path": "source/attachment.pdf",
            }
        )

        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{root}/{record_path}", b"%PDF-test-record")
            z.writestr(f"{root}/{attachment_path}", attachment)
            z.writestr(
                f"{root}/00_자료목록/지원용_패키지_요약.json",
                json.dumps(summary, ensure_ascii=False),
            )
            z.writestr(
                f"{root}/00_자료목록/원본검증목록/Requested_Scope.json",
                json.dumps(scope, ensure_ascii=False),
            )
            z.writestr(
                f"{root}/00_자료목록/원본검증목록/Archive_Manifest.json",
                json.dumps(archive_manifest, ensure_ascii=False),
            )
            z.writestr(
                f"{root}/00_자료목록/ENVINFO_자료수_설명.csv",
                count_io.getvalue().encode("utf-8-sig"),
            )
            z.writestr(
                f"{root}/00_자료목록/ENVINFO_첨부자료_참조목록.csv",
                refs_io.getvalue().encode("utf-8-sig"),
            )
            z.writestr(
                f"{root}/05_화학물질/화학물질통계/화학물질통계_정리.csv",
                ("사업장ID,사업장명\nTARGET,테스트기업\n" + excluded_payload).encode("utf-8-sig"),
            )
            z.writestr(
                f"{root}/05_화학물질/PRTR_배출이동량/PRTR_정리.csv",
                "사업장ID,측정값\nTARGET,860\n".encode("utf-8-sig"),
            )

    def test_valid_package_passes_and_short_numeric_id_does_not_false_match(self):
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "valid.zip"
            self.make_package(package)
            result = validate_package(str(package), "테스트기업")
            self.assertEqual(result["status"], "PASS")
            self.assertIn("VERIFIED_EXCLUSION_RECHECK", result["checks"])

    def test_count_identity_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "bad-count.zip"
            self.make_package(package, count_delta=1)
            with self.assertRaisesRegex(RuntimeError, "ENVINFO count identity failed"):
                validate_package(str(package), "테스트기업")

    def test_out_of_scope_envinfo_site_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "bad-site.zip"
            self.make_package(package, site="B공장")
            with self.assertRaisesRegex(RuntimeError, "outside requested target_site_tokens"):
                validate_package(str(package), "테스트기업")

    def test_verified_excluded_entity_name_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "bad-entity.zip"
            self.make_package(package, excluded_payload="AAI756N,제외계열사(주)\n")
            with self.assertRaisesRegex(RuntimeError, "verified excluded source entity leaked"):
                validate_package(str(package), "테스트기업")


if __name__ == "__main__":
    unittest.main()
