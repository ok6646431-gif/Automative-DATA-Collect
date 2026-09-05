"""Recover useful first-party navigation when the DART-anchored root is only a shell.

A HTTP 200 response is not enough for zero-touch discovery. Some corporate roots are
small JavaScript/bootstrap pages with no crawlable anchors while useful company, site,
and ESG pages live behind frames, scripts, standard sitemap resources, deeper paths,
or same-organization subdomains. This layer keeps the DART host as the trust anchor,
treats every auxiliary source as a locator only, and returns the original first-party
page when no safer improvement can be verified.
"""

from __future__ import annotations

import html as html_lib
import re
from collections import deque
from typing import Any, Dict, Iterable, List, Sequence, Tuple
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_official_site_recovery as recovery
from orchestrator import zero_touch_discovery as base


MIN_INTERNAL_LINKS = 3
MIN_TEXT_CHARS = 12000
MAX_BOOTSTRAP_SCRIPTS = 8
MAX_SITEMAPS = 12
MAX_BOOTSTRAP_URLS = 120

STATIC_ASSET_RE = re.compile(
    r"\.(?:css|js|mjs|map|json|xml|txt|jpg|jpeg|png|gif|svg|webp|ico|woff2?|ttf|eot|mp4|mp3|zip|hwp|xlsx?|docx?|pptx?|pdf)(?:\?|$)",
    re.I,
)
PAGE_PATH_HINT_RE = re.compile(
    r"(?:/|^)(?:home|homepage|company|about|support|location|plant|factory|site|sustainability|esg|report|ir|investor|main|index)(?:/|[-_.]|$)",
    re.I,
)
PAGE_EXTENSION_RE = re.compile(r"\.(?:html?|jsp|do|php|aspx?)(?:\?|$)", re.I)


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold().removeprefix("www.")


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _safe_http_url(value: str) -> bool:
    value = str(value or "").strip()
    if not value or any(ch.isspace() for ch in value) or "›" in value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def _page_candidate(start_url: str, value: str) -> str:
    value = str(value or "").strip().strip("\"'")
    if not value or value.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
        return ""
    candidate = urljoin(start_url, value).split("#", 1)[0]
    if not _safe_http_url(candidate) or not base._same_org_host(start_url, candidate):
        return ""
    if STATIC_ASSET_RE.search(candidate):
        return ""
    return candidate


def _candidate_priority(url: str) -> int:
    marker = unquote(str(url or "")).casefold()
    score = 0
    for token, weight in (
        ("sitemap", 35), ("site-map", 35), ("location", 25),
        ("support", 12), ("company", 18), ("about", 18),
        ("sustainability", 25), ("esg", 20), ("report", 15),
        ("plant", 20), ("factory", 20), ("homepage", 8),
        ("main", 5), ("index", 4),
    ):
        if token in marker:
            score += weight
    return score


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
    """Extract statically visible same-organization redirects and navigation frames."""
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
        for tag, attr in (("iframe", "src"), ("frame", "src"), ("form", "action"), ("base", "href")):
            for node in soup.find_all(tag):
                raw = str(node.get(attr) or "").strip()
                if raw:
                    found.append(urljoin(page.url, raw))
        for pattern in patterns:
            for match in re.findall(pattern, html):
                found.append(urljoin(page.url, match))
    return _dedupe(
        candidate
        for candidate in (_page_candidate(start_url, url) for url in found)
        if candidate
    )


def _literal_page_candidates(start_url: str, base_url: str, source: str) -> List[str]:
    """Recover same-organization page-looking URLs from static HTML/JS text."""
    decoded = unquote(html_lib.unescape(str(source or "")).replace("\\/", "/"))
    found: List[str] = []

    host = _host(start_url)
    if host:
        host_pattern = re.escape(host)
        absolute_re = re.compile(
            rf"(?i)https?://(?:[a-z0-9-]+\.)*{host_pattern}(?::\d+)?(?:/[^\s<>\"'\\]*)?"
        )
        found.extend(absolute_re.findall(decoded))

    # JavaScript/bootstrap shells often keep their real page route in a quoted literal.
    # Relative strings are only retained when they look like a navigable page, and the
    # final URL must still remain inside the independently verified organization domain.
    for raw in re.findall(r"['\"]([^'\"\r\n]{2,360})['\"]", decoded):
        value = raw.strip()
        if value.startswith(("/", "./", "../")):
            if PAGE_EXTENSION_RE.search(value) or PAGE_PATH_HINT_RE.search(value):
                found.append(urljoin(base_url, value))
        elif "/" in value and (PAGE_EXTENSION_RE.search(value) or PAGE_PATH_HINT_RE.search(value)):
            found.append(urljoin(base_url, value))

    return _dedupe(
        candidate
        for candidate in (_page_candidate(start_url, value) for value in found)
        if candidate
    )


def _script_bootstrap_candidates(http: base.Http, start_url: str, pages: Sequence[base.Page]) -> List[str]:
    scripts: List[str] = []
    found: List[str] = []
    for page in pages[:5]:
        soup = BeautifulSoup(str(page.html or ""), "html.parser")
        for node in soup.find_all("script", src=True):
            target = urljoin(page.url, str(node.get("src") or "")).split("#", 1)[0]
            if _safe_http_url(target) and base._same_org_host(start_url, target):
                scripts.append(target)
        found.extend(_literal_page_candidates(start_url, page.url, str(page.html or "")))

    for script_url in _dedupe(scripts)[:MAX_BOOTSTRAP_SCRIPTS]:
        response = http.get(script_url)
        if not response or response.status_code >= 400:
            continue
        ctype = str(response.headers.get("content-type") or "").casefold()
        text = str(response.text or "")
        if len(text) > 2_000_000:
            continue
        if ctype and not any(token in ctype for token in ("javascript", "text", "json")):
            continue
        found.extend(_literal_page_candidates(start_url, script_url, text))
    return sorted(_dedupe(found), key=_candidate_priority, reverse=True)


