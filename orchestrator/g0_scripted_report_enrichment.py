"""Recover annual reports exposed through verified official JavaScript download controls.

Some corporate report libraries do not place the PDF in an ``href``.  Instead an
official page exposes the report year/file name and calls a small JavaScript download
function with an opaque token.  This module treats that pattern generically:

1. the page must already belong to a verified official/same-organization report host;
2. the page must expose strong annual-report semantics and a year;
3. the download function contract must be read from a same-host script;
4. the derived endpoint must return actual PDF bytes before it is promoted.

No company names, report filenames, or download tokens are hard-coded here.
"""

from __future__ import annotations

import re
from collections import deque
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_report_enrichment as strict
from orchestrator import zero_touch_discovery as base

DOWNLOAD_CALL_RE = re.compile(
    r"fileDownload\s*\(\s*(['\"])(?P<token>.+?)\1\s*\)",
    re.I,
)
DOWNLOAD_FUNCTION_RE = re.compile(
    r"function\s+fileDownload\s*\(\s*(?P<arg>[A-Za-z_$][\w$]*)\s*\)\s*\{(?P<body>.{0,2400}?)\}",
    re.I | re.S,
)
REPORT_NAV_TOKENS = (
    "sustainability", "지속가능", "esg", "report", "보고서", "integrated", "통합보고",
    "digital library", "library", "자료실",
)


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _is_html_response(response: Any) -> bool:
    if not response:
        return False
    ctype = str(response.headers.get("content-type") or "").casefold()
    if "html" in ctype:
        return True
    try:
        return response.text.lstrip().startswith("<")
    except Exception:
        return False


def extract_download_prefixes(script_text: str) -> List[str]:
    """Return relative/absolute URL prefixes used by ``fileDownload(token)``.

    Example accepted implementation::
        function fileDownload(param) {
          let url = getContextPath() + "/attach?et=" + param;
          window.location.href = url;
        }
    """
    prefixes: List[str] = []
    text = str(script_text or "")
    for fn in DOWNLOAD_FUNCTION_RE.finditer(text):
        arg = re.escape(fn.group("arg"))
        body = fn.group("body")
        # Require a literal URL component with a query parameter whose value is the
        # opaque function argument.  This deliberately ignores arbitrary JS execution.
        pattern = re.compile(
            r"(['\"])(?P<prefix>(?:https?://[^'\"]+|/[^'\"]*|[^'\"]+/[^'\"]*)\?[^'\"]*=)\1\s*\+\s*"
            + arg + r"\b",
            re.I,
        )
        for match in pattern.finditer(body):
            prefixes.append(match.group("prefix"))
    return _dedupe(prefixes)


