"""Recover a current first-party company website when DART's website field is stale.

Search engines are candidate locators only. A replacement host is accepted only after
its own pages are fetched and show a self-identifying corporate-site structure for the
requested company. No company/domain pairs are hard-coded here.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Sequence, Tuple
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import zero_touch_discovery as base


BASE_CRAWL = base.crawl_official

BLOCKED_HOST_PARTS = (
    "google.", "bing.com", "duckduckgo.com", "naver.com", "daum.net",
    "wikipedia.org", "namu.wiki", "linkedin.com", "facebook.com",
    "instagram.com", "youtube.com", "jobkorea.co.kr", "saramin.co.kr",
    "catch.co.kr", "wanted.co.kr", "dart.fss.or.kr",
)
CORPORATE_STRUCTURE_WORDS = (
    "회사소개", "기업소개", "company", "about", "사업분야", "business",
    "지속가능", "sustainability", "투자자", "investor", "ir", "인재채용",
    "recruit", "career", "윤리경영", "환경경영", "안전·보건·환경",
)
OWNERSHIP_WORDS = ("copyright", "all rights reserved", "회사명", "대표전화", "대표이사")

last_recovery: Dict[str, Any] = {}


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold().removeprefix("www.")


def _blocked(url: str) -> bool:
    host = (urlparse(url).hostname or "").casefold()
    return not host or any(part in host for part in BLOCKED_HOST_PARTS)


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _origin_variants(url: str) -> List[str]:
    parsed = urlparse(url if "://" in url else "https://" + url)
    host = parsed.hostname or ""
    if not host:
        return [url]
    bare = host.removeprefix("www.")
    hosts = [host, bare, "www." + bare]
    schemes = [parsed.scheme if parsed.scheme in {"http", "https"} else "https", "https", "http"]
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return _dedupe(f"{scheme}://{h}{path}" for scheme in schemes for h in hosts)


def _search_result_links(search_url: str, html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[str] = []
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if href.startswith("/url?"):
            href = parse_qs(urlparse(href).query).get("q", [""])[0]
        elif "duckduckgo.com/l/" in href:
            href = parse_qs(urlparse(href).query).get("uddg", [""])[0]
        if href.startswith("//"):
            href = "https:" + href
        href = unquote(href)
        if href.startswith("http") and not _blocked(href):
            out.append(href.split("#")[0])
    return _dedupe(out)


def _locate_candidates(http: base.Http, company: str) -> List[str]:
    queries = (
        f'"{company}" 공식 홈페이지',
        f'"{company}" 회사소개',
        f'"{company}" 지속가능경영',
    )
    found: List[str] = []
    for query in queries:
        search_urls = (
            "https://www.google.com/search?q=" + base.quote(query) + "&num=10",
            "https://www.bing.com/search?q=" + base.quote(query) + "&count=10",
            "https://html.duckduckgo.com/html/?q=" + base.quote(query),
        )
        for search_url in search_urls:
            r = http.get(search_url)
            if not r or r.status_code >= 400:
                continue
            found.extend(_search_result_links(search_url, r.text))
            if found:
                break
        if found:
            break
    # Keep at most one representative URL per host, preserving ranking order.
    host_seen: set[str] = set()
    ranked: List[str] = []
    for url in found:
        host = _host(url)
        if not host or host in host_seen:
            continue
        host_seen.add(host)
        ranked.append(url)
        if len(ranked) >= 8:
            break
    return ranked


def _corporate_self_identifies(company: str, pages: Sequence[base.Page], links: Sequence[Tuple[str, str, str]]) -> Tuple[bool, Dict[str, Any]]:
    if not pages:
        return False, {"reason": "NO_PAGES"}
    company_norm = base.normalize_name(company)
    company_pages = 0
    structure_words: set[str] = set()
    ownership_words: set[str] = set()
    for page in pages[:20]:
        text = page.text or ""
        if company_norm and company_norm in base.normalize_name(text):
            company_pages += 1
        low = text.casefold()
        structure_words.update(word for word in CORPORATE_STRUCTURE_WORDS if word in low)
        ownership_words.update(word for word in OWNERSHIP_WORDS if word in low)
    host = _host(pages[0].url)
    internal_links = {
        target for _, _, target in links
        if _host(target) == host
    }
    # A search result cannot establish identity by itself. Require the fetched site to
    # repeatedly identify the company and expose a multi-section corporate structure.
    verified = (
        company_pages >= 2
        and len(structure_words) >= 4
        and len(ownership_words) >= 1
        and len(internal_links) >= 5
    )
    return verified, {
        "company_pages": company_pages,
        "structure_signals": sorted(structure_words),
        "ownership_signals": sorted(ownership_words),
        "internal_link_count": len(internal_links),
        "resolved_host": host,
    }


def crawl_official(http: base.Http, start_url: str, company: str, max_pages: int = 90):
    """Base crawl with fail-closed recovery for stale/unreachable DART website URLs."""
    global last_recovery
    last_recovery = {
        "status": "NOT_NEEDED",
        "dart_start_url": start_url,
        "resolved_url": None,
        "method": None,
        "candidate_checks": [],
    }

    pages, links = BASE_CRAWL(http, start_url, company, max_pages=max_pages)
    if pages:
        last_recovery["resolved_url"] = pages[0].url
        return pages, links

    # First preserve trust in the DART-declared host and try only transport/WWW variants.
    for variant in _origin_variants(start_url):
        if variant == start_url:
            continue
        pages, links = BASE_CRAWL(http, variant, company, max_pages=max_pages)
        if pages:
            last_recovery.update({
                "status": "RECOVERED",
                "resolved_url": pages[0].url,
                "method": "DART_HOST_VARIANT",
            })
            return pages, links

    # If the host itself is stale, search engines only locate candidates. Promotion is
    # based on content fetched from the candidate corporate site itself.
    for candidate in _locate_candidates(http, company):
        pages, links = BASE_CRAWL(http, candidate, company, max_pages=max_pages)
        verified, evidence = _corporate_self_identifies(company, pages, links)
        last_recovery["candidate_checks"].append({
            "candidate": candidate,
            "verified": verified,
            **evidence,
        })
        if verified:
            last_recovery.update({
                "status": "RECOVERED",
                "resolved_url": pages[0].url,
                "method": "SEARCH_LOCATED_FIRST_PARTY_REVERIFIED",
            })
            return pages, links

    last_recovery["status"] = "FAILED"
    return [], []
