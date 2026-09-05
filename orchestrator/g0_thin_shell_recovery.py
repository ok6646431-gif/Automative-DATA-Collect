"""Recover useful first-party navigation when the DART-anchored root is only a shell.

A HTTP 200 response is not enough for zero-touch discovery. Some corporate roots are
small JavaScript/bootstrap pages with no crawlable links while the useful company,
site, and ESG pages live at deeper paths or same-organization subdomains. This layer
keeps the DART host as the trust anchor, treats search engines only as locators, and
returns the original thin page when no safer improvement can be verified.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_official_site_recovery as recovery
from orchestrator import zero_touch_discovery as base


MIN_INTERNAL_LINKS = 3
MIN_TEXT_CHARS = 12000


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold().removeprefix("www.")


def navigation_evidence(
    pages: Sequence[base.Page],
    links: Sequence[Tuple[str, str, str]],
) -> Dict[str, Any]:
    if not pages:
        return {
            "page_count": 0,
            "internal_link_count": 0,
            "text_chars": 0,
            "usable": False,
        }
    root = pages[0].url
    root_host = _host(root)
    internal = {
        target.split("#", 1)[0]
        for _, _, target in links
        if _host(target) == root_host
    }
    text_chars = sum(len(str(page.text or "")) for page in pages[:10])
    usable = (
        len(pages) >= 2
        or len(internal) >= MIN_INTERNAL_LINKS
        or text_chars >= MIN_TEXT_CHARS
    )
    return {
        "page_count": len(pages),
        "internal_link_count": len(internal),
        "text_chars": text_chars,
        "usable": usable,
    }


def _embedded_candidates(start_url: str, pages: Sequence[base.Page]) -> List[str]:
    """Extract only statically visible same-organization redirects/deep paths."""
    found: List[str] = []
    patterns = (
        r"(?i)(?:window\.)?location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]",
        r"(?i)location\.replace\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"(?i)location\.assign\(\s*['\"]([^'\"]+)['\"]\s*\)",
    )
    for page in pages[:5]:
        html = str(page.html or "")
        soup = BeautifulSoup(html, "html.parser")
        for meta in soup.find_all("meta"):
            if str(meta.get("http-equiv") or "").casefold() != "refresh":
                continue
            content = str(meta.get("content") or "")
            m = re.search(r"(?i)url\s*=\s*([^;]+)$", content)
            if m:
                found.append(urljoin(page.url, m.group(1).strip(" \"'")))
        for pattern in patterns:
            for match in re.findall(pattern, html):
                found.append(urljoin(page.url, match))
    return _dedupe(
        url.split("#", 1)[0]
        for url in found
        if urlparse(url).scheme in {"http", "https"}
        and base._same_org_host(start_url, url)
    )


def _anchored_domain_candidates(http: base.Http, start_url: str, company: str) -> List[str]:
    """Locate deep pages under the DART-anchored organization domain."""
    host = _host(start_url)
    if not host:
        return []
    found: List[str] = []
    terms = (
        f'"{company}" 회사소개',
        f'"{company}" 국내 사업장',
        f'"{company}" 사업장',
        f'"{company}" 지속가능경영 보고서',
        f'"{company}" site map',
    )
    for query in terms:
        found.extend(base.search_official_domain_links(http, host, query)[:20])
    return _dedupe(found)


def _is_better(candidate: Dict[str, Any], original: Dict[str, Any]) -> bool:
    if candidate.get("usable") and not original.get("usable"):
        return True
    return (
        int(candidate.get("page_count") or 0),
        int(candidate.get("internal_link_count") or 0),
        int(candidate.get("text_chars") or 0),
    ) > (
        int(original.get("page_count") or 0),
        int(original.get("internal_link_count") or 0),
        int(original.get("text_chars") or 0),
    )


def crawl_official(http: base.Http, start_url: str, company: str, max_pages: int = 90):
    """Run normal recovery, then recover from a technically-live but unusable shell."""
    pages, links = recovery.crawl_official(http, start_url, company, max_pages=max_pages)
    original_pages, original_links = pages, links
    original_evidence = navigation_evidence(pages, links)
    if original_evidence["usable"]:
        return pages, links

    recovery.last_recovery.setdefault("candidate_checks", [])
    recovery.last_recovery["thin_surface"] = original_evidence
    recovery.last_recovery["status"] = "THIN_SURFACE_DETECTED"

    candidates = _dedupe([
        *_embedded_candidates(start_url, pages),
        *_anchored_domain_candidates(http, start_url, company),
        *recovery._locate_candidates(http, company),
    ])
    start_host = _host(start_url)

    for candidate in candidates[:30]:
        if not candidate or recovery._blocked(candidate):
            continue
        candidate_pages, candidate_links = recovery.BASE_CRAWL(
            http, candidate, company, max_pages=max_pages
        )
        evidence = navigation_evidence(candidate_pages, candidate_links)
        candidate_host = _host(candidate)
        exact_dart_host = bool(start_host and candidate_host == start_host)
        same_org = base._same_org_host(start_url, candidate)

        verified = False
        verification_method = ""
        if exact_dart_host and candidate_pages and _is_better(evidence, original_evidence):
            # Exact DART host is already independently anchored. Search remains only a
            # locator for a deeper first-party path.
            verified = True
            verification_method = "DART_HOST_DEEP_PATH"
        elif same_org and candidate_pages:
            self_identifies, self_evidence = recovery._corporate_self_identifies(
                company, candidate_pages, candidate_links
            )
            evidence = {**evidence, **self_evidence}
            verified = bool(self_identifies)
            verification_method = "SAME_ORG_SUBDOMAIN_REVERIFIED"
        elif candidate_pages:
            self_identifies, self_evidence = recovery._corporate_self_identifies(
                company, candidate_pages, candidate_links
            )
            evidence = {**evidence, **self_evidence}
            verified = bool(self_identifies)
            verification_method = "REPLACEMENT_HOST_REVERIFIED"

        recovery.last_recovery["candidate_checks"].append({
            "candidate": candidate,
            "verified": verified,
            "verification_method": verification_method,
            **evidence,
        })
        if not verified:
            continue

        recovery.last_recovery.update({
            "status": "RECOVERED",
            "resolved_url": candidate_pages[0].url,
            "method": verification_method,
            "thin_surface": original_evidence,
        })
        return candidate_pages, candidate_links

    # A simple one-page official site may be legitimate. Recovery failure must not turn
    # an existing DART-anchored response into fabricated evidence or total data loss.
    if original_pages:
        recovery.last_recovery.update({
            "status": "THIN_SURFACE_UNRESOLVED",
            "resolved_url": original_pages[0].url,
            "method": None,
            "thin_surface": original_evidence,
        })
        return original_pages, original_links

    return pages, links
