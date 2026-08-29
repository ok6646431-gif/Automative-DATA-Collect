import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "collectors"))
import envinfo_attachment_recovery as recovery


class EnvInfoRecoveryInterruptionTests(unittest.TestCase):
    def test_missing_downloaded_reference_is_requeued(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            row = {k: "" for k in recovery.RECOVERY_FIELDS}
            row.update({
                "collection_status": "DOWNLOADED",
                "stored_path": "output/ENVINFO/raw_attachments/2024/C1/missing.pdf",
                "file_id": "F1",
                "file_ext": "pdf",
                "year": "2024",
                "compId": "C1",
            })
            changed = recovery.requeue_missing_downloaded([row], root)
            self.assertEqual(changed, 1)
            self.assertEqual(row["collection_status"], "DOWNLOAD_FAILED")
            self.assertEqual(row["error"], recovery.MISSING_FILE_ERROR)
            self.assertEqual(row["storage_state"], "MISSING_FILE_RETRY_REQUIRED")
            self.assertEqual(row["storage_reference"], "output/ENVINFO/raw_attachments/2024/C1/missing.pdf")
            self.assertEqual(row["stored_path"], "")


if __name__ == "__main__":
    unittest.main()
