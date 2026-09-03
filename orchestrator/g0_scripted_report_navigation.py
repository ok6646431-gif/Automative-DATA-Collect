"""Recover annual reports hidden behind JavaScript navigation on trusted report hosts.

This is a second-stage fallback for corporate ESG/report libraries where the report
index is not reachable through a normal ``href`` crawl.  It never guesses company-
specific paths.  Instead it:

1. starts only from report/ESG hosts already trusted by G0;
2. extracts same-host navigation targets from HTML attributes and quoted JavaScript
   strings when the surrounding element has report semantics;
3. fetches those targets and delegates actual file recovery to the existing scripted
   download adapter, which must byte-verify the PDF;
4. fills only missing annual-report years and rebuilds gaps deterministically.
"""

from __future__ import annotations

import re
from collections import deque
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_report_enrichment as strict
from orchestrator import g0_scripted_report_enrichment as scripted
from orchestrator import zero_touch_discovery as base

NAV_SEMANTIC_TOKENS = (
    "지속가능경영보고서", "지속가능 보고서", "지속가능경영 보고서", "보고서",
    "sustainability report", "integrated report", "esg report", "report library",
    "sustainability", "integrated", "esg",
)
QUOTED_PATH_RE = re.compile(r"['\"](?P<path>/(?:[^'\"<>\\]|\\.){1,300})['\"]")
ABSOLUTE_URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.I)


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


def _semantic_blob(tag: Any) -> str:
    values: List[str] = [" ".join(getattr(tag, "stripped_strings", []) or [])]
    for key, value in getattr(tag, "attrs", {}).items():
        if isinstance(value, (list, tuple)):
            value = " ".join(str(x) for x in value)
        values.append(f"{key}={value}")
    return " ".join(values)


def extract_report_navigation_targets(page_url: str, html: str) -> List[str]:
    """Extract same-host navigation targets from report-semantic DOM controls.

    A path such as ``/dl/rep/`` is accepted only when its surrounding element carries
    report/ESG semantics.  Arbitrary JavaScript paths are ignored.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    host = base._host(page_url)
    targets: List[str] = []
    for tag in soup.find_all(True):
        blob = _semantic_blob(tag)
        low = blob.casefold()
        if not any(token in low for token in NAV_SEMANTIC_TOKENS):
            continue
        raw_values: List[str] = []
        for key, value in tag.attrs.items():
            if isinstance(value, (list, tuple)):
                raw_values.extend(str(x) for x in value)
            else:
                raw_values.append(str(value))
        for raw in raw_values:
            candidates: List[str] = []
            value = raw.strip()
            if value.startswith(("/", "http://", "https://")):
                candidates.append(value)
            candidates.extend(m.group("path") for m in QUOTED_PATH_RE.finditer(value))
            candidates.extend(ABSOLUTE_URL_RE.findall(value))
            for candidate in candidates:
                candidate = candidate.replace("\\/", "/").split("#")[0]
                target = urljoin(page_url, candidate)
                parsed = urlparse(target)
                if parsed.scheme not in {"http", "https"}:
                    continue
                if base._host(target) != host:
                    continue
                if re.search(r"\.(?:pdf|jpg|jpeg|png|gif|svg|css|js|zip|hwp|xlsx?|docx?|pptx?)(?:\?|$)", target, re.I):
                    continue
                targets.append(target)
    return _dedupe(targets)


def _trusted_starts(discovery: Dict[str, Any], audit: Dict[str, Any]) -> List[str]:
    starts = list(scripted._trusted_starts(discovery, audit))
    stage = ((audit.get("stages") or {}).get("scripted_report_enrichment") or {})
    starts.extend(stage.get("visited_pages") or [])
    return _dedupe(starts)


def recover_candidates(
    discovery: Dict[str, Any],
    audit: Dict[str, Any],
    start_year: int,
    current_year: int,
    max_pages_per_host: int = 24,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Recover scripted-report candidates via semantic JavaScript navigation."""
    http = base.Http()
    recovered: List[Dict[str, Any]] = []
    visited: List[str] = []
    desired = set(range(start_year, current_year))

    for start in _trusted_starts(discovery, audit)[:12]:
        host = base._host(start)
        if not host:
            continue
        queue: deque[str] = deque([start])
        seen: set[str] = set()
        while queue and len(seen) < max_pages_per_host:
            url = queue.popleft().split("#")[0]
            if url in seen or base._host(url) != host:
                continue
            seen.add(url)
            response = http.get(url)
            if not response or response.status_code >= 400 or not _is_html_response(response):
                continue
            visited.append(response.url)
            if "fileDownload" in response.text:
                recovered.extend(scripted.candidates_from_scripted_page(
                    http, response.url, response.text, start_year, current_year
                ))
                years = {int(x["year"]) for x in recovered}
                if desired and desired.issubset(years):
                    break
            for target in extract_report_navigation_targets(response.url, response.text):
                if target not in seen:
                    queue.append(target)
        if desired and desired.issubset({int(x["year"]) for x in recovered}):
            break

    audit.setdefault("http_attempts", []).extend(http.audit)
    return recovered, _dedupe(visited)


def enrich(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    policy = discovery.get("collection_policy") or {}
    window = policy.get("requested_history_window") or {}
    start_year = int(window.get("start_year") or 2020)
    current_year = int(window.get("end_year") or datetime.now(base.KST).year)

    recovered, visited = recover_candidates(discovery, audit, start_year, current_year)

    supporting = [
        d for d in documents.get("documents", []) or []
        if d.get("document_type") != "SUSTAINABILITY_REPORT"
    ]
    annual_by_year: Dict[int, Dict[str, Any]] = {}
    for d in documents.get("documents", []) or []:
        if d.get("document_type") != "SUSTAINABILITY_REPORT" or not d.get("report_year"):
            continue
        year = int(d["report_year"])
        if start_year <= year <= current_year:
            annual_by_year[year] = d

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
            "notes": "Recovered from report-semantic same-host JavaScript navigation; download contract and PDF bytes verified.",
        }

    found_years = set(annual_by_year)
    old_annual_gaps = {
        int(g.get("year")): g for g in documents.get("gaps", []) or []
        if g.get("document_type") == "SUSTAINABILITY_REPORT" and g.get("year")
    }
    gaps = [
        g for g in documents.get("gaps", []) or []
        if g.get("document_type") != "SUSTAINABILITY_REPORT"
    ]
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
    audit.setdefault("stages", {})["scripted_report_navigation_recovery"] = {
        "visited_pages": visited,
        "recovered_years": sorted({int(x["year"]) for x in recovered}),
        "recovered_candidate_count": len(recovered),
        "annual_years_after_merge": sorted(found_years),
    }
    return documents
