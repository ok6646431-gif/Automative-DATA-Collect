"""Patch the scripted-report crawler to invoke generic literal-PDF recovery.

The candidate parser already supports same-host PDF paths passed directly to arbitrary
JavaScript functions.  The outer crawler must also call that parser when a page has
such controls even if it does not contain the legacy ``fileDownload`` function name.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "orchestrator/g0_scripted_report_enrichment.py"
TEST = ROOT / "tests/test_g0_scripted_report_enrichment.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one patch target, found {count}")
    return text.replace(old, new, 1)


def patch_source() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    old = '''        if "fileDownload" in response.text:\n            candidates.extend(candidates_from_scripted_page(\n                http, response.url, response.text, start_year, current_year\n            ))\n'''
    new = '''        has_literal_pdf_control = "onclick" in response.text and ".pdf" in response.text.casefold()\n        if "fileDownload" in response.text or has_literal_pdf_control:\n            candidates.extend(candidates_from_scripted_page(\n                http, response.url, response.text, start_year, current_year\n            ))\n'''
    SOURCE.write_text(replace_once(text, old, new, "scripted crawler invocation gate"), encoding="utf-8")


def patch_test() -> None:
    text = TEST.read_text(encoding="utf-8")
    old_import = '''from orchestrator.g0_scripted_report_enrichment import (\n    _page_download_prefixes,\n    candidates_from_scripted_page,\n    extract_download_prefixes,\n)\n'''
    new_import = '''from orchestrator.g0_scripted_report_enrichment import (\n    _crawl_for_scripted_candidates,\n    _page_download_prefixes,\n    candidates_from_scripted_page,\n    extract_download_prefixes,\n)\n'''
    text = replace_once(text, old_import, new_import, "crawl helper test import")

    anchor = '''    def test_literal_pdf_argument_still_requires_report_semantics(self):\n        html = ''' + "'''" + '''\n        <html><body>\n          <a onclick="downloadAsset('2024 회사 브로슈어','/upload/annual_range.pdf','url')">다운로드</a>\n        </body></html>\n        ''' + "'''" + '''\n        found = candidates_from_scripted_page(\n            FakeHttp(),\n            "https://official.example/media/",\n            html,\n            2020,\n            2026,\n        )\n        self.assertEqual(found, [])\n'''
    addition = anchor + '''\n    def test_crawl_invokes_literal_pdf_parser_without_legacy_function_name(self):\n        page_html = ''' + "'''" + '''\n        <html><body>\n          <section class="annual-report">\n            <h3>지속가능성 보고서</h3>\n            <a onclick="fnFileDown('2022_23년 지속가능경영보고서(국문)','/upload/annual_range.pdf','url')">국문 다운로드</a>\n          </section>\n        </body></html>\n        ''' + "'''" + '''\n\n        class CrawlHttp(FakeHttp):\n            def get(self, url, **kwargs):\n                self.get_calls.append(url)\n                if url.endswith('/esg/sustainability.do'):\n                    return FakeResponse(url, text=page_html, content_type='text/html')\n                if url.endswith('/upload/annual_range.pdf'):\n                    return FakeResponse(url, content=b'%PDF-1.7\\nliteral-crawl', content_type='application/pdf')\n                return FakeResponse(url, status=404)\n\n        found, pages = _crawl_for_scripted_candidates(\n            CrawlHttp(),\n            'https://official.example/esg/sustainability.do',\n            2020,\n            2026,\n            max_pages=2,\n        )\n        self.assertEqual(pages, ['https://official.example/esg/sustainability.do'])\n        self.assertEqual(len(found), 1)\n        self.assertEqual(found[0]['year'], 2023)\n        self.assertEqual(found[0]['download_contract'], 'VERIFIED_SAME_HOST_LITERAL_PDF_ARG')\n'''
    TEST.write_text(replace_once(text, anchor, addition, "crawler literal PDF regression"), encoding="utf-8")


def main() -> int:
    patch_source()
    patch_test()
    subprocess.run([sys.executable, "-m", "unittest", "tests.test_g0_scripted_report_enrichment", "-v"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-m", "py_compile", "orchestrator/g0_scripted_report_enrichment.py"], cwd=ROOT, check=True)
    print("literal-PDF pages now reach scripted report parser; regression-tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
