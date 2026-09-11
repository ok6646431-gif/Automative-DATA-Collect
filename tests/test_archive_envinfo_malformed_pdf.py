import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))

from archive_builder import build_envinfo_user, copy_system_raw, promote_envinfo_references


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["source_key"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class MalformedEnvinfoPdfArchiveTests(unittest.TestCase):
    def test_malformed_pdf_is_notice_only_in_user_layer_and_raw_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "Human_Archive" / "예시회사_환경자료"
            env = root / "output" / "ENVINFO"
            raw = env / "raw_attachments" / "2020" / "C1" / "비상조치결과.pdf"
            raw.parent.mkdir(parents=True)
            raw.write_bytes(b"not a pdf response body")

            (root / "Company_Profile.json").write_text(
                json.dumps(
                    {
                        "company_display_name": "예시회사",
                        "site_candidates": [
                            {
                                "site_name_raw": "예시공장",
                                "identity_status": "CONFIRMED",
                                "verification_state": "VERIFIED",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "Requested_Scope.json").write_text("{}", encoding="utf-8")
            write_csv(env / "discovery.csv", [])
            write_csv(
                env / "attachment_index.csv",
                [
                    {
                        "year": "2020",
                        "compId": "C1",
                        "compNm": "예시공장",
                        "section_id": "inquiry26",
                        "section_title": "환경(지속가능)보고서 발간 현황",
                        "file_id": "F1",
                        "original_filename": "비상조치결과.pdf",
                        "stored_path": str(raw.relative_to(root)),
                        "bytes": str(raw.stat().st_size),
                        "sha256": "bad-pdf",
                        "content_type": "application/pdf",
                        "importance": "SUPPORTING",
                        "document_category": "OTHER_ENVINFO_EVIDENCE",
                        "collection_status": "DOWNLOADED",
                        "error": "",
                    }
                ],
            )

            created, failures, exclusions = build_envinfo_user(
                root,
                archive,
                {"ENVINFO": {"C1"}},
                {("ENVINFO", "C1"): "예시공장"},
            )

            attachment_dir = archive / "01_사용자자료" / "03_환경정보공개시스템" / "예시공장" / "첨부자료"
            notices = list(attachment_dir.glob("*_원본파일이상.txt"))
            self.assertEqual(len(notices), 1)
            self.assertFalse(any(attachment_dir.glob("*.pdf")))
            self.assertEqual(exclusions, [])
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["issue_type"], "ENVINFO_ATTACHMENT_INVALID_PDF")
            self.assertEqual(created, notices)
            notice = notices[0].read_text(encoding="utf-8")
            self.assertIn("90_시스템원본/ENVINFO/raw_attachments/2020/C1/비상조치결과.pdf", notice)
            self.assertIn("REVIEW_REQUIRED", notice)

            promoted = promote_envinfo_references(root, archive, {"ENVINFO": {"C1"}}, "예시회사")
            self.assertEqual(promoted, [])
            self.assertFalse((archive / "01_사용자자료" / "04_지속가능경영보고서").exists())

            copy_system_raw(root, archive)
            preserved = archive / "90_시스템원본" / "ENVINFO" / "raw_attachments" / "2020" / "C1" / "비상조치결과.pdf"
            self.assertTrue(preserved.exists())
            self.assertEqual(preserved.read_bytes(), raw.read_bytes())


if __name__ == "__main__":
    unittest.main()
