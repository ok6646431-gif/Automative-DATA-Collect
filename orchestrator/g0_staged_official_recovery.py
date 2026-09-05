"""Stage official-site recovery so first-party evidence wins before search fallback.

The legacy base crawler mixes two concerns: crawling an already-known first-party URL
and using public search engines to seed additional URLs. Calling that crawler while
probing every recovery candidate therefore repeats search traffic inside each stage.
This module separates those concerns.

Trust order:
1. crawl the DART-declared URL and same-host variants without search;
2. inspect first-party bootstrap resources (redirects, frames, scripts, robots/sitemaps);
3. use search only to locate URLs under the DART-anchored organization domain;
4. use general search only as a final replacement-host locator.

Candidate validation is also bounded independently from the full G0 crawl budget.
"""

from __future__ import annotations

from collections import deque
import re
from typing import Any, Dict, Sequence, Tuple, List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_official_site_recovery as recovery
from orchestrator import g0_thin_shell_recovery as thin
from orchestrator import zero_touch_discovery as base


MAX_CANDIDATE_PROBE_PAGES = 18
MAX_CANDIDATES_PER_STAGE = 12


def _crawl_no_search(
    http: base.Http,
    start_url: str,
    max_pages: int,
) -> Tuple[List[base.Page], List[Tuple[str, str, str]]]:
    """Crawl an already-trusted URL boundary without invoking any search engine."""
    first = http.get(start_url)
    if not first or first.status_code >= 400:
        return [], []
    root = first.url
    allowed_hosts = {base._host(start_url), base._host(root)} - {""}
    q: deque[Tuple[int, str]] = deque([(100, root)])
    seen: set[str] = set()
    pages: List[base.Page] = []
    linked: List[Tuple[str, str, str]] = []

    while q and len(pages) < max(1, int(max_pages or 1)):
        best_i = max(range(len(q)), key=lambda i: q[i][0])
        _, url = q[best_i]
        del q[best_i]
        url = url.split("#", 1)[0]
        if url in seen or base._host(url) not in allowed_hosts:
            continue
        seen.add(url)
        response = first if url == root and not pages else http.get(url)
        if not response or response.status_code >= 400:
            continue
        ctype = str(response.headers.get("content-type") or "").casefold()
        if "html" not in ctype and not str(response.text or "").lstrip().startswith("<"):
            continue

        html = str(response.text or "")
        text = base._soup_text(html)
        pages.append(base.Page(response.url, text, html, response.status_code))
        soup = BeautifulSoup(html, "html.parser")
        outgoing: List[Tuple[int, str]] = []
        for anchor in soup.find_all("a", href=True):
            label = " ".join(anchor.stripped_strings).strip()
            target = urljoin(response.url, anchor["href"]).split("#", 1)[0]
            if urlparse(target).scheme not in {"http", "https"}:
                continue
            linked.append((response.url, label, target))
            if base._host(target) not in allowed_hosts or target in seen:
                continue
            if re.search(
                r"\.(?:jpg|jpeg|png|gif|svg|css|js|zip|hwp|xlsx?|docx?|pptx?)(?:\?|$)",
                target,
                re.I,
            ):
                continue
            outgoing.append((base._priority(label, target), target))
        for item in sorted(outgoing, reverse=True)[:80]:
            q.append(item)
    return pages, linked


def _initial_dart_surface(
    http: base.Http,
    start_url: str,
    max_pages: int,
):
    """Preserve DART-host/path recovery without triggering search fallback."""
    recovery.last_recovery = {
        "status": "NOT_NEEDED",
        "dart_start_url": start_url,
        "resolved_url": None,
        "method": None,
        "candidate_checks": [],
    }
    pages, links = _crawl_no_search(http, start_url, max_pages=max_pages)
    if pages:
        recovery.last_recovery["resolved_url"] = pages[0].url
        return pages, links

    parsed_start = urlparse(start_url if "://" in start_url else "https://" + start_url)
    for variant in recovery._origin_variants(start_url):
        if variant == start_url:
            continue
        pages, links = _crawl_no_search(http, variant, max_pages=max_pages)
        if not pages:
            continue
        method = (
            "DART_HOST_PATH_ANCESTOR"
            if urlparse(variant).path != parsed_start.path
            else "DART_HOST_VARIANT"
        )
        recovery.last_recovery.update({
            "status": "RECOVERED",
            "resolved_url": pages[0].url,
            "method": method,
        })
        return pages, links
    recovery.last_recovery["status"] = "DART_SURFACE_UNREACHABLE"
    return [], []


