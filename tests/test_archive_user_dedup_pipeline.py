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
            self.assertEqual(args[4], "LIVE_ARCHIVE_TREE_SINGLE_REWRITE")

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
