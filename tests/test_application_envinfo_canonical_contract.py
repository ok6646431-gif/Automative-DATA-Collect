import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from orchestrator.archive_user_dedup_v2 import canonicalize_user_envinfo
from tools.build_application_material_package import build
from tools.validate_application_material_package import validate_package


class ApplicationEnvinfoCanonicalContractTests(unittest.TestCase):
    def test_canonical_store_restores_site_relations_and_crossfolder_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "테스트기업_환경자료"
            env = root / "01_사용자자료" / "03_환경정보공개시스템"
            report = root / "01_사용자자료" / "04_지속가능경영보고서"
            idx = root / "00_자료목록"
            for path in [env / "A사업장" / "첨부자료", env / "B사업장" / "첨부자료", report, idx]:
                path.mkdir(parents=True, exist_ok=True)
            (idx / "README_먼저읽기.txt").write_text("Archive v2 사용 안내\n", encoding="utf-8")

            (env / "A사업장" / "환경정보공개_A사업장_2024.pdf").write_bytes(b"%PDF-detail-a")
            (env / "B사업장" / "환경정보공개_B사업장_2024.pdf").write_bytes(b"%PDF-detail-b")
            shared = b"%PDF-shared" + b"A" * 2000 + b"%%EOF"
            unique = b"%PDF-unique" + b"B" * 1500 + b"%%EOF"
            (env / "A사업장" / "첨부자료" / "2024_공통보고서.pdf").write_bytes(shared)
            (env / "B사업장" / "첨부자료" / "2024_공통보고서.pdf").write_bytes(shared)
            (env / "A사업장" / "첨부자료" / "2024_고유자료.pdf").write_bytes(unique)
            (report / "테스트기업_지속가능경영보고서_2024.pdf").write_bytes(shared)

            stats = canonicalize_user_envinfo(root)
            self.assertEqual(stats["envinfo_attachment_occurrences"], 3)
            self.assertTrue((idx / "ENVINFO_첨부자료_참조표.csv").exists())
            refs = list(csv.DictReader((idx / "ENVINFO_첨부자료_참조표.csv").open(encoding="utf-8-sig", newline="")))
            original_refs = [r for r in refs if "/첨부자료/" in r["원래_사용자경로"]]
            self.assertEqual(len(original_refs), 3)
            self.assertTrue(any("04_지속가능경영보고서" in r["최종_보존경로"] for r in original_refs))

            scope = {
                "schema_version": "1.1",
                "target_source_ids": {"ENVINFO": ["A-ID", "B-ID"]},
                "excluded_source_ids": [],
            }
            manifest = {
                "schema_version": "2.0",
                "company_display_name": "테스트기업",
                "archive_completeness": "COMPLETE",
                "target_site_tokens": ["A사업장", "B사업장"],
                "target_source_ids": {"ENVINFO": ["A-ID", "B-ID"]},
            }
            (idx / "Requested_Scope.json").write_text(json.dumps(scope, ensure_ascii=False), encoding="utf-8")
            (idx / "Archive_Manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            analysis = io.StringIO(newline="")
            writer = csv.DictWriter(analysis, fieldnames=["scope_label", "source_key", "source_site_id", "source_site_name_raw"])
            writer.writeheader()
            writer.writerow({"scope_label": "test", "source_key": "ENVINFO", "source_site_id": "A-ID", "source_site_name_raw": "A사업장"})
            writer.writerow({"scope_label": "test", "source_key": "ENVINFO", "source_site_id": "B-ID", "source_site_name_raw": "B사업장"})
            (idx / "Analysis_Scope.csv").write_text(analysis.getvalue(), encoding="utf-8-sig")

            source = base / "Human_Archive.zip"
            with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for p in root.rglob("*"):
                    if p.is_file():
                        z.write(p, f"{root.name}/{p.relative_to(root).as_posix()}")

            output = base / "support.zip"
            result = build(str(source), str(output), "테스트기업_지원용_환경자료", "테스트기업", "123")
            self.assertEqual(result["envinfo_disclosure_records"], 2)
            self.assertEqual(result["envinfo_attachment_references"], 3)
            self.assertEqual(result["envinfo_unique_attachments"], 2)
            self.assertEqual(result["envinfo_physical_files"], 4)
            self.assertEqual(result["envinfo_site_count"], 2)

            validation = validate_package(str(output), "테스트기업")
            self.assertEqual(validation["status"], "PASS")
            self.assertIn("ENVINFO_SITE_SCOPE", validation["checks"])

            with zipfile.ZipFile(output) as z:
                names = z.namelist()
                self.assertFalse(any("02_환경인허가_ENVINFO/첨부자료_원문/" in n and "환경정보공개_" in n for n in names))
                ref_text = z.read("테스트기업_지원용_환경자료/00_자료목록/ENVINFO_첨부자료_참조목록.csv").decode("utf-8-sig")
                support_refs = list(csv.DictReader(io.StringIO(ref_text)))
                self.assertEqual({r["site"] for r in support_refs}, {"A사업장", "B사업장"})


if __name__ == "__main__":
    unittest.main()
