import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator"))

from human_archive_raw_policy import (
    assert_human_archive_raw_separated,
    raw_preservation_stats,
    rewrite_human_archive_raw_references,
    suppress_system_raw_copy,
)


class HumanArchiveRawPolicyTests(unittest.TestCase):
    def test_raw_output_is_preserved_without_copying_into_human_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "output" / "ENVINFO" / "raw_attachments" / "x.pdf"
            raw.parent.mkdir(parents=True)
            raw.write_bytes(b"raw-evidence")
            archive = root / "Human_Archive" / "회사_환경자료"
            archive.mkdir(parents=True)

            result = suppress_system_raw_copy(root, archive)

            self.assertTrue(raw.exists())
            self.assertFalse((archive / "90_시스템원본").exists())
            self.assertEqual(result["policy"], "EXTERNAL_TO_HUMAN_ARCHIVE")
            self.assertEqual(result["raw_files"], 1)
            self.assertEqual(result["raw_bytes"], len(b"raw-evidence"))
            self.assertTrue(result["preserved_in_final_package"])

    def test_leaked_system_raw_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "회사_환경자료"
            leaked = archive / "90_시스템원본" / "ENVINFO" / "raw.bin"
            leaked.parent.mkdir(parents=True)
            leaked.write_bytes(b"leak")

            with self.assertRaisesRegex(RuntimeError, "HUMAN_ARCHIVE_SYSTEM_RAW_LEAK"):
                assert_human_archive_raw_separated(archive)

    def test_empty_legacy_system_root_is_removed(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "회사_환경자료"
            (archive / "90_시스템원본" / "empty").mkdir(parents=True)

            self.assertTrue(assert_human_archive_raw_separated(archive))
            self.assertFalse((archive / "90_시스템원본").exists())

    def test_legacy_readme_and_notice_are_rewritten(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "회사_환경자료"
            readme = archive / "00_자료목록" / "README_먼저읽기.txt"
            notice = archive / "01_사용자자료" / "03_환경정보공개시스템" / "원본파일이상.txt"
            readme.parent.mkdir(parents=True)
            notice.parent.mkdir(parents=True)
            readme.write_text(
                "HTML/JSON/JSONL/실행로그 등 재현·개발용 원본은 90_시스템원본에 분리했습니다.\n",
                encoding="utf-8",
            )
            notice.write_text(
                "원본 바이트는 수정하지 않았으며 시스템 원본 영역에 그대로 보존됩니다.\n"
                "90_시스템원본에서 원본 경로를 확인하십시오.\n",
                encoding="utf-8",
            )

            changed = rewrite_human_archive_raw_references(archive)

            self.assertEqual(changed, 2)
            self.assertNotIn("90_시스템원본", readme.read_text(encoding="utf-8"))
            self.assertNotIn("90_시스템원본", notice.read_text(encoding="utf-8"))
            self.assertIn("최종 전체 패키지", readme.read_text(encoding="utf-8"))
            self.assertIn("최종 전체 패키지", notice.read_text(encoding="utf-8"))

    def test_raw_stats_count_only_external_output_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "output" / "A").mkdir(parents=True)
            (root / "output" / "A" / "1.bin").write_bytes(b"1234")
            (root / "output" / "A" / "2.bin").write_bytes(b"56")
            (root / "unrelated.bin").write_bytes(b"outside")

            stats = raw_preservation_stats(root)

            self.assertEqual(stats["raw_files"], 2)
            self.assertEqual(stats["raw_bytes"], 6)


if __name__ == "__main__":
    unittest.main()
