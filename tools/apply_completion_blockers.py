"""One-shot generic literal-PDF JavaScript report-control patch.

Some official corporate report libraries expose a verified PDF path directly as one
argument of a multi-argument JavaScript call, for example
``downloadReport('2022/23 sustainability report', '/upload/report.pdf', 'url')``.
The existing scripted parser only handled a one-token ``fileDownload(token)`` contract.

This patch is company-agnostic and fail-closed:
* any JS function name is allowed, but one quoted argument must be a same-host PDF path;
* annual-report semantics must be present in the local control/context;
* year ranges such as 2022/23 or 2021_22 resolve to the later report year;
* the target must pass streamed PDF magic-byte verification; and
* existing token-based behavior remains unchanged.
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

    helper_anchor = '''def _dedupe(values: Iterable[str]) -> List[str]:\n    out: List[str] = []\n    for value in values:\n        value = str(value or "").strip()\n        if value and value not in out:\n            out.append(value)\n    return out\n\n\n'''
    helpers = helper_anchor + '''def _quoted_call_args(raw: str) -> List[str]:\n    """Return literal quoted arguments from a JavaScript control in source order."""\n    return [\n        match.group("value")\n        for match in re.finditer(\n            r"(?P<quote>['\\\"])(?P<value>(?:\\\\.|(?! (?P=quote)).)*?)(?P=quote)",\n            str(raw or ""),\n            re.X | re.S,\n        )\n    ]\n\n\ndef _report_year_from_context(text: str) -> int | None:\n    """Prefer the later year in annual labels such as 2022/23 or 2021_22."""\n    raw = str(text or "")\n    match = re.search(\n        r"(?<!\\d)(?P<first>(?:19|20)\\d{2})\\s*[_/／-]\\s*(?P<second>(?:19|20)\\d{2}|\\d{2})(?!\\d)",\n        raw,\n    )\n    if match:\n        first = int(match.group("first"))\n        second_raw = match.group("second")\n        if len(second_raw) == 4:\n            second = int(second_raw)\n        else:\n            second = (first // 100) * 100 + int(second_raw)\n            if second < first:\n                second += 100\n        return max(first, second)\n    return base._year_from(raw)\n\n\ndef _literal_pdf_targets(onclick: str, page_url: str) -> List[str]:\n    """Recover direct same-host PDF arguments without trusting the function name."""\n    page_host = base._host(page_url)\n    targets: List[str] = []\n    for value in _quoted_call_args(onclick):\n        candidate = str(value or "").strip()\n        if not re.search(r"\\.pdf(?:[?#].*)?$", candidate, re.I):\n            continue\n        target = urljoin(page_url, candidate)\n        parsed = urlparse(target)\n        if parsed.scheme not in {"http", "https"} or base._host(target) != page_host:\n            continue\n        if target not in targets:\n            targets.append(target)\n    return targets\n\n\n'''
    text = replace_once(text, helper_anchor, helpers, "literal PDF helpers")

    old = '''    soup = BeautifulSoup(html or "", "html.parser")\n    prefixes = _page_download_prefixes(http, page_url, html)\n    if not prefixes:\n        return []\n    found: List[Dict[str, Any]] = []\n    seen_targets: set[str] = set()\n    for anchor in soup.find_all("a"):\n        onclick = str(anchor.get("onclick") or "")\n        call = DOWNLOAD_CALL_RE.search(onclick)\n        if not call:\n            continue\n        context = _anchor_context(anchor)\n        download_name = str(anchor.get("download") or "")\n        if not strict.strong_report_semantics(context, download_name or page_url, page_url):\n            continue\n        year = base._year_from(" ".join((context, download_name)))\n        if not year or year < start_year or year > current_year:\n            continue\n        token = call.group("token")\n        for prefix in prefixes:\n            target = urljoin(page_url, prefix + token)\n            parsed = urlparse(target)\n            if parsed.scheme not in {"http", "https"} or base._host(target) != base._host(page_url):\n                continue\n            if target in seen_targets:\n                continue\n            seen_targets.add(target)\n            ok, final_url, ctype = _verify_pdf(http, target, page_url)\n            if not ok:\n                continue\n            score = 90\n            lowered = context.casefold()\n            if "지속가능경영보고서" in lowered or "sustainability report" in lowered:\n                score += 10\n            if "통합보고" in lowered or "integrated report" in lowered:\n                score += 5\n            if any(x in lowered for x in ("국문", "korean", " kor", "_kor", "_kr")):\n                score += 3\n            found.append({\n                "year": int(year),\n                "label": download_name or context[:180] or f"{year} sustainability report",\n                "url": final_url,\n                "source_locator": page_url,\n                "score": score,\n                "content_type": ctype,\n                "download_contract": "VERIFIED_SAME_HOST_SCRIPT_TOKEN",\n            })\n            break\n    return found\n'''
    new = '''    soup = BeautifulSoup(html or "", "html.parser")\n    prefixes = _page_download_prefixes(http, page_url, html)\n    found: List[Dict[str, Any]] = []\n    seen_targets: set[str] = set()\n    for anchor in soup.find_all(["a", "button"]):\n        onclick = str(anchor.get("onclick") or "")\n        if not onclick:\n            continue\n        literal_args = _quoted_call_args(onclick)\n        context = " ".join(_dedupe([_anchor_context(anchor), *literal_args]))\n        download_name = str(anchor.get("download") or "")\n        if not strict.strong_report_semantics(context, download_name or page_url, page_url):\n            continue\n        year = _report_year_from_context(" ".join((context, download_name)))\n        if not year or year < start_year or year > current_year:\n            continue\n\n        direct_targets = _literal_pdf_targets(onclick, page_url)\n        contract = "VERIFIED_SAME_HOST_LITERAL_PDF_ARG"\n        targets = list(direct_targets)\n        if not targets:\n            call = DOWNLOAD_CALL_RE.search(onclick)\n            if not call or not prefixes:\n                continue\n            token = call.group("token")\n            targets = [urljoin(page_url, prefix + token) for prefix in prefixes]\n            contract = "VERIFIED_SAME_HOST_SCRIPT_TOKEN"\n\n        for target in targets:\n            parsed = urlparse(target)\n            if parsed.scheme not in {"http", "https"} or base._host(target) != base._host(page_url):\n                continue\n            if target in seen_targets:\n                continue\n            seen_targets.add(target)\n            ok, final_url, ctype = _verify_pdf(http, target, page_url)\n            if not ok:\n                continue\n            score = 90\n            lowered = context.casefold()\n            if "지속가능경영보고서" in lowered or "sustainability report" in lowered:\n                score += 10\n            if "통합보고" in lowered or "integrated report" in lowered:\n                score += 5\n            if any(x in lowered for x in ("국문", "korean", " kor", "_kor", "_kr")):\n                score += 3\n            found.append({\n                "year": int(year),\n                "label": download_name or (literal_args[0] if literal_args else "") or context[:180] or f"{year} sustainability report",\n                "url": final_url,\n                "source_locator": page_url,\n                "score": score,\n                "content_type": ctype,\n                "download_contract": contract,\n            })\n            break\n    return found\n'''
    text = replace_once(text, old, new, "scripted candidate extraction")
    SOURCE.write_text(text, encoding="utf-8")


def patch_test() -> None:
    text = TEST.read_text(encoding="utf-8")
    old_response = '''        if url.endswith("/files/report_2020_kor.pdf"):\n            return FakeResponse(\n                url,\n                content=b"%PDF-1.7\\ndirect-js",\n                content_type="application/pdf",\n            )\n'''
    new_response = old_response + '''        if url.endswith("/upload/annual_range.pdf"):\n            return FakeResponse(\n                url,\n                content=b"%PDF-1.7\\nliteral-arg",\n                content_type="application/pdf",\n            )\n'''
    text = replace_once(text, old_response, new_response, "literal PDF fake response")

    anchor = '''    def test_brochure_scripted_download_is_rejected(self):\n        html = ''' + "'''" + '''\n        <html><head><script src="/js/download.js"></script></head><body>\n          <li>\n            <span>2025 회사 브로슈어</span>\n            <a onclick='fileDownload("TOKEN2024")' download="Company_Brochure_2025.pdf">다운로드</a>\n          </li>\n        </body></html>\n        ''' + "'''" + '''\n        found = candidates_from_scripted_page(\n            FakeHttp(),\n            "https://official.example/media/",\n            html,\n            2020,\n            2026,\n        )\n        self.assertEqual(found, [])\n'''
    addition = anchor + '''\n    def test_multi_argument_literal_pdf_path_recovers_range_report_year(self):\n        html = ''' + "'''" + '''\n        <html><body>\n          <section class="annual-report">\n            <h3>지속가능성 보고서</h3>\n            <article>\n              <a onclick="downloadAnnual('2022/23 지속가능경영보고서_국문','/upload/annual_range.pdf','url')">\n                국문 다운로드\n              </a>\n            </article>\n          </section>\n        </body></html>\n        ''' + "'''" + '''\n        found = candidates_from_scripted_page(\n            FakeHttp(),\n            "https://official.example/esg/sustainability.do",\n            html,\n            2020,\n            2026,\n        )\n        self.assertEqual(len(found), 1)\n        self.assertEqual(found[0]["year"], 2023)\n        self.assertEqual(found[0]["url"], "https://official.example/upload/annual_range.pdf")\n        self.assertEqual(found[0]["download_contract"], "VERIFIED_SAME_HOST_LITERAL_PDF_ARG")\n\n    def test_literal_pdf_argument_still_requires_report_semantics(self):\n        html = ''' + "'''" + '''\n        <html><body>\n          <a onclick="downloadAsset('2024 회사 브로슈어','/upload/annual_range.pdf','url')">다운로드</a>\n        </body></html>\n        ''' + "'''" + '''\n        found = candidates_from_scripted_page(\n            FakeHttp(),\n            "https://official.example/media/",\n            html,\n            2020,\n            2026,\n        )\n        self.assertEqual(found, [])\n'''
    text = replace_once(text, anchor, addition, "literal PDF report tests")
    TEST.write_text(text, encoding="utf-8")


def main() -> int:
    patch_source()
    patch_test()
    subprocess.run(
        [sys.executable, "-m", "unittest", "tests.test_g0_scripted_report_enrichment", "-v"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "py_compile", "orchestrator/g0_scripted_report_enrichment.py"],
        cwd=ROOT,
        check=True,
    )
    print("generic multi-argument literal-PDF report controls patched and regression-tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