def _page_download_prefixes(http: Any, page_url: str, html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    page_host = base._host(page_url)
    prefixes: List[str] = []
    # Inline scripts are allowed because they are part of the already verified page.
    for script in soup.find_all("script"):
        if not script.get("src"):
            prefixes.extend(extract_download_prefixes(script.string or script.get_text() or ""))
    # External script contracts must remain on the same host as the verified page.
    for script in soup.find_all("script", src=True)[:30]:
        url = urljoin(page_url, script["src"])
        if base._host(url) != page_host:
            continue
        response = http.get(url)
        if not response or response.status_code >= 400:
            continue
        prefixes.extend(extract_download_prefixes(response.text))
    return _dedupe(prefixes)


def _anchor_context(anchor: Any) -> str:
    parts: List[str] = []
    download_name = anchor.get("download")
    if download_name:
        parts.append(str(download_name))
    label = " ".join(anchor.stripped_strings).strip()
    if label:
        parts.append(label)
    # Report libraries commonly put the year/title in the surrounding LI/TR/DIV while
    # the anchor itself merely says "download".
    node = anchor
    for _ in range(4):
        node = getattr(node, "parent", None)
        if node is None:
            break
        if getattr(node, "name", None) in {"li", "tr", "article", "section", "div"}:
            context = " ".join(node.stripped_strings).strip()
            if context:
                parts.append(context[:500])
                if base._year_from(context):
                    break
    return " ".join(_dedupe(parts))


def _verify_pdf(http: Any, target: str, source: str) -> Tuple[bool, str, str]:
    """Verify actual PDF bytes, sending Referer only for the validation request.

    The stored URL remains the direct derived endpoint; the downstream downloader can
    still re-fetch it independently.  A content-type claim without PDF magic is not
    enough.
    """
    response = http.get(target, headers={"Referer": source})
    if not response or response.status_code >= 400:
        return False, target, ""
    body = bytes(response.content or b"")
    ctype = str(response.headers.get("content-type") or "")
    if not body.lstrip().startswith(b"%PDF-"):
        return False, response.url or target, ctype
    return True, response.url or target, ctype


def candidates_from_scripted_page(
    http: Any,
    page_url: str,
    html: str,
    start_year: int,
    current_year: int,
) -> List[Dict[str, Any]]:
    """Extract and byte-verify annual-report candidates from one trusted page."""
    soup = BeautifulSoup(html or "", "html.parser")
    prefixes = _page_download_prefixes(http, page_url, html)
    if not prefixes:
        return []
    found: List[Dict[str, Any]] = []
    seen_targets: set[str] = set()
    for anchor in soup.find_all("a"):
        onclick = str(anchor.get("onclick") or "")
        call = DOWNLOAD_CALL_RE.search(onclick)
        if not call:
            continue
        context = _anchor_context(anchor)
        download_name = str(anchor.get("download") or "")
        semantic_url = download_name or page_url
        if not strict.strong_report_semantics(context, semantic_url, page_url):
            continue
        year = base._year_from(" ".join((context, download_name)))
        if not year or year < start_year or year > current_year:
            continue
        token = call.group("token")
        for prefix in prefixes:
            target = urljoin(page_url, prefix + token)
            parsed = urlparse(target)
            if parsed.scheme not in {"http", "https"} or base._host(target) != base._host(page_url):
                continue
            if target in seen_targets:
                continue
            seen_targets.add(target)
            ok, final_url, ctype = _verify_pdf(http, target, page_url)
            if not ok:
                continue
            score = 90
            lowered = context.casefold()
            if "지속가능경영보고서" in lowered or "sustainability report" in lowered:
                score += 10
            if "통합보고" in lowered or "integrated report" in lowered:
                score += 5
            if any(x in lowered for x in ("국문", "korean", " kor", "_kor", "_kr")):
                score += 3
            found.append({
                "year": int(year),
                "label": download_name or context[:180] or f"{year} sustainability report",
                "url": final_url,
                "source_locator": page_url,
                "score": score,
                "content_type": ctype,
                "download_contract": "VERIFIED_SAME_HOST_SCRIPT_TOKEN",
            })
            break
    return found


def _trusted_starts(discovery: Dict[str, Any], audit: Dict[str, Any]) -> List[str]:
    stage = ((audit.get("stages") or {}).get("strict_report_enrichment") or {})
    starts = list(stage.get("trusted_secondary_starts") or [])
    official = ((audit.get("stages") or {}).get("official_site") or {})
    root = str(official.get("resolved_official_root") or official.get("dart_website") or "").strip()
    if root:
        starts.append(base._official_url(root))
    return _dedupe(starts)


def _crawl_for_scripted_candidates(
    http: Any,
    start: str,
    start_year: int,
    current_year: int,
    max_pages: int = 28,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    host = base._host(start)
    if not host:
        return [], []
    queue: deque[Tuple[int, str]] = deque([(100, start)])
    seen: set[str] = set()
    candidates: List[Dict[str, Any]] = []
    pages: List[str] = []
    while queue and len(seen) < max_pages:
        best_i = max(range(len(queue)), key=lambda i: queue[i][0])
        _, url = queue[best_i]
        del queue[best_i]
        url = url.split("#")[0]
        if url in seen or base._host(url) != host:
            continue
        seen.add(url)
        response = http.get(url)
        if not response or response.status_code >= 400 or not _is_html_response(response):
            continue
        pages.append(response.url)
        candidates.extend(candidates_from_scripted_page(
            http, response.url, response.text, start_year, current_year
        ))
        soup = BeautifulSoup(response.text, "html.parser")
        outgoing: List[Tuple[int, str]] = []
        for anchor in soup.find_all("a", href=True):
            target = urljoin(response.url, anchor["href"]).split("#")[0]
            if base._host(target) != host or target in seen:
                continue
            if re.search(r"\.(?:pdf|jpg|jpeg|png|gif|svg|css|js|zip|hwp|xlsx?|docx?|pptx?)(?:\?|$)", target, re.I):
                continue
            marker = (" ".join(anchor.stripped_strings) + " " + target).casefold()
            priority = 60 if any(token in marker for token in REPORT_NAV_TOKENS) else 1
            outgoing.append((priority, target))
        for item in sorted(outgoing, reverse=True)[:50]:
            queue.append(item)
    return candidates, pages


def enrich(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    policy = discovery.get("collection_policy") or {}
    window = policy.get("requested_history_window") or {}
    start_year = int(window.get("start_year") or 2020)
    current_year = int(window.get("end_year") or datetime.now(base.KST).year)

    http = base.Http()
    recovered: List[Dict[str, Any]] = []
    visited_pages: List[str] = []
    for start in _trusted_starts(discovery, audit)[:6]:
        candidates, pages = _crawl_for_scripted_candidates(
            http, start, start_year, current_year
        )
        recovered.extend(candidates)
        visited_pages.extend(pages)

    supporting = [
        d for d in documents.get("documents", []) or []
        if d.get("document_type") != "SUSTAINABILITY_REPORT"
    ]
    annual_by_year: Dict[int, Dict[str, Any]] = {}
    for d in documents.get("documents", []) or []:
        if d.get("document_type") != "SUSTAINABILITY_REPORT" or not d.get("report_year"):
            continue
        annual_by_year[int(d["report_year"])] = d
    for candidate in sorted(recovered, key=lambda x: int(x.get("score") or 0), reverse=True):
        year = int(candidate["year"])
        if year in annual_by_year:
            continue
        annual_by_year[year] = {
            "document_id": f"AUTO_SUSTAINABILITY_{year}",
            "document_type": "SUSTAINABILITY_REPORT",
            "title": candidate["label"],
            "report_year": year,
            "source_url": candidate["url"],
            "source_locator": candidate["source_locator"],
            "expected_extension": "pdf",
            "verification_status": "SOURCE_VERIFIED",
            "importance": "CORE",
            "notes": "Official report-page year/file semantics + same-host JavaScript download contract + PDF byte verification.",
        }

    found_years = set(annual_by_year)
    gaps: List[Dict[str, Any]] = [
        g for g in documents.get("gaps", []) or []
        if g.get("document_type") != "SUSTAINABILITY_REPORT"
    ]
    old_annual_gaps = {
        int(g.get("year")): g for g in documents.get("gaps", []) or []
        if g.get("document_type") == "SUSTAINABILITY_REPORT" and g.get("year")
    }
    source_locator = next(iter(_trusted_starts(discovery, audit)), "")
    for year in range(start_year, current_year + 1):
        if year in found_years:
            continue
        if year == current_year and found_years and max(found_years) == current_year - 1:
            gaps.append({
                "gap_id": f"AUTO_SUSTAINABILITY_{year}_NOT_LISTED",
                "source_key": "CORP_DOCS",
                "document_type": "SUSTAINABILITY_REPORT",
                "year": year,
                "verification_status": "SOURCE_VERIFIED",
                "status": "NOT_PUBLISHED",
                "severity": "LOW",
                "blocking": False,
                "reason": f"As of {datetime.now(base.KST).date().isoformat()}, verified official report sources list reports through {current_year - 1}, not {current_year}.",
                "source_locator": source_locator,
            })
        else:
            gaps.append(old_annual_gaps.get(year) or {
                "gap_id": f"AUTO_SUSTAINABILITY_{year}_UNRESOLVED",
                "source_key": "CORP_DOCS",
                "document_type": "SUSTAINABILITY_REPORT",
                "year": year,
                "verification_status": "UNVERIFIED",
                "status": "DISCOVERY_GAP",
                "severity": "MEDIUM",
                "blocking": True,
                "reason": "No byte-verified annual sustainability/integrated report was recovered from verified official report sources.",
                "source_locator": source_locator,
            })

    documents["documents"] = [*supporting, *[annual_by_year[y] for y in sorted(annual_by_year)]]
    documents["gaps"] = gaps
    documents["discovery_status"] = (
        "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE"
        if not any(g.get("blocking") for g in gaps)
        else "PARTIAL"
    )
    audit.setdefault("stages", {})["scripted_report_enrichment"] = {
        "trusted_starts": _trusted_starts(discovery, audit),
        "visited_pages": _dedupe(visited_pages),
        "recovered_years": sorted({int(x["year"]) for x in recovered}),
        "recovered_candidate_count": len(recovered),
    }
    audit.setdefault("http_attempts", []).extend(http.audit)
    return documents
