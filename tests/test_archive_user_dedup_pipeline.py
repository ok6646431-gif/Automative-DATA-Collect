import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from orchestrator import archive_user_dedup_pipeline as pipeline


class ArchiveUserDedupPipelineExecutionModeTests(unittest.TestCase):
    def _package_with_zip(self, root: Path) -> Path:
        package = root / "assembled"
        package.mkdir()
        with zipfile.ZipFile(package / "Human_Archive.zip", "w") as zf:
            zf.writestr("Company/00_자료목록/README_먼저읽기.txt", "ok")
        return package

    def test_live_archive_tree_avoids_zip_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            package = self._package_with_zip(Path(td))
            live_root = package / "Human_Archive" / "Company"
            live_root.mkdir(parents=True)

            expected = {"dedup_execution_mode": "LIVE_ARCHIVE_TREE_SINGLE_REWRITE"}
            with mock.patch.object(pipeline, "_process_archive_tree", return_value=expected) as process, \
                 mock.patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("live mode must not extract ZIP")):
                result = pipeline.run(package)

            self.assertEqual(result, expected)
            self.assertEqual(process.call_count, 1)
            args = process.call_args.args
            self.assertEqual(args[2], live_root)
            self.assertGreater(args[3], 0)
            self.assertEqual(args[4], "LIVE_ARCHIVE_TREE_SINGLE_REWRITE")

    def test_live_archive_tree_can_run_before_any_zip_exists(self):
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "assembled"
            live_root = package / "Human_Archive" / "Company"
            live_root.mkdir(parents=True)
            (live_root / "payload.txt").write_text("ok", encoding="utf-8")

            expected = {"dedup_execution_mode": "LIVE_ARCHIVE_TREE_PREZIP_SINGLE_WRITE"}
            with mock.patch.object(pipeline, "_process_archive_tree", return_value=expected) as process, \
                 mock.patch.object(pipeline, "_validate_zip", side_effect=AssertionError("pre-ZIP mode must not validate a missing ZIP")), \
                 mock.patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("pre-ZIP live mode must not extract ZIP")):
                result = pipeline.run(package)

            self.assertEqual(result, expected)
            self.assertFalse((package / "Human_Archive.zip").exists())
            self.assertEqual(process.call_count, 1)
            args = process.call_args.args
            self.assertEqual(args[2], live_root)
            self.assertIsNone(args[3])
            self.assertEqual(args[4], "LIVE_ARCHIVE_TREE_PREZIP_SINGLE_WRITE")

    def test_standalone_fallback_extracts_zip_once(self):
        with tempfile.TemporaryDirectory() as td:
            package = self._package_with_zip(Path(td))
            original_extractall = zipfile.ZipFile.extractall
            extraction_count = 0

            def counted_extractall(zf, *args, **kwargs):
                nonlocal extraction_count
                extraction_count += 1
                return original_extractall(zf, *args, **kwargs)

            expected = {"dedup_execution_mode": "SINGLE_TEMP_EXTRACTION_SINGLE_REWRITE"}
            with mock.patch.object(pipeline, "_process_archive_tree", return_value=expected) as process, \
                 mock.patch.object(zipfile.ZipFile, "extractall", new=counted_extractall):
                result = pipeline.run(package)

            self.assertEqual(result, expected)
            self.assertEqual(extraction_count, 1)
            self.assertEqual(process.call_count, 1)
            self.assertEqual(process.call_args.args[4], "SINGLE_TEMP_EXTRACTION_SINGLE_REWRITE")


if __name__ == "__main__":
    unittest.main()
