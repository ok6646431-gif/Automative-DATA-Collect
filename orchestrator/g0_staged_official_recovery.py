"""Stage official-site recovery so first-party evidence wins before search fallback.

The thin-shell adapter can discover candidates from first-party bootstrap resources,
DART-domain search, and replacement-host search. This wrapper evaluates those sources
in trust order instead of eagerly querying every fallback before testing a strong
first-party candidate.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from orchestrator import g0_official_site_recovery as recovery
from orchestrator import g0_thin_shell_recovery as thin
from orchestrator import zero_touch_discovery as base


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
    for candidate in list(candidates)[:40]:
        if not thin._safe_http_url(candidate) or recovery._blocked(candidate):
            continue
        candidate_pages, candidate_links = recovery.BASE_CRAWL(
            http, candidate, company, max_pages=max_pages
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
        })
        return candidate_pages, candidate_links
    return None


def crawl_official(http: base.Http, start_url: str, company: str, max_pages: int = 90):
    pages, links = recovery.crawl_official(http, start_url, company, max_pages=max_pages)
    original_pages, original_links = pages, links
    original_evidence = thin.navigation_evidence(pages, links)
    if original_evidence["usable"]:
        return pages, links

    recovery.last_recovery.setdefault("candidate_checks", [])
    recovery.last_recovery["thin_surface"] = original_evidence
    recovery.last_recovery["status"] = "THIN_SURFACE_DETECTED"
    recovery.last_recovery["stages_attempted"] = []

    first_party = thin._first_party_bootstrap_candidates(http, start_url, pages)
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
    return pages, links
