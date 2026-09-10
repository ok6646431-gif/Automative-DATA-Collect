"""Recover explicit first-publication evidence from a verified company's own site.

Search engines are useful locators but are not dependable from CI runners.  This stage
therefore stays inside the already verified first-party web boundary: it follows Media /
News / Press navigation, recognizes same-host search forms, submits a few bounded report
queries, and fetches matching first-party result pages.  It only resolves pre-history
report gaps when an explicit first/inaugural report statement, a nearby year, and the
verified company identity all agree.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_report_enrichment as report_enrichment
from orchestrator import zero_touch_discovery as base

MEDIA_HINTS = (
    "newsroom", "news", "media", "press", "보도", "뉴스", "소식", "홍보",
)
SEARCH_HINTS = (
    "search", "검색", "newsroom", "news", "media", "press", "보도", "뉴스",
)
REPORT_QUERIES = (
    "지속가능경영보고서",
    "지속가능 보고서",
    "sustainability report",
    "ESG 보고서",
)
RESULT_HINTS = (
    "지속가능경영보고서", "지속가능 보고서", "sustainability report", "esg 보고서",
    "첫 발간", "최초", "inaugural", "first report",
)


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _is_html_response(response: Any) -> bool:
    if not response or response.status_code >= 400:
        return False
    ctype = str(response.headers.get("content-type") or "").casefold()
    return "html" in ctype or str(response.text or "").lstrip().startswith("<")


def _text(html: str) -> str:
    return " ".join(BeautifulSoup(html or "", "html.parser").stripped_strings)


def _same_org(root: str, target: str) -> bool:
    try:
        return bool(root and target and base._same_org_host(root, target))
    except Exception:
        root_host = (urlparse(root).hostname or "").casefold().removeprefix("www.").removeprefix("m.")
        target_host = (urlparse(target).hostname or "").casefold().removeprefix("www.").removeprefix("m.")
        return bool(root_host and target_host and (target_host == root_host or target_host.endswith("." + root_host)))


def _identity_terms(discovery: Dict[str, Any]) -> List[str]:
    values = [
        discovery.get("requested_company_name"),
        discovery.get("current_legal_name"),
    ]
    for alias in discovery.get("company_aliases", []) or []:
        if isinstance(alias, dict):
            values.append(alias.get("name"))
        else:
            values.append(alias)
    return _dedupe(str(x) for x in values if x)


def _claim_matches_company(discovery: Dict[str, Any], claim: Dict[str, Any]) -> bool:
    context = base.normalize_name(str(claim.get("claim_context") or ""))
    if not context:
        return False
    for term in _identity_terms(discovery):
        normalized = base.normalize_name(term)
        if normalized and normalized in context:
            return True
    return False


def _claim_from_html(
    discovery: Dict[str, Any],
    html: str,
    url: str,
    start_year: int,
    current_year: int,
) -> Dict[str, Any] | None:
    claim = report_enrichment.first_publication_claim(
        _text(html), url, start_year, current_year
    )
    if claim and _claim_matches_company(discovery, claim):
        return claim
    return None


def _priority_links(root: str, page_url: str, html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    ranked: List[Tuple[int, str]] = []
    for a in soup.find_all("a", href=True):
        target = urljoin(page_url, str(a.get("href") or "")).split("#", 1)[0]
        if not _same_org(root, target):
            continue
        marker = (" ".join(a.stripped_strings) + " " + target).casefold()
        score = 0
        if any(token in marker for token in RESULT_HINTS):
            score += 100
        if any(token in marker for token in MEDIA_HINTS):
            score += 40
        if "sitemap" in marker or "사이트맵" in marker:
            score += 30
        if score:
            ranked.append((score, target))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return _dedupe(url for _, url in ranked)


def _form_payload(form: Any, field_name: str, query: str) -> Dict[str, str]:
    payload: Dict[str, str] = {}
    for inp in form.find_all("input"):
        name = str(inp.get("name") or "").strip()
        if not name:
            continue
        itype = str(inp.get("type") or "text").casefold()
        if name == field_name:
            payload[name] = query
        elif itype == "hidden":
            payload[name] = str(inp.get("value") or "")
        elif itype in {"radio", "checkbox"} and inp.has_attr("checked"):
            payload[name] = str(inp.get("value") or "")
    for select in form.find_all("select"):
        name = str(select.get("name") or "").strip()
        if not name:
            continue
        option = select.find("option", selected=True) or select.find("option")
        if option is not None:
            payload[name] = str(option.get("value") or "")
    payload[field_name] = query
    return payload


def _search_forms(root: str, page_url: str, html: str) -> List[Tuple[Any, str, str, str]]:
    """Return conservative first-party search forms: form, field, action, method."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[Any, str, str, str]] = []
    for form in soup.find_all("form"):
        action = urljoin(page_url, str(form.get("action") or page_url)).split("#", 1)[0]
        if not _same_org(root, action):
            continue
        marker = (" ".join(form.stripped_strings) + " " + action + " " + page_url).casefold()
        if not any(token in marker for token in SEARCH_HINTS):
            continue
        fields = []
        for inp in form.find_all("input"):
            name = str(inp.get("name") or "").strip()
            itype = str(inp.get("type") or "text").casefold()
            if name and itype in {"text", "search", ""}:
                fields.append(name)
        if not fields:
            continue
        method = str(form.get("method") or "get").casefold()
        if method not in {"get", "post"}:
            continue
        out.append((form, fields[0], action, method))
    return out[:4]