def _try_candidates(
    http: base.Http,
    start_url: str,
    company: str,
    candidates: Sequence[str],
    original_evidence: Dict[str, Any],
    stage: str,
    max_pages: int,
):
    start_host = thin._host(start_url)
    probe_pages = max(1, min(int(max_pages or 1), MAX_CANDIDATE_PROBE_PAGES))
    for candidate in list(candidates)[:MAX_CANDIDATES_PER_STAGE]:
        if not thin._safe_http_url(candidate) or recovery._blocked(candidate):
            continue
        candidate_pages, candidate_links = _crawl_no_search(
            http, candidate, max_pages=probe_pages
        )
        evidence = thin.navigation_evidence(candidate_pages, candidate_links)
        candidate_host = thin._host(candidate)
        exact_dart_host = bool(start_host and candidate_host == start_host)
        same_org = base._same_org_host(start_url, candidate)

        verified = False
        method = ""
        if exact_dart_host and candidate_pages and thin._is_better(evidence, original_evidence):
            verified = True
            method = f"DART_HOST_{stage}"
        elif same_org and candidate_pages:
            self_identifies, self_evidence = recovery._corporate_self_identifies(
                company, candidate_pages, candidate_links
            )
            evidence = {**evidence, **self_evidence}
            verified = bool(self_identifies)
            method = f"SAME_ORG_{stage}_REVERIFIED"
        elif candidate_pages:
            self_identifies, self_evidence = recovery._corporate_self_identifies(
                company, candidate_pages, candidate_links
            )
            evidence = {**evidence, **self_evidence}
            verified = bool(self_identifies)
            method = f"REPLACEMENT_{stage}_REVERIFIED"

        recovery.last_recovery.setdefault("candidate_checks", []).append({
            "candidate": candidate,
            "stage": stage,
            "verified": verified,
            "verification_method": method,
            "probe_page_budget": probe_pages,
            **evidence,
        })
        if not verified:
            continue

        recovery.last_recovery.update({
            "status": "RECOVERED",
            "resolved_url": candidate_pages[0].url,
            "method": method,
            "thin_surface": original_evidence,
            "successful_stage": stage,
            "candidate_probe_page_budget": probe_pages,
        })
        return candidate_pages, candidate_links
    return None


def crawl_official(http: base.Http, start_url: str, company: str, max_pages: int = 90):
    original_pages, original_links = _initial_dart_surface(
        http, start_url, max_pages=max_pages
    )
    original_evidence = thin.navigation_evidence(original_pages, original_links)
    if original_evidence["usable"]:
        return original_pages, original_links

    recovery.last_recovery.setdefault("candidate_checks", [])
    recovery.last_recovery["thin_surface"] = original_evidence
    recovery.last_recovery["status"] = (
        "THIN_SURFACE_DETECTED" if original_pages else "DART_SURFACE_UNREACHABLE"
    )
    recovery.last_recovery["stages_attempted"] = []

    first_party = thin._first_party_bootstrap_candidates(http, start_url, original_pages)
    recovery.last_recovery["stages_attempted"].append({
        "stage": "FIRST_PARTY_BOOTSTRAP",
        "candidate_count": len(first_party),
        "sample_candidates": first_party[:10],
    })
    resolved = _try_candidates(
        http, start_url, company, first_party, original_evidence,
        "FIRST_PARTY_BOOTSTRAP", max_pages,
    )
    if resolved:
        return resolved

    anchored_search = thin._anchored_domain_candidates(http, start_url, company)
    recovery.last_recovery["stages_attempted"].append({
        "stage": "ANCHORED_SEARCH",
        "candidate_count": len(anchored_search),
        "sample_candidates": anchored_search[:10],
    })
    resolved = _try_candidates(
        http, start_url, company, anchored_search, original_evidence,
        "ANCHORED_SEARCH", max_pages,
    )
    if resolved:
        return resolved

    replacement = recovery._locate_candidates(http, company)
    recovery.last_recovery["stages_attempted"].append({
        "stage": "REPLACEMENT_SEARCH",
        "candidate_count": len(replacement),
        "sample_candidates": replacement[:10],
    })
    resolved = _try_candidates(
        http, start_url, company, replacement, original_evidence,
        "REPLACEMENT_SEARCH", max_pages,
    )
    if resolved:
        return resolved

    if original_pages:
        recovery.last_recovery.update({
            "status": "THIN_SURFACE_UNRESOLVED",
            "resolved_url": original_pages[0].url,
            "method": None,
            "thin_surface": original_evidence,
        })
        return original_pages, original_links
    recovery.last_recovery["status"] = "FAILED"
    return [], []
