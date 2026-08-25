import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.archive_stage import finalize_archive_manifest


class ArchiveStageManifestTests(unittest.TestCase):
    def test_final_manifest_is_synced_to_index_and_system_raw(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive_root = root / "Human_Archive" / "테스트_환경자료"
            index_dir = archive_root / "00_자료목록"
            system_dir = archive_root / "90_시스템원본" / "control_plane"
            index_dir.mkdir(parents=True)
            system_dir.mkdir(parents=True)

            building = {
                "schema_version": "1.6",
                "human_archive": {"status": "BUILDING"},
            }
            (root / "Master_Manifest.json").write_text(
                json.dumps(building, ensure_ascii=False), encoding="utf-8"
            )
            (system_dir / "Master_Manifest.json").write_text(
                json.dumps(building, ensure_ascii=False), encoding="utf-8"
            )

            summary = {
                "schema_version": "2.0",
                "archive_root": "테스트_환경자료",
                "archive_completeness": "COMPLETE",
                "acceptance_checks": {},
            }
            finalize_archive_manifest(root, building, summary)

            index_manifest = json.loads(
                (index_dir / "Master_Manifest.json").read_text(encoding="utf-8")
            )
            system_manifest = json.loads(
                (system_dir / "Master_Manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(index_manifest["human_archive"]["status"], "PASS")
            self.assertEqual(system_manifest["human_archive"]["status"], "PASS")
            self.assertEqual(index_manifest["human_archive"], system_manifest["human_archive"])


if __name__ == "__main__":
    unittest.main()
