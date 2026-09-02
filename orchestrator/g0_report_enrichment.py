"""Strict, company-agnostic annual sustainability-report enrichment for G0.

The base crawler deliberately gathers broadly.  This layer prevents generic PDFs such
as brochures or IR decks from satisfying annual sustainability coverage, follows only
company-linked same-organization ESG/report hosts, and performs bounded official-host
search recovery for missing report years.
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from datetime import datetime
from typing import Any, Dict, Iterable, List, Sequence, Tuple
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import zero_touch_discovery as base

POSITIVE_REPORT_TOKENS = (
    "지속가능경영보고서", "지속가능 보고서", "지속가능경영 보고서", "sustainability report",
    "integrated report", "통합보고서", "통합 보고서", "esg report", "sustainability_report",
    "sustainability-report", "sustainability_", "sustainability-",
)
NEGATIVE_REPORT_TOKENS = (
    "브로슈어", "brochure", "브로셔", "catalog", "catalogue", "카탈로그", "company profile",
    "corporate profile", "presentation", "ir presentation", "investor presentation", "factsheet",
    "fact sheet", "leaflet", "pamphlet",
)
TRUST_LINK_TOKENS = (
    "sustainability", "지속가능", "esg", "report", "보고서", "sustainability homepage",
)


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _decoded(value: str) -> str:
    try:
        return unquote(str(value or "")).casefold()
    except Exception:
        return str(value or "").casefold()


def strong_report_semantics(label: str, url: str, source_locator: str = "") -> bool:
    value = " ".join((_decoded(label), _decoded(url), _decoded(source_locator)))
    if any(token in value for token in NEGATIVE_REPORT_TOKENS):
        return False
    return any(token in value for token in POSITIVE_REPORT_TOKENS)


def _is_html_response(r: Any) -> bool:
    ctype = str(r.headers.get("content-type") or "").casefold()
    return "html" in ctype or r.text.lstrip().startswith("<")


def _crawl_document_host(http: Any, start_url: str, max_pages: int = 30) -> Tuple[List[base.Page], List[Tuple[str, str, str]]]:
    """Crawl one already-trusted document host, never expanding to sibling hosts."""
    start = str(start_url or "").strip()
    if not start:
        return [], []
    host = base._host(start)
    if not host:
        return [], []
    q: deque[Tuple[int, str]] = deque([(100, start)])
    seen: set[str] = set()
    pages: List[base.Page] = []
    links: List[Tuple[str, str, str]] = []
    while q and len(pages) < max_pages:
        best_i = max(range(len(q)), key=lambda i: q[i][0])
        _, url = q[best_i]
        del q[best_i]
        url = url.split("#")[0]
        if url in seen or base._host(url) != host:
            continue
        seen.add(url)
        r = http.get(url)
        if not r or r.status_code >= 400 or not _is_html_response(r):
            continue
        html = r.text
        text = " ".join(BeautifulSoup(html, "html.parser").stripped_strings)
        pages.append(base.Page(r.url, text, html, r.status_code))
        soup = BeautifulSoup(html, "html.parser")
        outgoing: List[Tuple[int, str]] = []
        for a in soup.find_all("a", href=True):
            label = " ".join(a.stripped_strings).strip()
            target = urljoin(r.url, a["href"]).split("#")[0]
            if urlparse(target).scheme not in {"http", "https"}:
                continue
            links.append((r.url, label, target))
            if base._host(target) != host or target in seen:
                continue
            marker = _decoded(label + " " + target)
            if re.search(r"\.(?:jpg|jpeg|png|gif|svg|css|js|zip|hwp|xlsx?|docx?|pptx?)(?:\?|$)", target, re.I):
                continue
            priority = 40 if any(x in marker for x in TRUST_LINK_TOKENS) else 1
            outgoing.append((priority, target))
        for item in sorted(outgoing, reverse=True)[:60]:
            q.append(item)
    return pages, links


def _trusted_secondary_starts(http: Any, official_root: str, pages: Sequence[base.Page], links: Sequence[Tuple[str, str, str]]) -> List[str]:
    """Accept only same-organization report/ESG hosts directly linked by official pages."""
    root_host = base._host(official_root)
    starts: List[str] = []
    source_urls = {p.url for p in pages}
    for source, label, target in links:
        target_host = base._host(target)
        if not target_host or target_host == root_host or source not in source_urls:
            continue
        marker = _decoded(label + " " + target)
        if not any(token in marker for token in TRUST_LINK_TOKENS):
            continue
        if not base._same_org_host(official_root, target):
            continue
        r = http.get(target)
        if not r or r.status_code >= 400 or not _is_html_response(r):
            continue
        text = " ".join(BeautifulSoup(r.text, "html.parser").stripped_strings).casefold()
        # A report/ESG host must itself expose sustainability/report semantics; a same-
        # domain marketing or recruiting subsite is not enough.
        if not any(token in text for token in ("sustainability", "지속가능", "esg", "report", "보고서")):
            continue
        starts.append(r.url)
    return _dedupe(starts)


def _candidate_from_link(http: Any, source: str, label: str, target: str, start_year: int, current_year: int) -> Dict[str, Any] | None:
    decoded = _decoded(label + " " + target)
    if not strong_report_semantics(label, target, source):
        return None
    year = base._year_from(decoded)
    if not year or year < start_year - 2 or year > current_year + 1:
        return None
    ok, final_url, ctype = base.verify_pdf(http, target, source)
    if not ok:
        return None
    score = 40
    if "지속가능경영보고서" in decoded or "sustainability report" in decoded:
        score += 20
    if "통합보고" in decoded or "integrated report" in decoded:
        score += 15
    if any(x in decoded for x in ("국문", "korean", "_kr", "kor")):
        score += 5
    return {
        "year": year,
        "label": label.strip() or f"{year} sustainability report",
        "url": final_url or target,
        "source_locator": source,
        "score": score,
        "content_type": ctype,
    }


def _search_host_candidates(http: Any, host: str, year: int, start_year: int, current_year: int) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for terms in (f'"{year}" "sustainability report"', f'{year} 지속가능경영보고서', f'{year} 통합보고서'):
        for url in base.search_official_domain_links(http, host, terms)[:20]:
            # Search results are locators only.  The candidate still has to be a real
            # PDF and carry strong report semantics in its official URL.
            c = _candidate_from_link(http, f"https://{host}", "", url, start_year, current_year)
            if c:
                found.append(c)
        if found:
            break
    return found


def _supporting_documents(documents: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [d for d in documents.get("documents", []) if d.get("document_type") != "SUSTAINABILITY_REPORT"]


def enrich(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    """Replace broad annual classification with strict, verified report coverage."""
    policy = discovery.get("collection_policy") or {}
    window = policy.get("requested_history_window") or {}
    start_year = int(window.get("start_year") or 2020)
    current_year = int(window.get("end_year") or datetime.now(base.KST).year)
    official_stage = ((audit.get("stages") or {}).get("official_site") or {})
    official_root = str(official_stage.get("resolved_official_root") or "").strip()
    if not official_root:
        raw = str(official_stage.get("dart_website") or "").strip()
        official_root = base._official_url(raw) if raw else ""

    http = base.Http()
    strict_existing: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for d in documents.get("documents", []) or []:
        if d.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        if strong_report_semantics(str(d.get("title") or ""), str(d.get("source_url") or ""), str(d.get("source_locator") or "")):
            strict_existing.append(d)
        else:
            rejected.append({
                "document_id": d.get("document_id"), "title": d.get("title"),
                "source_url": d.get("source_url"), "reason": "NO_STRONG_ANNUAL_REPORT_SEMANTICS_OR_NEGATIVE_DOCUMENT_TYPE",
            })

    # Re-fetch a bounded set of already-known official pages so we can discover a
    # company-linked ESG/report subdomain without widening the legal/site trust boundary.
    main_pages: List[base.Page] = []
    main_links: List[Tuple[str, str, str]] = []
    for url in _dedupe([official_root, *(official_stage.get("sample_pages") or [])])[:35]:
        if not url or (official_root and not base._same_org_host(official_root, url)):
            continue
        r = http.get(url)
        if not r or r.status_code >= 400 or not _is_html_response(r):
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        text = " ".join(soup.stripped_strings)
        main_pages.append(base.Page(r.url, text, r.text, r.status_code))
        for a in soup.find_all("a", href=True):
            main_links.append((r.url, " ".join(a.stripped_strings).strip(), urljoin(r.url, a["href"]).split("#")[0]))

    extra_candidates: List[Dict[str, Any]] = []
    for source, label, target in main_links:
        c = _candidate_from_link(http, source, label, target, start_year, current_year)
        if c:
            extra_candidates.append(c)

    secondary_starts = _trusted_secondary_starts(http, official_root, main_pages, main_links) if official_root else []
    secondary_hosts: List[str] = []
    for start in secondary_starts[:5]:
        secondary_hosts.append(base._host(start))
        pages, links = _crawl_document_host(http, start, max_pages=35)
        for source, label, target in links:
            c = _candidate_from_link(http, source, label, target, start_year, current_year)
            if c:
                extra_candidates.append(c)

    existing_years = {int(d.get("report_year")) for d in strict_existing if d.get("report_year")}
    candidate_years = {int(c["year"]) for c in extra_candidates}
    search_hosts = _dedupe([base._host(official_root), *secondary_hosts])
    for year in range(start_year, current_year + 1):
        if year in existing_years or year in candidate_years:
            continue
        for host in search_hosts:
            if not host:
                continue
            found = _search_host_candidates(http, host, year, start_year, current_year)
            extra_candidates.extend(found)
            if found:
                break

    # Pick the strongest unique PDF for each year.  Existing strict documents receive a
    # baseline score so a newly discovered alternative only replaces them when stronger.
    best: Dict[int, Tuple[int, Dict[str, Any]]] = {}
    for d in strict_existing:
        year = int(d.get("report_year") or 0)
        if year:
            best[year] = (50, d)
    for c in extra_candidates:
        year = int(c["year"])
        item = {
            "document_id": f"AUTO_SUSTAINABILITY_{year}",
            "document_type": "SUSTAINABILITY_REPORT",
            "title": c["label"],
            "report_year": year,
            "source_url": c["url"],
            "source_locator": c["source_locator"],
            "expected_extension": "pdf",
            "verification_status": "SOURCE_VERIFIED",
            "importance": "CORE",
            "notes": "Strict annual-report semantics plus official-company or directly linked same-organization ESG/report host; PDF verified by response bytes/content-type.",
        }
        if year not in best or int(c["score"]) > best[year][0]:
            best[year] = (int(c["score"]), item)

    annual = [best[y][1] for y in sorted(best)]
    found_years = set(best)
    old_gaps = list(documents.get("gaps", []) or [])
    gaps: List[Dict[str, Any]] = []
    # Preserve unrelated/non-annual gaps, then rebuild the annual series deterministically.
    for g in old_gaps:
        if g.get("document_type") != "SUSTAINABILITY_REPORT":
            gaps.append(g)
    for year in range(start_year, current_year + 1):
        if year in found_years:
            continue
        if year == current_year and found_years and max(found_years) == current_year - 1:
            gaps.append({
                "gap_id": f"AUTO_SUSTAINABILITY_{year}_NOT_LISTED",
                "source_key": "CORP_DOCS", "document_type": "SUSTAINABILITY_REPORT", "year": year,
                "verification_status": "SOURCE_VERIFIED", "status": "NOT_PUBLISHED", "severity": "LOW", "blocking": False,
                "reason": f"As of {datetime.now(base.KST).date().isoformat()}, verified official report sources list reports through {current_year - 1}, not {current_year}.",
                "source_locator": secondary_starts[0] if secondary_starts else official_root,
            })
        else:
            gaps.append({
                "gap_id": f"AUTO_SUSTAINABILITY_{year}_UNRESOLVED",
                "source_key": "CORP_DOCS", "document_type": "SUSTAINABILITY_REPORT", "year": year,
                "verification_status": "UNVERIFIED", "status": "DISCOVERY_GAP", "severity": "MEDIUM", "blocking": True,
                "reason": "No strongly classified, byte-verified annual sustainability/integrated report file was discovered from verified official report hosts.",
                "source_locator": secondary_starts[0] if secondary_starts else official_root,
            })

    documents["documents"] = [*_supporting_documents(documents), *annual]
    documents["gaps"] = gaps
    documents["discovery_status"] = "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE" if not any(g.get("blocking") for g in gaps) else "PARTIAL"
    audit.setdefault("stages", {})["strict_report_enrichment"] = {
        "rejected_broad_candidates": rejected,
        "trusted_secondary_starts": secondary_starts,
        "search_hosts": search_hosts,
        "annual_years": sorted(found_years),
        "extra_candidate_count": len(extra_candidates),
    }
    audit.setdefault("http_attempts", []).extend(http.audit)
    return documents


def refresh_document_unresolved(discovery: Dict[str, Any], documents: Dict[str, Any], audit: Dict[str, Any]) -> None:
    """Synchronize aggregate G0 gate item after document enrichment."""
    unresolved = [x for x in discovery.get("unresolved_items", []) or [] if x.get("code") != "CORPORATE_DOCUMENT_COVERAGE_INCOMPLETE"]
    blocking = [g for g in documents.get("gaps", []) or [] if g.get("blocking")]
    if blocking:
        unresolved.append({
            "code": "CORPORATE_DOCUMENT_COVERAGE_INCOMPLETE",
            "subject": discovery.get("requested_company_name"),
            "detail": f"{len(blocking)} annual report coverage gap(s) remain after strict official-source discovery.",
            "source_locator": (((audit.get("stages") or {}).get("official_site") or {}).get("resolved_official_root")),
        })
    discovery["unresolved_items"] = unresolved
    audit["gate_status"] = "PASS" if not unresolved else "REVIEW_REQUIRED"
