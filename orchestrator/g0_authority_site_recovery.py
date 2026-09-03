"""Recover a current official website from regulator/exchange filings.

This fallback is used only after the DART-declared website cannot be crawled.  For a
DART-verified listed company, the six-digit listed-company code is used to query KIND
company disclosures directly.  Recent periodic reports are then fetched from KIND and
the explicit ``홈페이지`` field in the filing is treated as an authority-anchored
candidate.  The candidate site must still be reachable and crawlable before it is used
for site/document discovery.

Search engines are deliberately not used in this adapter.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from orchestrator import g0_kind_disclosure_recovery as kind
from orchestrator import g0_official_site_recovery as official
from orchestrator import zero_touch_discovery as base


PERIODIC_WORDS = ("사업보고서", "반기보고서", "분기보고서")


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def extract_homepage_candidates(text: str) -> List[str]:
    """Extract only URLs explicitly adjacent to a homepage label in a filing body."""
    source = re.sub(r"\s+", " ", str(text or ""))
    values: List[str] = []
    patterns = (
        r"(?:홈\s*페\s*이\s*지|홈페이지)\s*[)\]】:：-]*\s*(https?://[^\s<>'\"，,;]+)",
        r"\(\s*(?:홈\s*페\s*이\s*지|홈페이지)\s*\)\s*(https?://[^\s<>'\"，,;]+)",
        r"(?:홈\s*페\s*이\s*지|홈페이지)\s*[)\]】:：-]*\s*(www\.[A-Za-z0-9.-]+(?:/[^\s<>'\"，,;]*)?)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, source, re.I):
            value = match.group(1).rstrip(".)]}>、。")
            if value.casefold().startswith("www."):
                value = "https://" + value
            values.append(value)
    return _dedupe(values)


def _periodic_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    selected = [
        dict(row) for row in rows
        if any(word in str(row.get("title") or "") for word in PERIODIC_WORDS)
    ]
    selected.sort(
        key=lambda row: (str(row.get("date") or ""), str(row.get("acceptance_no") or "")),
        reverse=True,
    )
    return selected


def _authority_candidate(
    http: Any,
    company: str,
    code: str,
    start_year: int,
    end_year: int,
    stage: Dict[str, Any],
) -> Optional[Tuple[str, Dict[str, str], List[base.Page], List[Tuple[str, str, str]]]]:
    # Current and recent filings are enough to recover a current homepage.  The wider
    # history window is intentionally not scanned here.
    lower = max(int(start_year), int(end_year) - 2)
    for year in range(int(end_year), lower - 1, -1):
        rows = kind.search_year(http, code, company, year, max_pages=4)
        periodic = _periodic_rows(rows)
        stage["years_checked"].append({"year": year, "rows": len(rows), "periodic_rows": len(periodic)})
        for row in periodic[:8]:
            body = kind.fetch_disclosure_body(http, str(row.get("acceptance_no") or ""), company)
            check: Dict[str, Any] = {"row": row, "body_resolved": bool(body), "homepage_candidates": []}
            stage["periodic_reports_checked"].append(check)
            if not body:
                continue
            candidates = extract_homepage_candidates(body.get("text") or "")
            check["body_url"] = body.get("body_url")
            check["homepage_candidates"] = candidates
            for candidate in candidates:
                parsed = urlparse(candidate)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    continue
                if base._host(candidate) in {"kind.krx.co.kr", "dart.fss.or.kr", "englishdart.fss.or.kr"}:
                    continue
                # KIND filing is the trust anchor; use the original first-party crawler
                # directly so a failed candidate cannot widen back into web search.
                pages, links = official.BASE_CRAWL(http, candidate, company, max_pages=90)
                landing_url = pages[0].url if pages else None
                check.setdefault("candidate_checks", []).append({
                    "candidate": candidate,
                    "pages_crawled": len(pages),
                    "landing_url": landing_url,
                    "landing_host_changed": bool(
                        landing_url and base._host(landing_url) != base._host(candidate)
                    ),
                })
                if pages:
                    authority = {
                        "acceptance_no": str(row.get("acceptance_no") or ""),
                        "filing_title": str(row.get("title") or ""),
                        "filing_date": str(row.get("date") or ""),
                        "filing_body_url": str(body.get("body_url") or ""),
                        "homepage_field": candidate,
                        "initial_landing_url": landing_url,
                    }
                    # Preserve the authority-declared homepage as the trust root. A
                    # geo-aware corporate site may redirect a US runner to a regional
                    # domain, while the crawl still discovers the global/Korean pages.
                    # Promoting that regional landing host would incorrectly exclude the
                    # authority-declared host from downstream report classification.
                    return candidate, authority, pages, links
    return None


def enrich(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    official_stage = (audit.get("stages") or {}).get("official_site") or {}
    if official_stage.get("resolved_official_root") or int(official_stage.get("pages_crawled") or 0) > 0:
        audit.setdefault("stages", {})["authority_site_recovery"] = {"status": "NOT_NEEDED"}
        return discovery, documents, audit

    legal = dict((((audit.get("stages") or {}).get("legal_identity") or {}).get("resolved") or {}))
    code = kind.extract_company_code(legal)
    company = str(discovery.get("current_legal_name") or discovery.get("requested_company_name") or "").strip()
    policy = discovery.get("collection_policy") or {}
    window = policy.get("requested_history_window") or {}
    start_year = int(window.get("start_year") or datetime.now().year - 5)
    end_year = int(window.get("end_year") or datetime.now().year)
    stage: Dict[str, Any] = {
        "status": "NOT_APPLICABLE",
        "company_code": code or None,
        "years_checked": [],
        "periodic_reports_checked": [],
    }
    audit.setdefault("stages", {})["authority_site_recovery"] = stage
    if not company or not code:
        stage["reason"] = "NO_VERIFIED_LISTED_COMPANY_CODE"
        return discovery, documents, audit

    http = base.Http()
    recovered = _authority_candidate(http, company, code, start_year, end_year, stage)
    audit.setdefault("http_attempts", []).extend(http.audit)
    if not recovered:
        stage["status"] = "FAILED"
        return discovery, documents, audit

    resolved_url, authority, pages, links = recovered
    stage.update({
        "status": "RECOVERED",
        "resolved_url": resolved_url,
        "authority": authority,
        "pages_crawled": len(pages),
        "links_seen": len(links),
    })
    official_stage.update({
        "resolved_official_root": resolved_url,
        "pages_crawled": len(pages),
        "links_seen": len(links),
        "sample_pages": [p.url for p in pages[:12]],
        "authority_recovery": {
            "status": "RECOVERED",
            "method": "KIND_PERIODIC_REPORT_HOMEPAGE_FIELD",
            **authority,
        },
    })

    # Rebuild site scope from the authority-recovered first-party pages.
    sites, requested_scope, site_unresolved = base.discover_site_candidates(company, pages, legal)
    discovery["domestic_site_candidates"] = sites
    discovery["requested_scope"] = requested_scope
    audit.setdefault("stages", {})["site_scope"] = {
        "sites": sites,
        "requested_scope": requested_scope,
        "unresolved": site_unresolved,
        "recovered_from": "KIND_PERIODIC_REPORT_HOMEPAGE_FIELD",
    }
    unresolved = [
        x for x in (discovery.get("unresolved_items") or [])
        if x.get("code") not in {"SITE_SCOPE_NOT_UNIQUELY_RESOLVED", "CORPORATE_DOCUMENT_COVERAGE_INCOMPLETE"}
    ]
    unresolved.extend(site_unresolved)
    discovery["unresolved_items"] = unresolved

    # Re-seed corporate documents from recovered official pages. Strict/scripted
    # enrichment later in the runner will expand and reclassify this evidence.
    docs, doc_audit = base.discover_documents(http, resolved_url, pages, links, start_year, end_year)
    docs["request_id"] = documents.get("request_id")
    documents = docs
    audit.setdefault("stages", {})["corporate_documents"] = doc_audit
    return discovery, documents, audit
