import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator import envinfo_content_qa as qa
from orchestrator.scope_quality import classify_archive_summary


class EnvInfoContentQATests(unittest.TestCase):
    @staticmethod
    def _token_text(count):
        return " ".join(f"token{i:03d}" for i in range(count))

    def test_thresholds_are_fail_closed(self):
        source = self._token_text(100)
        self.assertEqual(qa.compare_text(source, self._token_text(100))["verdict"], "PASS")
        self.assertEqual(qa.compare_text(source, self._token_text(96))["verdict"], "WARN")
        self.assertEqual(qa.compare_text(source, self._token_text(94))["verdict"], "FAIL")

    def test_evaluate_writes_full_scope_csv_and_passes_fifteen_items(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            archive = Path(td) / "archive"
            env = root / "output" / "ENVINFO"
            detail = env / "raw_detail"
            detail.mkdir(parents=True)
            pdf_dir = archive / "01_사용자자료" / "03_환경정보공개시스템" / "예시공장"
            pdf_dir.mkdir(parents=True)

            rows = []
            scope = set()
            for year in range(2010, 2025):
                comp = f"C{year}"
                scope.add(comp)
                rows.append({"year": str(year), "compId": comp, "compNm": "예시공장"})
                (detail / f"{year}_{comp}_예시공장.html").write_text("<div class='inquiry_cont'>x</div>", encoding="utf-8")
                (pdf_dir / f"환경정보공개_예시공장_{year}_전체내용정적재현본.pdf").write_bytes(b"%PDF-1.4\n%%EOF")

            with (env / "discovery.csv").open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["year", "compId", "compNm"])
                writer.writeheader()
                writer.writerows(rows)

            source = self._token_text(100)
            pdf = self._token_text(98)
            with patch.object(qa, "_source_text", return_value=(source, 7)), patch.object(
                qa, "_pdf_text", return_value=(pdf, 3)
            ):
                result = qa.evaluate(
                    root,
                    archive,
                    scope,
                    labels={},
                    site_tokens=[("예시공장", qa._norm_site("예시공장"))],
                )

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["expected_items"], 15)
            self.assertEqual(result["checked_items"], 15)
            self.assertEqual(result["pass_items"], 15)
            self.assertEqual(result["warn_items"], 0)
            self.assertEqual(result["fail_items"], 0)
            csv_path = archive / "00_자료목록" / "ENVINFO_Content_QA.csv"
            self.assertTrue(csv_path.exists())
            with csv_path.open(encoding="utf-8-sig", newline="") as f:
                written = list(csv.DictReader(f))
            self.assertEqual(len(written), 15)
            self.assertTrue(all(row["판정"] == "PASS" for row in written))

    def test_missing_user_pdf_blocks_qa(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            archive = Path(td) / "archive"
            env = root / "output" / "ENVINFO"
            detail = env / "raw_detail"
            detail.mkdir(parents=True)
            with (env / "discovery.csv").open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["year", "compId", "compNm"])
                writer.writeheader()
                writer.writerow({"year": "2024", "compId": "ABC", "compNm": "예시공장"})
            (detail / "2024_ABC_예시공장.html").write_text(
                "<div class='inquiry_cont'>정상 원문</div>", encoding="utf-8"
            )

            result = qa.evaluate(
                root,
                archive,
                {"ABC"},
                labels={},
                site_tokens=[("예시공장", qa._norm_site("예시공장"))],
            )
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["fail_items"], 1)

    def test_false_content_fidelity_check_makes_archive_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Collection_Completeness.json").write_text(
                json.dumps({"status": "COMPLETE"}), encoding="utf-8"
            )
            result = classify_archive_summary(
                root,
                {
                    "acceptance_checks": {
                        "envinfo_content_fidelity": False,
                        "guideline_reference_present": True,
                    }
                },
            )
            self.assertEqual(result["archive_completeness"], "INCOMPLETE")
            self.assertFalse(result["blocking_acceptance_checks"]["envinfo_content_fidelity"])


if __name__ == "__main__":
    unittest.main()