def _sitemap_loc_values(source: str) -> List[str]:
    return [
        html_lib.unescape(value.strip())
        for value in re.findall(r"(?is)<loc\b[^>]*>\s*(.*?)\s*</loc>", str(source or ""))
        if value.strip()
    ]


def _standard_sitemap_candidates(http: base.Http, start_url: str) -> List[str]:
    """Discover first-party URLs through robots.txt and standard sitemap resources."""
    origin = _origin(start_url)
    if not origin:
        return []

    sitemap_seeds: List[str] = []
    robots = http.get(origin + "/robots.txt")
    if robots and robots.status_code < 400:
        for line in str(robots.text or "").splitlines():
            if line.casefold().lstrip().startswith("sitemap:"):
                value = line.split(":", 1)[1].strip()
                candidate = urljoin(origin + "/", value)
                if _safe_http_url(candidate) and base._same_org_host(start_url, candidate):
                    sitemap_seeds.append(candidate)

    sitemap_seeds.extend([
        origin + "/sitemap.xml",
        origin + "/sitemap_index.xml",
        origin + "/sitemap-index.xml",
    ])

    queue: deque[str] = deque(_dedupe(sitemap_seeds))
    seen_maps: set[str] = set()
    found: List[str] = []
    while queue and len(seen_maps) < MAX_SITEMAPS and len(found) < MAX_BOOTSTRAP_URLS:
        sitemap_url = queue.popleft()
        if sitemap_url in seen_maps:
            continue
        seen_maps.add(sitemap_url)
        response = http.get(sitemap_url)
        if not response or response.status_code >= 400:
            continue
        body = str(response.text or "")
        if len(body) > 5_000_000:
            continue
        for value in _sitemap_loc_values(body):
            target = urljoin(sitemap_url, value).split("#", 1)[0]
            if not _safe_http_url(target) or not base._same_org_host(start_url, target):
                continue
            low = target.casefold().split("?", 1)[0]
            if low.endswith((".xml", ".xml.gz")):
                if len(seen_maps) + len(queue) < MAX_SITEMAPS:
                    queue.append(target)
                continue
            candidate = _page_candidate(start_url, target)
            if candidate:
                found.append(candidate)
                if len(found) >= MAX_BOOTSTRAP_URLS:
                    break
    return sorted(_dedupe(found), key=_candidate_priority, reverse=True)


def _first_party_bootstrap_candidates(
    http: base.Http,
    start_url: str,
    pages: Sequence[base.Page],
) -> List[str]:
    """Recover navigation candidates without leaving the verified organization boundary."""
    return sorted(_dedupe([
        *_embedded_candidates(start_url, pages),
        *_standard_sitemap_candidates(http, start_url),
        *_script_bootstrap_candidates(http, start_url, pages),
    ]), key=_candidate_priority, reverse=True)


def _anchored_urls_from_search_html(start_url: str, source: str) -> List[str]:
    """Extract literal URLs whose authority is inside the DART-anchored domain."""
    return _literal_page_candidates(start_url, start_url, source)


def _anchored_domain_candidates(http: base.Http, start_url: str, company: str) -> List[str]:
    """Locate deep pages under the DART-anchored organization domain via web search."""
    host = _host(start_url)
    if not host:
        return []
    found: List[str] = []
    terms = (
        f'"{company}" 사이트맵',
        f'"{company}" 찾아오시는 길',
        f'"{company}" 국내 사업장',
        f'"{company}" 사업장',
        f'"{company}" 회사소개',
        f'"{company}" 지속가능경영 보고서',
        f'"{company}" sitemap',
    )
    for terms_i in terms:
        query = f"site:{host} {terms_i}"
        search_urls = (
            "https://www.google.com/search?q=" + base.quote(query) + "&num=20",
            "https://www.bing.com/search?q=" + base.quote(query) + "&count=20",
            "https://html.duckduckgo.com/html/?q=" + base.quote(query),
        )
        for search_url in search_urls:
            response = http.get(search_url)
            if not response or response.status_code >= 400:
                continue
            found.extend(_anchored_urls_from_search_html(start_url, response.text))
            for value in recovery._search_result_links(search_url, response.text):
                candidate = _page_candidate(start_url, value)
                if candidate:
                    found.append(candidate)
    return sorted(_dedupe(found), key=_candidate_priority, reverse=True)


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

    first_party_candidates = _first_party_bootstrap_candidates(http, start_url, pages)
    search_candidates = _anchored_domain_candidates(http, start_url, company)
    replacement_candidates = recovery._locate_candidates(http, company)
    candidates = _dedupe([
        *first_party_candidates,
        *search_candidates,
        *replacement_candidates,
    ])
    recovery.last_recovery["bootstrap_discovery"] = {
        "first_party_candidate_count": len(first_party_candidates),
        "anchored_search_candidate_count": len(search_candidates),
        "replacement_candidate_count": len(replacement_candidates),
        "sample_first_party_candidates": first_party_candidates[:10],
    }
    start_host = _host(start_url)

    for candidate in candidates[:60]:
        if not _safe_http_url(candidate) or recovery._blocked(candidate):
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
            verified = True
            verification_method = "DART_HOST_BOOTSTRAP_PAGE"
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

    if original_pages:
        recovery.last_recovery.update({
            "status": "THIN_SURFACE_UNRESOLVED",
            "resolved_url": original_pages[0].url,
            "method": None,
            "thin_surface": original_evidence,
        })
        return original_pages, original_links

    return pages, links