def _matching_result_links(root: str, page_url: str, html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[str] = []
    for a in soup.find_all("a", href=True):
        target = urljoin(page_url, str(a.get("href") or "")).split("#", 1)[0]
        if not _same_org(root, target):
            continue
        marker = (" ".join(a.stripped_strings) + " " + target).casefold()
        if any(token in marker for token in RESULT_HINTS):
            out.append(target)
    return _dedupe(out)


def _discover_claim(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
    start_year: int,
    current_year: int,
) -> Tuple[Dict[str, Any] | None, Dict[str, Any]]:
    official = ((audit.get("stages") or {}).get("official_site") or {})
    root = str(official.get("resolved_official_root") or official.get("dart_website") or "").strip()
    if root and "://" not in root:
        root = base._official_url(root)
    stage: Dict[str, Any] = {
        "status": "NOT_FOUND",
        "official_root": root,
        "seed_fetches": 0,
        "navigation_fetches": 0,
        "form_submissions": 0,
        "result_fetches": 0,
    }
    if not root:
        stage["status"] = "NO_VERIFIED_OFFICIAL_ROOT"
        return None, stage

    seeds = [root]
    seeds.extend(official.get("sample_pages") or [])
    for doc in documents.get("documents", []) or []:
        if isinstance(doc, dict):
            seeds.append(doc.get("source_locator"))
    seeds = [u for u in _dedupe(seeds) if _same_org(root, u)][:30]

    http = base.Http()
    fetched: Dict[str, str] = {}
    navigation: List[str] = []
    for url in seeds:
        r = http.get(url)
        stage["seed_fetches"] += 1
        if not _is_html_response(r):
            continue
        fetched[r.url] = r.text
        claim = _claim_from_html(discovery, r.text, r.url, start_year, current_year)
        if claim:
            stage.update({"status": "FOUND_ON_SEED", "claim": claim})
            audit.setdefault("http_attempts", []).extend(http.audit)
            return claim, stage
        navigation.extend(_priority_links(root, r.url, r.text))

    # Prefer explicit media/search/report navigation over generic crawling.
    for url in _dedupe(navigation)[:24]:
        if url in fetched:
            continue
        r = http.get(url)
        stage["navigation_fetches"] += 1
        if not _is_html_response(r):
            continue
        fetched[r.url] = r.text
        claim = _claim_from_html(discovery, r.text, r.url, start_year, current_year)
        if claim:
            stage.update({"status": "FOUND_ON_NAVIGATION", "claim": claim})
            audit.setdefault("http_attempts", []).extend(http.audit)
            return claim, stage

    # Submit a bounded set of search terms through search forms declared by the
    # verified first-party pages themselves. Parameter names/actions are never guessed.
    searchable = list(fetched.items())
    for page_url, html in searchable[:40]:
        for form, field, action, method in _search_forms(root, page_url, html):
            for query in REPORT_QUERIES:
                payload = _form_payload(form, field, query)
                r = http.post(action, data=payload) if method == "post" else http.get(action, params=payload)
                stage["form_submissions"] += 1
                if not _is_html_response(r):
                    continue
                claim = _claim_from_html(discovery, r.text, r.url, start_year, current_year)
                if claim:
                    stage.update({"status": "FOUND_ON_SEARCH_RESULT", "claim": claim})
                    audit.setdefault("http_attempts", []).extend(http.audit)
                    return claim, stage
                for target in _matching_result_links(root, r.url, r.text)[:10]:
                    detail = http.get(target)
                    stage["result_fetches"] += 1
                    if not _is_html_response(detail):
                        continue
                    claim = _claim_from_html(discovery, detail.text, detail.url, start_year, current_year)
                    if claim:
                        stage.update({"status": "FOUND_ON_SEARCH_DETAIL", "claim": claim})
                        audit.setdefault("http_attempts", []).extend(http.audit)
                        return claim, stage

    audit.setdefault("http_attempts", []).extend(http.audit)
    return None, stage


def apply_verified_claim(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    claim: Dict[str, Any],
) -> List[int]:
    """Resolve only years strictly before a corroborated first-report year."""
    first_year = int(claim.get("first_report_year") or 0)
    annual_years = sorted({
        int(d.get("report_year"))
        for d in documents.get("documents", []) or []
        if isinstance(d, dict)
        and d.get("document_type") == "SUSTAINABILITY_REPORT"
        and str(d.get("verification_status") or "").upper() in {"VERIFIED", "SOURCE_VERIFIED"}
        and str(d.get("report_year") or "").isdigit()
    })
    # A clean bridge requires the explicit first-publication year to be represented by
    # a real verified annual report. Otherwise the claim may reveal a different missing
    # document rather than resolve the series.
    if not first_year or not annual_years or min(annual_years) != first_year:
        return []
    resolved: List[int] = []
    for gap in documents.get("gaps", []) or []:
        if not isinstance(gap, dict) or gap.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        try:
            year = int(gap.get("year"))
        except (TypeError, ValueError):
            continue
        if year >= first_year:
            continue
        gap.update({
            "gap_id": f"AUTO_SUSTAINABILITY_{year}_PRE_FIRST_PUBLICATION",
            "verification_status": "SOURCE_VERIFIED",
            "status": "NOT_PUBLISHED",
            "severity": "LOW",
            "blocking": False,
            "reason": (
                "A verified first-party source explicitly identifies "
                f"{first_year} as the first annual sustainability/ESG report publication."
            ),
            "source_locator": claim.get("source_url"),
            "evidence_type": "PRE_FIRST_PUBLICATION_YEAR",
        })
        resolved.append(year)
    documents["discovery_status"] = (
        "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE"
        if not any(g.get("blocking") for g in documents.get("gaps", []) or [])
        else "PARTIAL"
    )
    return resolved


def recover(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    """Recover first-publication evidence only when an unresolved prefix gap exists."""
    annual_years = sorted({
        int(d.get("report_year"))
        for d in documents.get("documents", []) or []
        if isinstance(d, dict)
        and d.get("document_type") == "SUSTAINABILITY_REPORT"
        and str(d.get("verification_status") or "").upper() in {"VERIFIED", "SOURCE_VERIFIED"}
        and str(d.get("report_year") or "").isdigit()
    })
    blocking_prefix = []
    if annual_years:
        first = min(annual_years)
        for gap in documents.get("gaps", []) or []:
            if not isinstance(gap, dict) or gap.get("document_type") != "SUSTAINABILITY_REPORT" or not gap.get("blocking"):
                continue
            try:
                year = int(gap.get("year"))
            except (TypeError, ValueError):
                continue
            if year < first:
                blocking_prefix.append(year)
    if not blocking_prefix:
        audit.setdefault("stages", {})["first_publication_recovery"] = {
            "status": "NOT_NEEDED",
            "resolved_years": [],
        }
        return documents

    policy = discovery.get("collection_policy") or {}
    window = policy.get("requested_history_window") or {}
    start_year = int(window.get("start_year") or min(blocking_prefix))
    current_year = int(window.get("end_year") or max(annual_years))
    claim, stage = _discover_claim(
        discovery, documents, audit, start_year, current_year
    )
    resolved = apply_verified_claim(discovery, documents, claim) if claim else []
    stage["resolved_years"] = resolved
    if claim and resolved:
        stage["status"] = "RESOLVED_PRE_FIRST_PUBLICATION_GAPS"
    elif claim:
        stage["status"] = "CLAIM_FOUND_BUT_NOT_CORROBORATED_BY_FIRST_REPORT_FILE"
    audit.setdefault("stages", {})["first_publication_recovery"] = stage
    return documents
