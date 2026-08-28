import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "collectors"))

import envinfo_attachment_recovery as recovery


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_index(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(recovery.RECOVERY_FIELDS)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def row(**overrides):
    base = {k: "" for k in recovery.RECOVERY_FIELDS}
    base.update({
        "year": "2024",
        "compId": "C1",
        "compNm": "테스트공장",
        "section_id": "inquiry04",
        "section_title": "환경경영",
        "file_id": "F1",
        "file_ext": "pdf",
        "original_filename": "자료.pdf",
        "importance": "SUPPORTING",
        "document_category": "OTHER_ENVINFO_EVIDENCE",
    })
    base.update(overrides)
    return base


class EnvInfoAttachmentRecoveryTests(unittest.TestCase):
    def test_deduplicate_downloaded_counts_unique_physical_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "output/ENVINFO/raw_attachments/2024/C1/a.pdf"
            b = root / "output/ENVINFO/raw_attachments/2024/C2/b.pdf"
            a.parent.mkdir(parents=True); b.parent.mkdir(parents=True)
            payload = b"same-pdf-payload"
            a.write_bytes(payload); b.write_bytes(payload)
            rows = [
                row(compId="C1", stored_path=str(a.relative_to(root)), bytes=str(len(payload)), sha256=digest(payload), collection_status="DOWNLOADED"),
                row(compId="C2", file_id="F2", stored_path=str(b.relative_to(root)), bytes=str(len(payload)), sha256=digest(payload), collection_status="DOWNLOADED"),
            ]

            by_sha, unique_bytes, duplicate_rows, duplicate_bytes = recovery.deduplicate_downloaded(rows, root)

            self.assertEqual(unique_bytes, len(payload))
            self.assertEqual(duplicate_rows, 1)
            self.assertEqual(duplicate_bytes, len(payload))
            self.assertEqual(len(by_sha), 1)
            self.assertTrue(a.exists())
            self.assertFalse(b.exists())
            self.assertEqual(rows[1]["storage_state"], "DEDUPLICATED_REFERENCE")
            self.assertEqual(rows[1]["stored_path"], str(a.relative_to(root)))

    def test_recovery_reuses_duplicate_without_consuming_unique_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); out = root / "output/ENVINFO"
            existing = out / "raw_attachments/2024/C1/a.pdf"
            existing.parent.mkdir(parents=True)
            payload = b"same-payload"
            existing.write_bytes(payload)
            rows = [
                row(stored_path=str(existing.relative_to(root)), bytes=str(len(payload)), sha256=digest(payload), collection_status="DOWNLOADED"),
                row(file_id="F2", compId="C2", collection_status="DOWNLOAD_FAILED", error="ValueError: attachment collection size safety limit exceeded"),
            ]
            write_index(out / "attachment_index.csv", rows)
            (out / "status.json").write_text(json.dumps({"attachment_ok": 1, "attachment_fail": 1, "errors": 1}), encoding="utf-8")

            def fake_download(session, item, attachments_root, max_attempts=2):
                target = Path(attachments_root) / "2024/C2/retry.pdf"
                target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(payload)
                return target, len(payload), digest(payload), "application/pdf", 1

            with patch.object(recovery, "download_without_total_cap", side_effect=fake_download):
                summary = recovery.recover(out, root, total_limit=len(payload))

            saved = recovery.read_rows(out / "attachment_index.csv")
            self.assertEqual(summary["recovered"], 1)
            self.assertEqual(summary["unique_bytes"], len(payload))
            self.assertEqual(summary["remaining_failed"], 0)
            self.assertEqual(saved[1]["collection_status"], "DOWNLOADED")
            self.assertEqual(saved[1]["storage_state"], "DEDUPLICATED_REFERENCE")
            status = json.loads((out / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["attachment_ok"], 2)
            self.assertEqual(status["attachment_fail"], 0)
            self.assertEqual(status["errors"], 0)

    def test_unique_payload_over_budget_is_explicit_skip_not_source_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); out = root / "output/ENVINFO"
            existing = out / "raw_attachments/2024/C1/a.pdf"
            existing.parent.mkdir(parents=True)
            old_payload = b"123456"
            new_payload = b"ABCD"
            existing.write_bytes(old_payload)
            rows = [
                row(stored_path=str(existing.relative_to(root)), bytes=str(len(old_payload)), sha256=digest(old_payload), collection_status="DOWNLOADED"),
                row(file_id="F2", compId="C2", collection_status="DOWNLOAD_FAILED", error="ValueError: attachment collection size safety limit exceeded"),
            ]
            write_index(out / "attachment_index.csv", rows)
            (out / "status.json").write_text(json.dumps({"attachment_ok": 1, "attachment_fail": 1, "errors": 1}), encoding="utf-8")

            def fake_download(session, item, attachments_root, max_attempts=2):
                target = Path(attachments_root) / "2024/C2/retry.pdf"
                target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(new_payload)
                return target, len(new_payload), digest(new_payload), "application/pdf", 1

            with patch.object(recovery, "download_without_total_cap", side_effect=fake_download):
                summary = recovery.recover(out, root, total_limit=8)

            saved = recovery.read_rows(out / "attachment_index.csv")
            self.assertEqual(summary["skipped_budget"], 1)
            self.assertEqual(summary["remaining_failed"], 0)
            self.assertEqual(saved[1]["collection_status"], "SKIPPED_TOTAL_BUDGET")
            status = json.loads((out / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["attachment_fail"], 0)
            self.assertEqual(status["attachment_skipped_budget"], 1)
            self.assertEqual(status["errors"], 0)

    def test_sustainability_report_is_recovered_before_supporting_evidence(self):
        report = row(section_id="inquiry26", importance="SUPPORTING")
        supporting = row(section_id="inquiry04", importance="SUPPORTING")
        self.assertLess(recovery.recovery_priority(report), recovery.recovery_priority(supporting))


if __name__ == "__main__":
    unittest.main()
