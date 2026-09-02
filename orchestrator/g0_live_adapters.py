"""Live-source adapters that make G0 resilient to changing official-site structures.

Two generic failures motivated this layer:

* Korean administrative-region names can change, so a site address parser must not be
  limited to a frozen province list; and
* an explicit legal-name-change notice may live deep in an official press archive, so
  a bounded general crawl should replay the site's own search form instead of crawling
  hundreds of old articles.

Every promoted fact still requires first-party official evidence. Search forms and
search engines are locators only; the final rename statement is re-fetched from the
same official host and parsed explicitly.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_evidence_enrichment as enrich
from orchestrator import zero_touch_discovery as base


COMMON_REGION = (
    "서울|부산|대구|인천|광주|대전|울산|세종|경기|경기도|강원|강원도|"
    "충북|충청북도|충남|충청남도|전북|전라북도|전남|전라남도|"
    "경북|경상북도|경남|경상남도|제주|제주도"
)
# The first branch supports familiar abbreviations. The second intentionally accepts
# future/merged official region names such as "OO통합특별시" without code changes.
FLEX_ROAD_ADDRESS_RE = re.compile(
    rf"((?:(?:{COMMON_REGION})\s+|[가-힣]{{2,24}}(?:특별자치도|특별자치시|광역시|특별시|도)\s+)"
    r"[가-힣0-9] {0})".replace("[가-힣0-9] {0}", "")
)
# Keep the readable construction separate from the region prefix above.
FLEX_ROAD_ADDRESS_RE = re.compile(
    rf"((?:(?:{COMMON_REGION})\s+|[가-힣]{{2,24}}(?:특별자치도|특별자치시|광역시|특별시|도)\s+)"
    r"[가-힣0-9]{1,24}(?:시|군|구)\s+"
    r"(?:[가-힣0-9]{1,24}(?:읍|면|동|리|구)\s+)?"
    r"[가-힣0-9·.\-]{1,36}(?:대로|로|길)\s*\d+(?:[-~]\d+)?)"
)

PROFILE_URL_WORDS = (
    "about", "company", "status", "overview", "intro", "location", "contact",
    "plant", "factory", "shipyard", "site", "profile",
)
BOARD_URL_WORDS = ("news", "press", "media", "notice", "board", "story")
RENAME_QUERY_WORDS = ("상호", "회사명", "사명")
VIEW_URL_WORDS = ("view", "detail", "read", "article")


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold().removeprefix("www.")


def _same_host(a: str, b: str) -> bool:
    ha, hb = _host(a), _host(b)
    return bool(ha and hb and (ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)))


def _compact(value: str) -> str:
    return re.sub(r"[^0-9가-힣]+", "", value or "")


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def discover_site_candidates(
    company: str,
    pages: Sequence[base.Page],
    dart: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    """Resolve a primary operational site from strong official profile evidence.

    A single company-profile page can be sufficient when the address is locally tied
    to both the company and an operational descriptor (plant/yard/factory/etc.). If
    multiple equally strong operational addresses are found, the function fails closed.
    News/press pages are excluded from primary-site establishment because they often
    mention partner or event locations.
    """

    company_norm = base.normalize_name(company)
    candidates: Dict[str, Dict[str, Any]] = {}

    for page in pages:
        low_url = page.url.casefold()
        if any(word in low_url for word in BOARD_URL_WORDS):
            continue
        is_profile = any(word in low_url for word in PROFILE_URL_WORDS)
        if not is_profile:
            continue
        text = page.text or ""
        for match in FLEX_ROAD_ADDRESS_RE.finditer(text):
            raw = re.sub(r"\s+", " ", match.group(1)).strip()
            context = text[max(0, match.start() - 1200): min(len(text), match.end() + 450)]
            context_norm = base.normalize_name(context)
            operational = [w for w in enrich.OPERATIONAL_SITE_WORDS if w in context.casefold()]
            company_here = bool(company_norm and company_norm in context_norm)
            if not operational or not company_here:
                continue
            key = _compact(raw)
            item = candidates.setdefault(key, {
                "address": raw,
                "pages": [],
                "operational_terms": [],
                "evidence_score": 0,
            })
            if page.url not in item["pages"]:
                item["pages"].append(page.url)
            item["operational_terms"] = _dedupe(item["operational_terms"] + operational)
            item["evidence_score"] += 12 + 2 * len(operational)
            if "status" in low_url or "location" in low_url or "profile" in low_url:
                item["evidence_score"] += 8

    # DART address, when available, remains the strongest independent anchor.
    if dart.get("address"):
        raw = re.sub(r"\s+", " ", str(dart["address"])).strip()
        key = _compact(raw)
        item = candidates.setdefault(key, {
            "address": raw, "pages": [], "operational_terms": ["DART_ADDRESS"],
            "evidence_score": 0,
        })
        source = str(dart.get("source_url") or "")
        if source and source not in item["pages"]:
            item["pages"].append(source)
        item["evidence_score"] += 30

    ranked = sorted(candidates.values(), key=lambda x: x["evidence_score"], reverse=True)
    resolved: Optional[Dict[str, Any]] = None
    if len(ranked) == 1:
        resolved = ranked[0]
    elif len(ranked) > 1 and ranked[0]["evidence_score"] >= ranked[1]["evidence_score"] + 12:
        resolved = ranked[0]

    if resolved:
        cid = base._slug(company + " " + resolved["address"])
        site = {
            "candidate_id": cid,
            "site_name_raw": f"{company} 주요 사업장",
            "address_raw": resolved["address"],
            "business_unit_raw": "official-profile primary operational location",
            "source_locator": resolved["pages"][0] if resolved["pages"] else dart.get("source_url"),
            "identity_status": "CONFIRMED",
            "verification_state": "VERIFIED",
            "discovery_evidence": {
                "official_profile_pages": resolved["pages"],
                "operational_terms": resolved["operational_terms"],
                "evidence_score": resolved["evidence_score"],
            },
        }
        scope = {
            "mode": "SITE_SET",
            "label": f"{company} 주요 사업장",
            "candidate_ids": [cid],
            "raw_collection_policy": "PRESERVE_COMPANY_WIDE",
            "archive_policy": "FILTER_TO_REQUESTED_SCOPE",
            "analysis_policy": "FILTER_TO_REQUESTED_SCOPE",
        }
        return [site], scope, []

    # Preserve the older repeated-evidence resolver as a secondary path for websites
    # without a dedicated company/profile page.
    sites, scope, unresolved = enrich.discover_site_candidates(company, pages, dart)
    if sites:
        for site in sites:
            if site.get("verification_state") in {"VERIFIED", "SOURCE_VERIFIED"}:
                site["identity_status"] = "CONFIRMED"
        return sites, scope, unresolved

    diagnostic = [
        {"address": x["address"], "score": x["evidence_score"], "pages": x["pages"][:3]}
        for x in ranked[:5]
    ]
    if unresolved:
        unresolved[0]["candidate_diagnostics"] = diagnostic
    return sites, scope, unresolved


def _search_form_payload(form: Any, query: str) -> Optional[Dict[str, str]]:
    payload: Dict[str, str] = {}
    keyword_fields: List[str] = []
    for node in form.find_all(["input", "select", "textarea"]):
        name = node.get("name")
        if not name:
            continue
        value = node.get("value", "")
        if node.name == "select":
            selected = node.find("option", selected=True) or node.find("option")
            value = selected.get("value", "") if selected else ""
        payload[name] = value
        marker = " ".join([
            name, node.get("id", ""), node.get("placeholder", ""), node.get("title", ""),
        ]).casefold()
        node_type = (node.get("type") or "").casefold()
        if node.name == "textarea" or node_type in {"text", "search"}:
            if any(word in marker for word in ("keyword", "search", "query", "word", "검색", "selkeyword")):
                keyword_fields.append(name)
    if not keyword_fields:
        return None
    for name in keyword_fields:
        payload[name] = query
    return payload


def _candidate_view_links(result_url: str, html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(result_url, a["href"])
        if not _same_host(result_url, href):
            continue
        marker = (href + " " + " ".join(a.stripped_strings)).casefold()
        if any(word in marker for word in VIEW_URL_WORDS):
            links.append(href.split("#")[0])
    return _dedupe(links)


def _official_board_rename_search(
    pages: Sequence[base.Page],
    current_name: str,
    known_history: Sequence[str],
) -> Optional[Dict[str, Any]]:
    board_pages = [
        p for p in pages
        if any(word in p.url.casefold() for word in BOARD_URL_WORDS)
        and ("list" in p.url.casefold() or "board" in p.url.casefold())
    ]
    if not board_pages:
        return None

    http = base.Http(timeout=(5, 15))
    fetched: List[base.Page] = []
    seen_links: set[str] = set()

    for board in board_pages[:4]:
        soup = BeautifulSoup(board.html or "", "html.parser")
        for form in soup.find_all("form")[:6]:
            for query in RENAME_QUERY_WORDS:
                payload = _search_form_payload(form, query)
                if not payload:
                    continue
                action = urljoin(board.url, form.get("action") or board.url)
                if not _same_host(board.url, action):
                    continue
                method = (form.get("method") or "GET").upper()
                response = http.post(action, data=payload) if method == "POST" else http.get(action, params=payload)
                if not response or response.status_code >= 400:
                    continue
                for link in _candidate_view_links(response.url, response.text)[:30]:
                    if link in seen_links:
                        continue
                    seen_links.add(link)
                    r = http.get(link)
                    if not r or r.status_code >= 400:
                        continue
                    fetched.append(base.Page(r.url, base._soup_text(r.text), r.text, r.status_code))
                    # Parse only verified first-party article/detail pages, not the
                    # aggregate search-result page where dates can be mixed.
                    result = enrich.extract_rename_date_and_names([fetched[-1]], current_name, known_history)
                    if result:
                        result["locator_method"] = "OFFICIAL_SITE_SEARCH_FORM"
                        return result
    return None


def extract_rename_date_and_names(
    pages: Sequence[base.Page],
    current_name: str,
    known_history: Sequence[str],
) -> Optional[Dict[str, Any]]:
    # Fast path: explicit notice already landed in the bounded crawl.
    direct = enrich.extract_rename_date_and_names(pages, current_name, known_history)
    if direct:
        return direct
    # Deep archives are searched through their own first-party search form rather than
    # by increasing the general crawl budget indefinitely.
    return _official_board_rename_search(pages, current_name, known_history)
