import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.build_application_material_package import build


class ApplicationMaterialPackageTests(unittest.TestCase):
    def test_envinfo_duplicate_attachments_become_logical_references(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "Human_Archive.zip"
            output = root / "support.zip"
            archive_root = "테스트기업_환경자료"
            shared = b"%PDF-shared-envinfo-attachment"
            unique = b"%PDF-unique-envinfo-attachment"

            with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr(
                    f"{archive_root}/01_사용자자료/03_환경정보공개시스템/A사업장/환경정보공개_A사업장_2024.pdf",
                    b"%PDF-detail-a",
                )
                z.writestr(
                    f"{archive_root}/01_사용자자료/03_환경정보공개시스템/B사업장/환경정보공개_B사업장_2024.pdf",
                    b"%PDF-detail-b",
                )
                z.writestr(
                    f"{archive_root}/01_사용자자료/03_환경정보공개시스템/A사업장/첨부자료/2024_공통보고서.pdf",
                    shared,
                )
                z.writestr(
                    f"{archive_root}/01_사용자자료/03_환경정보공개시스템/B사업장/첨부자료/2024_공통보고서.pdf",
                    shared,
                )
                z.writestr(
                    f"{archive_root}/01_사용자자료/03_환경정보공개시스템/B사업장/첨부자료/2024_B고유자료.pdf",
                    unique,
                )
                # Deduplication is deliberately scoped to ENVINFO attachments. A copy
                # classified as a sustainability report keeps its own user-facing file.
                z.writestr(
                    f"{archive_root}/01_사용자자료/04_지속가능경영보고서/테스트기업_보고서_2024.pdf",
                    shared,
                )
                prior_reference = io.StringIO(newline="")
                writer = csv.DictWriter(
                    prior_reference,
                    fieldnames=[
                        "removed_user_path",
                        "retained_user_path",
                        "bytes",
                        "sha256",
                        "resolution",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "removed_user_path": "01_사용자자료/03_환경정보공개시스템/A사업장/첨부자료/2023_공통보고서.pdf",
                        "retained_user_path": "01_사용자자료/03_환경정보공개시스템/A사업장/첨부자료/2024_공통보고서.pdf",
                        "bytes": len(shared),
                        "sha256": hashlib.sha256(shared).hexdigest(),
                        "resolution": "IDENTICAL_SHA256_SAME_USER_FOLDER",
                    }
                )
                z.writestr(
                    f"{archive_root}/00_자료목록/Deduplicated_User_File_References.csv",
                    prior_reference.getvalue().encode("utf-8-sig"),
                )

            result = build(
                str(source),
                str(output),
                "테스트기업_지원용_환경자료",
                "테스트기업",
                "12345",
            )

            self.assertEqual(result["schema_version"], "application-material-package-1.2")
            self.assertEqual(result["envinfo_disclosure_records"], 2)
            self.assertEqual(result["envinfo_attachment_references"], 4)
            self.assertEqual(result["envinfo_source_attachment_paths"], 3)
            self.assertEqual(result["envinfo_unique_attachments"], 2)
            self.assertEqual(result["envinfo_duplicate_attachment_references"], 2)
            self.assertEqual(result["envinfo_source_duplicate_attachment_references"], 1)
            self.assertEqual(result["envinfo_physical_files"], 4)
            self.assertEqual(result["envinfo_site_count"], 2)
            self.assertEqual(result["envinfo_duplicate_attachment_bytes_avoided"], len(shared) * 2)

            package_root = "테스트기업_지원용_환경자료"
            with zipfile.ZipFile(output) as z:
                names = set(z.namelist())
                retained = "02_환경인허가_ENVINFO/A사업장/첨부자료/2024_공통보고서.pdf"
                referenced = "02_환경인허가_ENVINFO/B사업장/첨부자료/2024_공통보고서.pdf"
                self.assertIn(f"{package_root}/{retained}", names)
                self.assertNotIn(f"{package_root}/{referenced}", names)
                self.assertIn(
                    f"{package_root}/06_지속가능경영보고서/테스트기업_보고서_2024.pdf",
                    names,
                )

                references = list(
                    csv.DictReader(
                        io.StringIO(
                            z.read(
                                f"{package_root}/00_자료목록/ENVINFO_첨부자료_참조목록.csv"
                            ).decode("utf-8-sig")
                        )
                    )
                )
                self.assertEqual(len(references), 4)
                duplicate = next(row for row in references if row["logical_path"] == referenced)
                self.assertEqual(duplicate["stored_path"], retained)
                self.assertEqual(duplicate["reference_type"], "IDENTICAL_SHA256_REFERENCE")
                prior_duplicate = next(
                    row for row in references if row["logical_path"].endswith("2023_공통보고서.pdf")
                )
                self.assertEqual(prior_duplicate["stored_path"], retained)
                self.assertEqual(
                    prior_duplicate["reference_type"], "IDENTICAL_SHA256_SOURCE_REFERENCE"
                )

                inventory = list(
                    csv.DictReader(
                        io.StringIO(
                            z.read(
                                f"{package_root}/00_자료목록/지원용_전체자료목록.csv"
                            ).decode("utf-8-sig")
                        )
                    )
                )
                inventory_paths = {row["path"] for row in inventory}
                self.assertIn(retained, inventory_paths)
                self.assertNotIn(referenced, inventory_paths)

                counts = {
                    row["항목"]: int(row["값"])
                    for row in csv.DictReader(
                        io.StringIO(
                            z.read(
                                f"{package_root}/00_자료목록/ENVINFO_자료수_설명.csv"
                            ).decode("utf-8-sig")
                        )
                    )
                }
                self.assertEqual(counts["환경정보_공개레코드"], 2)
                self.assertEqual(counts["환경정보_첨부관계"], 4)
                self.assertEqual(counts["환경정보_고유첨부파일"], 2)
                self.assertEqual(counts["환경정보_물리파일"], 4)

                summary = json.loads(
                    z.read(
                        f"{package_root}/00_자료목록/지원용_패키지_요약.json"
                    ).decode("utf-8")
                )
                self.assertEqual(summary["envinfo_attachment_references"], 4)


    def test_human_archive_semantic_reference_uses_retained_digest_and_preserves_source_digest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "Human_Archive.zip"
            output = root / "support.zip"
            archive_root = "테스트기업_환경자료"

            source_bytes = b"%PDF-source-semantic-copy"
            retained_bytes = b"%PDF-retained-official-copy"
            source_digest = hashlib.sha256(source_bytes).hexdigest()
            retained_digest = hashlib.sha256(retained_bytes).hexdigest()

            reference = io.StringIO(newline="")
            writer = csv.DictWriter(
                reference,
                fieldnames=[
                    "사업장",
                    "공개연도",
                    "원래_사용자경로",
                    "최종_보존경로",
                    "파일명",
                    "용량_bytes",
                    "SHA256",
                    "최종_보존_SHA256",
                    "처리",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "사업장": "A사업장",
                    "공개연도": "2022",
                    "원래_사용자경로": "01_사용자자료/03_환경정보공개시스템/A사업장/첨부자료/2022_보고서.pdf",
                    "최종_보존경로": "01_사용자자료/04_지속가능경영보고서/테스트기업_보고서_2022.pdf",
                    "파일명": "2022_보고서.pdf",
                    "용량_bytes": len(source_bytes),
                    "SHA256": source_digest,
                    "최종_보존_SHA256": retained_digest,
                    "처리": "SEMANTIC_PDF_DUPLICATE_CANONICAL_REPORT:test",
                }
            )

            with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr(
                    f"{archive_root}/01_사용자자료/03_환경정보공개시스템/A사업장/환경정보공개_A사업장_2022.pdf",
                    b"%PDF-detail",
                )
                z.writestr(
                    f"{archive_root}/01_사용자자료/04_지속가능경영보고서/테스트기업_보고서_2022.pdf",
                    retained_bytes,
                )
                z.writestr(
                    f"{archive_root}/00_자료목록/ENVINFO_첨부자료_참조표.csv",
                    reference.getvalue().encode("utf-8-sig"),
                )

            result = build(
                str(source),
                str(output),
                "테스트기업_지원용_환경자료",
                "테스트기업",
                "12345",
            )
            self.assertEqual(result["envinfo_attachment_references"], 1)
            self.assertEqual(result["envinfo_unique_attachments"], 1)

            with zipfile.ZipFile(output) as z:
                rows = list(
                    csv.DictReader(
                        io.StringIO(
                            z.read(
                                "테스트기업_지원용_환경자료/00_자료목록/ENVINFO_첨부자료_참조목록.csv"
                            ).decode("utf-8-sig")
                        )
                    )
                )
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["sha256"], retained_digest)
            self.assertEqual(row["source_sha256"], source_digest)
            self.assertEqual(
                row["reference_type"],
                "HUMAN_ARCHIVE_SEMANTIC_CANONICAL_REFERENCE",
            )


if __name__ == "__main__":
    unittest.main()
