import tempfile
import unittest
from pathlib import Path
from unittest import mock

from orchestrator import user_archive_format as fmt


class UserArchiveHtmlNormalizationTests(unittest.TestCase):
    def test_sustainability_endpoint_html_is_rendered_to_same_named_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            user = Path(td) / "01_사용자자료"
            report = user / "04_지속가능경영보고서" / "주식회사 포스코_지속가능경영보고서_2025.html"
            report.parent.mkdir(parents=True)
            report.write_text(
                "<!doctype html><html><body><main><h1>2025 지속가능경영보고서</h1><p>본문</p></main></body></html>",
                encoding="utf-8",
            )

            def fake_render(_html, target):
                Path(target).write_bytes(b"%PDF-1.7\nnormalized\n%%EOF\n")
                return True, ""

            with mock.patch.object(fmt.archive_builder, "render_html_pdf", side_effect=fake_render):
                converted = fmt._render_user_html(user)

            target = report.with_suffix(".pdf")
            self.assertEqual(converted, 1)
            self.assertFalse(report.exists())
            self.assertTrue(target.exists())
            self.assertTrue(target.read_bytes().startswith(b"%PDF-"))

    def test_web_endpoint_normalized_htm_is_also_rendered(self):
        with tempfile.TemporaryDirectory() as td:
            user = Path(td) / "01_사용자자료"
            page = user / "06_회사환경정책" / "기타_공식자료" / "정책페이지.htm"
            page.parent.mkdir(parents=True)
            page.write_text("<html><body><main><h1>환경정책</h1></main></body></html>", encoding="utf-8")

            def fake_render(_html, target):
                Path(target).write_bytes(b"%PDF-1.7\nnormalized\n%%EOF\n")
                return True, ""

            with mock.patch.object(fmt.archive_builder, "render_html_pdf", side_effect=fake_render):
                converted = fmt._render_user_html(user)

            self.assertEqual(converted, 1)
            self.assertFalse(page.exists())
            self.assertTrue(page.with_suffix(".pdf").exists())

    def test_review_machine_companions_are_removed_recursively_not_rendered(self):
        with tempfile.TemporaryDirectory() as td:
            user = Path(td) / "01_사용자자료"
            review = user / "00_환경관리검토" / "내부"
            review.mkdir(parents=True)
            for name in ("brief.html", "summary.json", "cards.jsonl", "notes.md"):
                (review / name).write_text("machine", encoding="utf-8")
            (review / "brief.pdf").write_bytes(b"%PDF-1.7\nkept\n%%EOF\n")

            removed = fmt._remove_review_machine_variants(user)

            self.assertEqual(removed, 4)
            self.assertTrue((review / "brief.pdf").exists())
            self.assertEqual(
                [p for p in review.iterdir() if p.suffix.lower() in fmt.MACHINE_REVIEW_SUFFIXES],
                [],
            )


if __name__ == "__main__":
    unittest.main()
