import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))

import user_archive_format


class UserArchiveFormatTests(unittest.TestCase):
    def test_user_layer_converts_corporate_html_and_removes_machine_review_variants(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "회사_환경자료"
            policy = root / "01_사용자자료" / "06_회사환경정책" / "기타_공식자료"
            review = root / "01_사용자자료" / "00_환경관리검토"
            index = root / "00_자료목록"
            policy.mkdir(parents=True)
            review.mkdir(parents=True)
            index.mkdir(parents=True)

            (policy / "2026_policy.html").write_text(
                '<html><body><div class="wrapper ESG"><h3>환경경영 전략</h3><p>본문</p><script>x()</script></div></body></html>',
                encoding="utf-8",
            )
            for name in ["brief.html", "summary.json", "cards.json", "cards.md"]:
                (review / name).write_text("machine", encoding="utf-8")
            (review / "brief.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
            (review / "evidence.xlsx").write_bytes(b"PK")

            def fake_render(_html, pdf):
                Path(pdf).write_bytes(b"%PDF-1.4\n%%EOF")
                return True, ""

            def fake_xlsx(path, _sheets):
                Path(path).write_bytes(b"PK")

            with patch("user_archive_format.archive_builder.render_html_pdf", side_effect=fake_render), patch(
                "user_archive_format.archive_builder.dict_rows_to_xlsx", side_effect=fake_xlsx
            ):
                result = user_archive_format.normalize_user_archive(root)

            self.assertEqual(result["corporate_html_rendered_to_pdf"], 1)
            self.assertEqual(result["review_machine_variants_removed"], 4)
            self.assertTrue((policy / "2026_환경경영 전략.pdf").exists())
            self.assertFalse(any(policy.glob("*.html")))
            self.assertFalse(any(p.suffix.lower() in {".html", ".json", ".jsonl"} for p in (root / "01_사용자자료").rglob("*")))
            self.assertTrue((index / "사용자자료_목록.csv").exists())
            self.assertTrue((index / "전체자료목록.xlsx").exists())


if __name__ == "__main__":
    unittest.main()
