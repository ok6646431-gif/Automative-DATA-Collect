"""Add a generic direct-PDF JavaScript report recovery path.

Official report libraries sometimes expose the real PDF as a quoted argument of a
multi-argument JavaScript call.  Existing token-based recovery stays untouched; this
patch adds a small fail-closed path in front of it.
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

    marker = '''def candidates_from_scripted_page(\n'''
    helpers = '''def _quoted_call_args(raw: str) -> List[str]:\n    values: List[str] = []\n    for match in re.finditer(r"'([^']*)'|\\\"([^\\\"]*)\\\"", str(raw or ""), re.S):\n        values.append(match.group(1) if match.group(1) is not None else match.group(2))\n    return values\n\n\ndef _report_year_from_literal_context(text: str) -> int | None:\n    raw = str(text or "")\n    match = re.search(\n        r"(?<!\\d)(?P<first>(?:19|20)\\d{2})\\s*[_/／-]\\s*(?P<second>(?:19|20)\\d{2}|\\d{2})(?!\\d)",\n        raw,\n    )\n    if match:\n        first = int(match.group("first"))\n        second_raw = match.group("second")\n        if len(second_raw) == 4:\n            second = int(second_raw)\n        else:\n            second = (first // 100) * 100 + int(second_raw)\n            if second < first:\n                second += 100\n        return max(first, second)\n    return base._year_from(raw)\n\n\ndef _literal_pdf_candidates(\n    http: Any,\n    page_url: str,\n    html: str,\n    start_year: int,\n    current_year: int,\n) -> List[Dict[str, Any]]:\n    """Recover same-host PDF paths passed literally to arbitrary JS functions."""\n    soup = BeautifulSoup(html or "", "html.parser")\n    page_host = base._host(page_url)\n    found: List[Dict[str, Any]] = []\n    seen: set[str] = set()\n    for anchor in soup.find_all(["a", "button"]):\n        onclick = str(anchor.get("onclick") or "")\n        if ".pdf" not in onclick.casefold():\n            continue\n        args = _quoted_call_args(onclick)\n        pdf_args = [x for x in args if re.search(r"\\.pdf(?:[?#].*)?$", str(x or ""), re.I)]\n        if not pdf_args:\n            continue\n        context = " ".join(_dedupe([_anchor_context(anchor), *args]))\n        if not strict.strong_report_semantics(context, pdf_args[0], page_url):\n            continue\n        year = _report_year_from_literal_context(context)\n        if not year or year < start_year or year > current_year:\n            continue\n        for raw_target in pdf_args:\n            target = urljoin(page_url, raw_target)\n            parsed = urlparse(target)\n            if parsed.scheme not in {"http", "https"} or base._host(target) != page_host:\n                continue\n            if target in seen:\n                continue\n            seen.add(target)\n            ok, final_url, ctype = _verify_pdf(http, target, page_url)\n            if not ok:\n                continue\n            lowered = context.casefold()\n            score = 90\n            if "지속가능경영보고서" in lowered or "지속가능성보고서" in lowered or "sustainability report" in lowered:\n                score += 10\n            if "통합보고" in lowered or "integrated report" in lowered:\n                score += 5\n            if any(x in lowered for x in ("국문", "korean", " kor", "_kor", "_kr")):\n                score += 3\n            found.append({\n                "year": int(year),\n                "label": args[0] if args else f"{year} sustainability report",\n                "url": final_url,\n                "source_locator": page_url,\n                "score": score,\n                "content_type": ctype,\n                "download_contract": "VERIFIED_SAME_HOST_LITERAL_PDF_ARG",\n            })\n            break\n    return found\n\n\n'''
    text = replace_once(text, marker, helpers + marker, "literal PDF helper insertion")

    old = '''    if "fileDownload" not in str(html or ""):\n        return []\n    soup = BeautifulSoup(html or "", "html.parser")\n    prefixes = _page_download_prefixes(http, page_url, html)\n    if not prefixes:\n        return []\n    found: List[Dict[str, Any]] = []\n    seen_targets: set[str] = set()\n'''
    new = '''    literal_found = _literal_pdf_candidates(http, page_url, html, start_year, current_year)\n    if "fileDownload" not in str(html or ""):\n        return literal_found\n    soup = BeautifulSoup(html or "", "html.parser")\n    prefixes = _page_download_prefixes(http, page_url, html)\n    if not prefixes:\n        return literal_found\n    found: List[Dict[str, Any]] = list(literal_found)\n    seen_targets: set[str] = {str(item.get("url") or "") for item in literal_found}\n'''
    text = replace_once(text, old, new, "scripted entry integration")
    SOURCE.write_text(text, encoding="utf-8")


def patch_test() -> None:
    text = TEST.read_text(encoding="utf-8")
    old_response = '''        if url.endswith("/files/report_2020_kor.pdf"):\n            return FakeResponse(\n                url,\n                content=b"%PDF-1.7\\ndirect-js",\n                content_type="application/pdf",\n            )\n'''
    new_response = old_response + '''        if url.endswith("/upload/annual_range.pdf"):\n            return FakeResponse(\n                url,\n                content=b"%PDF-1.7\\nliteral-arg",\n                content_type="application/pdf",\n            )\n'''
    text = replace_once(text, old_response, new_response, "literal PDF fake response")

    anchor = '''    def test_brochure_scripted_download_is_rejected(self):\n        html = ''' + "'''" + '''\n        <html><head><script src="/js/download.js"></script></head><body>\n          <li>\n            <span>2025 회사 브로슈어</span>\n            <a onclick='fileDownload("TOKEN2024")' download="Company_Brochure_2025.pdf">다운로드</a>\n          </li>\n        </body></html>\n        ''' + "'''" + '''\n        found = candidates_from_scripted_page(\n            FakeHttp(),\n            "https://official.example/media/",\n            html,\n            2020,\n            2026,\n        )\n        self.assertEqual(found, [])\n'''
    addition = anchor + '''\n    def test_multi_argument_literal_pdf_path_recovers_range_report_year(self):\n        html = ''' + "'''" + '''\n        <html><body>\n          <section class="annual-report">\n            <h3>지속가능성 보고서</h3>\n            <article>\n              <a onclick="downloadAnnual('2022/23 지속가능경영보고서_국문','/upload/annual_range.pdf','url')">국문 다운로드</a>\n            </article>\n          </section>\n        </body></html>\n        ''' + "'''" + '''\n        found = candidates_from_scripted_page(\n            FakeHttp(),\n            "https://official.example/esg/sustainability.do",\n            html,\n            2020,\n            2026,\n        )\n        self.assertEqual(len(found), 1)\n        self.assertEqual(found[0]["year"], 2023)\n        self.assertEqual(found[0]["url"], "https://official.example/upload/annual_range.pdf")\n        self.assertEqual(found[0]["download_contract"], "VERIFIED_SAME_HOST_LITERAL_PDF_ARG")\n\n    def test_literal_pdf_argument_still_requires_report_semantics(self):\n        html = ''' + "'''" + '''\n        <html><body>\n          <a onclick="downloadAsset('2024 회사 브로슈어','/upload/annual_range.pdf','url')">다운로드</a>\n        </body></html>\n        ''' + "'''" + '''\n        found = candidates_from_scripted_page(\n            FakeHttp(),\n            "https://official.example/media/",\n            html,\n            2020,\n            2026,\n        )\n        self.assertEqual(found, [])\n'''
    text = replace_once(text, anchor, addition, "literal PDF tests")
    TEST.write_text(text, encoding="utf-8")


def main() -> int:
    patch_source()
    patch_test()
    subprocess.run([sys.executable, "-m", "unittest", "tests.test_g0_scripted_report_enrichment", "-v"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-m", "py_compile", "orchestrator/g0_scripted_report_enrichment.py"], cwd=ROOT, check=True)
    print("isolated same-host literal-PDF report recovery patched and regression-tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
