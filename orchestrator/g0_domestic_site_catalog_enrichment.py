"""Recover complete multi-site scope from first-party domestic-location evidence.

A company's official domestic facilities are not always published on one catalog page.
Some sites expose a location hub whose tabs lead to one page per plant/office. This
module therefore supports both contracts:

1. one explicit domestic-site catalog containing multiple facilities; or
2. multiple first-party location pages reached from the same official navigation hub.

The second contract is intentionally conservative: at least two distinct, explicitly
named operational facilities with valid road addresses must be recovered. A repeated
footer address or one generic "company site" address cannot replace a multi-site scope.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_domestic_site_catalog as catalog
from orchestrator import g0_live_adapters as live
from orchestrator import zero_touch_discovery as base


URL_HINTS = ("location", "locations", "plant", "factory", "dome", "domestic", "company", "support")
LOCATION_WORDS = (
    "찾아오시는 길", "오시는 길", "국내사업장", "국내 사업장", "사업장소개", "사업장 소개",
    "사업장 안내", "제철소", "공장", "연구소", "본사", "사무소",
    "location", "locations", "domestic site", "domestic plant", "plant", "factory",
)
STRONG_LOCATION_WORDS = (
    "찾아오시는 길", "오시는 길", "국내사업장", "국내 사업장", "사업장소개", "사업장 소개",
    "locations", "domestic site", "domestic plant",
)
NEGATIVE_NAV_WORDS = (
    "뉴스", "보도", "미디어", "채용", "문화", "견학", "박물관", "아트홀",
    "news", "press", "media", "recruit", "career", "museum", "culture",
)
GLOBAL_NAV_WORDS = (
    "회사소개", "투자자", "홍보", "고객지원", "지속가능", "로그인", "전체메뉴",
    "company", "investor", "sustainability", "login", "menu",
)
LOCAL_SITE_NAME_RE = re.compile(
    r"([A-Za-z0-9가-힣㈜()·&.\-]{1,45}(?:제철소|공장|연구소|사업장|센터|사무소|본사))",
    re.I,
)
MAX_NAVIGATION_PAGES = 28
MAX_DISCOVERY_DEPTH = 2


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _same_org_page(root: str, value: str) -> str:
    url = str(value or "").strip().split("#", 1)[0]
    if not url or urlparse(url).scheme not in {"http", "https"}:
        return ""
    if not base._same_org_host(root, url):
        return ""
    if re.search(r"\.(?:jpg|jpeg|png|gif|svg|css|js|zip|hwp|xlsx?|docx?|pptx?|pdf)(?:\?|$)", url, re.I):
        return ""
    return url


def _location_score(label: str, target: str, ancestor_text: str = "") -> int:
    label_low = str(label or "").casefold()
    target_low = str(target or "").casefold()
    context_low = str(ancestor_text or "").casefold()
    marker = f"{label_low} {target_low}"
    score = 0
    for word in STRONG_LOCATION_WORDS:
        if word.casefold() in marker:
            score += 12
    for word in LOCATION_WORDS:
        if word.casefold() in marker:
            score += 5
    for hint in URL_HINTS:
        if hint in target_low:
            score += 2
    if any(word.casefold() in context_low for word in STRONG_LOCATION_WORDS):
        # Tabs such as "포항", "광양", "서울" can be semantically meaningful only
        # because they sit inside a verified "찾아오시는 길 / Locations" navigation hub.
        if label_low and not any(word.casefold() in label_low for word in GLOBAL_NAV_WORDS):
            score += 6
    if any(word.casefold() in marker for word in NEGATIVE_NAV_WORDS):
        score -= 10
    return score


def _ancestor_text(anchor: Any) -> str:
    parts: List[str] = []
    node = anchor
    for _ in range(4):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = " ".join(getattr(node, "stripped_strings", []) or [])
        if text:
            parts.append(text[:500])
    return " ".join(parts)


def _navigation_links(root: str, page: base.Page) -> List[Tuple[int, str]]:
    soup = BeautifulSoup(str(page.html or ""), "html.parser")
    out: List[Tuple[int, str]] = []
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.stripped_strings).strip()
        target = _same_org_page(root, urljoin(page.url, anchor["href"]))
        if not target:
            continue
        score = _location_score(label, target, _ancestor_text(anchor))
        if score >= 5:
            out.append((score, target))
    return sorted(out, key=lambda x: x[0], reverse=True)


def _fetch_location_navigation(
    http: base.Http,
    root: str,
    seed_urls: Iterable[str],
) -> Tuple[List[base.Page], List[str]]:
    queue: List[Tuple[int, int, str]] = []
    for url in _dedupe(seed_urls):
        safe = _same_org_page(root, url)
        if safe:
            queue.append((100, 0, safe))
    seen: set[str] = set()
    pages: List[base.Page] = []
    checked: List[str] = []

    while queue and len(pages) < MAX_NAVIGATION_PAGES:
        best_i = max(range(len(queue)), key=lambda i: queue[i][0])
        _, depth, url = queue.pop(best_i)
        if url in seen:
            continue
        seen.add(url)
        checked.append(url)
        response = http.get(url)
        if not response or response.status_code >= 400:
            continue
        ctype = str(response.headers.get("content-type") or "").casefold()
        if "html" not in ctype and not str(response.text or "").lstrip().startswith("<"):
            continue
        page = base.Page(response.url, base._soup_text(response.text), response.text, response.status_code)
        pages.append(page)
        if depth >= MAX_DISCOVERY_DEPTH:
            continue
        for score, target in _navigation_links(root, page)[:36]:
            if target not in seen:
                queue.append((score, depth + 1, target))
    return pages, checked


def _generic_site_name(company: str, name: str) -> bool:
    compact = re.sub(r"\s+", "", str(name or ""))
    company_compact = re.sub(r"\s+", "", str(company or ""))
    return compact in {"사업장", company_compact + "사업장", "주요사업장", company_compact + "주요사업장"}


def _location_page_sites(company: str, page: base.Page) -> Dict[str, Dict[str, Any]]:
    """Extract named operational-site/address pairs from one location-context page."""
    found: Dict[str, Dict[str, Any]] = {}
    for source in (
        catalog._structured_dom_sites(company, page),
        catalog._flattened_text_sites(company, page),
    ):
        for key, item in source.items():
            if _generic_site_name(company, str(item.get("name") or "")):
                continue
            found.setdefault(key, item)

    # Location pages often render a heading such as "포항제철소" and insert buttons or
    # map controls between that heading and the address. Recover the nearest explicit
    # facility token without requiring adjacency to the address.
    text = str(page.text or "")
    for match in live.FLEX_ROAD_ADDRESS_RE.finditer(text):
        address = re.sub(r"\s+", " ", match.group(1)).strip()
        key = catalog._compact(address)
        if not key or key in found:
            continue
        before = text[max(0, match.start() - 420):match.start()]
        names = LOCAL_SITE_NAME_RE.findall(before)
        if not names:
            continue
        name = re.sub(r"\s+", " ", names[-1]).strip()
        if _generic_site_name(company, name):
            continue
        found[key] = {
            "name": name,
            "address": address,
            "source_locator": page.url,
            "extraction_contract": "LOCATION_PAGE_NEAREST_OPERATIONAL_NAME",
        }
    return found


def _aggregate_multi_page_sites(
    company: str,
    pages: Iterable[base.Page],
) -> Dict[str, Dict[str, Any]]:
    aggregate: Dict[str, Dict[str, Any]] = {}
    for page in pages:
        marker = (str(page.url) + " " + str(page.text or "")[:2500]).casefold()
        if not any(word.casefold() in marker for word in LOCATION_WORDS):
            continue
        for key, item in _location_page_sites(company, page).items():
            aggregate.setdefault(key, item)
    return aggregate


def _materialize_site_set(
    company: str,
    found: Dict[str, Dict[str, Any]],
    evidence_type: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    sites: List[Dict[str, Any]] = []
    for item in found.values():
        cid = base._slug(company + " " + item["name"] + " " + item["address"])
        sites.append({
            "candidate_id": cid,
            "site_name_raw": item["name"],
            "address_raw": item["address"],
            "business_unit_raw": "official domestic location navigation",
            "source_locator": item["source_locator"],
            "identity_status": "CONFIRMED",
            "verification_state": "VERIFIED",
            "discovery_evidence": {
                "evidence_type": evidence_type,
                "location_page": item["source_locator"],
                "extraction_contract": item.get("extraction_contract"),
            },
        })
    scope = {
        "mode": "SITE_SET",
        "label": f"{company} 국내 사업장",
        "candidate_ids": [site["candidate_id"] for site in sites],
        "raw_collection_policy": "PRESERVE_COMPANY_WIDE",
        "archive_policy": "FILTER_TO_REQUESTED_SCOPE",
        "analysis_policy": "FILTER_TO_REQUESTED_SCOPE",
    }
    return sites, scope, []


def _promote(
    discovery: Dict[str, Any],
    stages: Dict[str, Any],
    sites: List[Dict[str, Any]],
    scope: Dict[str, Any],
    unresolved: List[Dict[str, Any]],
    recovered_from: str,
) -> None:
    discovery["domestic_site_candidates"] = sites
    discovery["requested_scope"] = scope
    discovery["unresolved_items"] = [
        item for item in (discovery.get("unresolved_items") or [])
        if item.get("code") != "SITE_SCOPE_NOT_UNIQUELY_RESOLVED"
    ] + unresolved
    stages["site_scope"] = {
        "sites": sites,
        "requested_scope": scope,
        "unresolved": unresolved,
        "recovered_from": recovered_from,
    }


def enrich(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    stages = audit.get("stages") or {}
    official = stages.get("official_site") or {}
    root = str(official.get("resolved_official_root") or "")
    if not root:
        stages["domestic_site_catalog_enrichment"] = {"status": "NOT_APPLICABLE_NO_OFFICIAL_ROOT"}
        return discovery, documents, audit

    corp_docs = stages.get("corporate_documents") or {}
    seed_urls = [root]
    seed_urls.extend(list(official.get("sample_pages") or []))
    seed_urls.extend(list(corp_docs.get("report_index_pages") or []))

    http = base.Http(timeout=(5, 15))
    fetched, checked = _fetch_location_navigation(http, root, seed_urls)
    company = str(discovery.get("current_legal_name") or discovery.get("requested_company_name") or "")

    # Strongest contract: one explicit page enumerates the domestic site set.
    explicit = catalog.discover(company, fetched)
    if explicit:
        sites, scope, unresolved = explicit
        _promote(discovery, stages, sites, scope, unresolved, "EXPLICIT_DOMESTIC_SITE_CATALOG")
        stages["domestic_site_catalog_enrichment"] = {
            "status": "RECOVERED",
            "contract": "EXPLICIT_DOMESTIC_SITE_CATALOG",
            "site_count": len(sites),
            "urls_checked": checked,
        }
        audit.setdefault("http_attempts", []).extend(http.audit)
        return discovery, documents, audit

    # Second contract: the same official navigation hub exposes one page per facility.
    aggregate = _aggregate_multi_page_sites(company, fetched)
    source_pages = {str(item.get("source_locator") or "") for item in aggregate.values()}
    if len(aggregate) >= 2 and len(source_pages) >= 2:
        sites, scope, unresolved = _materialize_site_set(
            company, aggregate, "MULTI_PAGE_OFFICIAL_LOCATION_NAVIGATION"
        )
        _promote(discovery, stages, sites, scope, unresolved, "MULTI_PAGE_OFFICIAL_LOCATION_NAVIGATION")
        stages["domestic_site_catalog_enrichment"] = {
            "status": "RECOVERED",
            "contract": "MULTI_PAGE_OFFICIAL_LOCATION_NAVIGATION",
            "site_count": len(sites),
            "source_page_count": len(source_pages),
            "urls_checked": checked,
        }
        audit.setdefault("http_attempts", []).extend(http.audit)
        return discovery, documents, audit

    stages["domestic_site_catalog_enrichment"] = {
        "status": "NO_MULTI_SITE_CATALOG_RESOLVED",
        "urls_checked": checked,
        "named_site_count": len(aggregate),
        "named_site_source_page_count": len(source_pages),
    }
    audit.setdefault("http_attempts", []).extend(http.audit)
    return discovery, documents, audit
