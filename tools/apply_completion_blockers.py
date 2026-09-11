"""One-shot generic report-discovery performance patch.

Large corporate sites can expose the same multi-megabyte JavaScript bundle on every
page.  The report recovery stages previously re-fetched those bundles while broad
navigation ran before the more general bounded parsers, so the process-wide network
budget could expire before the parser capable of understanding the actual download
control got a turn.

This patch is company-agnostic:
* run bounded generic/data-attribute/plain-href recovery before broad scripted crawl;
* keep the later generic pass so newly discovered navigation pages can still be read;
* cache same-host external script text per Http instance; and
* add regression tests proving the cache prevents repeated script downloads.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "orchestrator/zero_touch_runner.py"
SCRIPTED = ROOT / "orchestrator/g0_scripted_report_enrichment.py"
GENERIC = ROOT / "orchestrator/g0_generic_js_report_recovery.py"
TEST = ROOT / "tests/test_g0_scripted_report_enrichment.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one patch target, found {count}")
    return text.replace(old, new, 1)


def patch_runner() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    old = '''    documents = g0_report_enrichment.enrich(discovery, documents, audit)\n    documents = g0_scripted_report_enrichment.enrich(discovery, documents, audit)\n    documents = g0_scripted_report_navigation.enrich(discovery, documents, audit)\n    documents = g0_generic_js_report_recovery.enrich(discovery, documents, audit)\n    documents = g0_data_attr_report_recovery.enrich(discovery, documents, audit)\n    documents = g0_plain_href_report_recovery.enrich(discovery, documents, audit)\n'''
    new = '''    documents = g0_report_enrichment.enrich(discovery, documents, audit)\n\n    # Bounded parsers get first use of the live-network budget.  They inspect already\n    # verified report-index pages and can resolve arbitrary static JS/data-attribute\n    # controls without crawling the wider corporate site.  Broad navigation remains a\n    # fallback, followed by a second generic pass for any new report pages it reveals.\n    documents = g0_generic_js_report_recovery.enrich(discovery, documents, audit)\n    documents = g0_data_attr_report_recovery.enrich(discovery, documents, audit)\n    documents = g0_plain_href_report_recovery.enrich(discovery, documents, audit)\n    documents = g0_scripted_report_enrichment.enrich(discovery, documents, audit)\n    documents = g0_scripted_report_navigation.enrich(discovery, documents, audit)\n    documents = g0_generic_js_report_recovery.enrich(discovery, documents, audit)\n'''
    RUNNER.write_text(replace_once(text, old, new, "report-stage priority"), encoding="utf-8")


def patch_scripted_cache() -> None:
    text = SCRIPTED.read_text(encoding="utf-8")
    old = '''    for script in soup.find_all("script", src=True)[:30]:\n        url = urljoin(page_url, script["src"])\n        if base._host(url) != page_host:\n            continue\n        response = http.get(url)\n        if not response or response.status_code >= 400:\n            continue\n        prefixes.extend(extract_download_prefixes(response.text))\n        if prefixes:\n            break\n'''
    new = '''    cache = getattr(http, "_g0_same_host_script_text_cache", None)\n    if cache is None:\n        cache = {}\n        setattr(http, "_g0_same_host_script_text_cache", cache)\n    for script in soup.find_all("script", src=True)[:30]:\n        url = urljoin(page_url, script["src"])\n        if base._host(url) != page_host:\n            continue\n        if url in cache:\n            script_text = cache[url]\n        else:\n            response = http.get(url)\n            if not response or response.status_code >= 400:\n                continue\n            script_text = response.text\n            cache[url] = script_text\n        prefixes.extend(extract_download_prefixes(script_text))\n        if prefixes:\n            break\n'''
    SCRIPTED.write_text(replace_once(text, old, new, "scripted external-script cache"), encoding="utf-8")


def patch_generic_cache() -> None:
    text = GENERIC.read_text(encoding="utf-8")
    old = '''    for script in soup.find_all("script", src=True)[:50]:\n        url = urljoin(page_url, str(script.get("src") or ""))\n        if base._host(url) != host:\n            continue\n        response = http.get(url)\n        if not response or response.status_code >= 400:\n            continue\n        out.append((response.url or url, response.text))\n    return out\n'''
    new = '''    cache = getattr(http, "_g0_same_host_script_text_cache", None)\n    if cache is None:\n        cache = {}\n        setattr(http, "_g0_same_host_script_text_cache", cache)\n    for script in soup.find_all("script", src=True)[:50]:\n        url = urljoin(page_url, str(script.get("src") or ""))\n        if base._host(url) != host:\n            continue\n        if url in cache:\n            script_text = cache[url]\n            final_url = url\n        else:\n            response = http.get(url)\n            if not response or response.status_code >= 400:\n                continue\n            script_text = response.text\n            final_url = response.url or url\n            cache[url] = script_text\n        out.append((final_url, script_text))\n    return out\n'''
    GENERIC.write_text(replace_once(text, old, new, "generic external-script cache"), encoding="utf-8")


def patch_tests() -> None:
    text = TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''from orchestrator.g0_generic_js_report_recovery import (\n    candidates_from_generic_js_page,\n''',
        '''from orchestrator.g0_generic_js_report_recovery import (\n    _script_texts,\n    candidates_from_generic_js_page,\n''',
        "generic cache test import",
    )
    text = replace_once(
        text,
        '''from orchestrator.g0_scripted_report_enrichment import (\n    candidates_from_scripted_page,\n''',
        '''from orchestrator.g0_scripted_report_enrichment import (\n    _page_download_prefixes,\n    candidates_from_scripted_page,\n''',
        "scripted cache test import",
    )
    text = replace_once(
        text,
        '''class FakeHttp:\n    def __init__(self):\n        self.audit = []\n\n    def get(self, url, **kwargs):\n''',
        '''class FakeHttp:\n    def __init__(self):\n        self.audit = []\n        self.get_calls = []\n\n    def get(self, url, **kwargs):\n        self.get_calls.append(url)\n''',
        "fake http call counter",
    )
    anchor = '''    def test_extract_download_prefixes_from_same_function_contract(self):\n        script = 'function fileDownload(param) { let url = getContextPath() + "/attach?et=" + param; window.location.href = url; }'\n        self.assertEqual(extract_download_prefixes(script), ["/attach?et="])\n'''
    addition = anchor + '''\n    def test_same_external_script_is_fetched_once_per_http_instance(self):\n        http = FakeHttp()\n        scripted_html = '<script src="/js/download.js"></script><a onclick="fileDownload(\\\"x\\\")">x</a>'\n        _page_download_prefixes(http, "https://official.example/esg/report.do", scripted_html)\n        _page_download_prefixes(http, "https://official.example/esg/other.do", scripted_html)\n        self.assertEqual(\n            http.get_calls.count("https://official.example/js/download.js"),\n            1,\n        )\n\n        generic_http = FakeHttp()\n        generic_html = '<script src="/js/generic-download.js"></script>'\n        _script_texts(generic_http, "https://official.example/esg/report.do", generic_html)\n        _script_texts(generic_http, "https://official.example/esg/other.do", generic_html)\n        self.assertEqual(\n            generic_http.get_calls.count("https://official.example/js/generic-download.js"),\n            1,\n        )\n'''
    TEST.write_text(replace_once(text, anchor, addition, "shared script cache regression test"), encoding="utf-8")


def main() -> int:
    patch_runner()
    patch_scripted_cache()
    patch_generic_cache()
    patch_tests()
    subprocess.run(
        [sys.executable, "-m", "unittest", "tests.test_g0_scripted_report_enrichment", "-v"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            "orchestrator/zero_touch_runner.py",
            "orchestrator/g0_scripted_report_enrichment.py",
            "orchestrator/g0_generic_js_report_recovery.py",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            "git", "add",
            "orchestrator/zero_touch_runner.py",
            "orchestrator/g0_scripted_report_enrichment.py",
            "orchestrator/g0_generic_js_report_recovery.py",
            "tests/test_g0_scripted_report_enrichment.py",
        ],
        cwd=ROOT,
        check=True,
    )
    print("generic report-stage priority and shared-script cache patched and regression-tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
