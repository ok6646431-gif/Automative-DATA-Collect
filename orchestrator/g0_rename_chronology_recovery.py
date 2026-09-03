"""Recover legal-name continuity from official chronology-style disclosures.

The first G0 rename adapter handles explicit ``OLD에서 NEW로 변경`` prose.  Public
business reports also commonly express name history as dated chronology rows:

    2002.03.16 : OLD_NAME(주)으로 상호 변경
    2023.05.23 : CURRENT_NAME(주)로 상호 변경

This fallback is company-agnostic.  It searches only official DART/KRX disclosure
pages or already verified first-party company history pages, parses the resulting-name
chain, and promotes the latest predecessor only when the current legal name is an exact
normalized match.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_public_disclosure_enrichment as legacy
from orchestrator import zero_touch_discovery as base

OFFICIAL_DISCLOSURE_HOSTS = ("kind.krx.co.kr", "dart.fss.or.kr")
DATE_ANY_RE = re.compile(
    r"(?:(?P<y1>(?:19|20)\d{2})\s*년\s*(?P<m1>\d{1,2})\s*월\s*(?P<d1>\d{1,2})\s*일?|"
    r"(?P<y2>(?:19|20)\d{2})[.\-/](?P<m2>\d{1,2})[.\-/](?P<d2>\d{1,2}))"
)
CHANGE_RE = re.compile(
    r"(?P<name>[가-힣A-Za-z0-9&.·㈜()\[\]\-\s]{2,140}?)(?:으로|로)\s*"
    r"(?:상호|사명|회사명)(?:가|를|을|이)?\s*변경",
    re.I,
)


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _date_value(match: re.Match[str]) -> str:
    if match.group("y1"):
        y, m, d = match.group("y1"), match.group("m1"), match.group("d1")
    else:
        y, m, d = match.group("y2"), match.group("m2"), match.group("d2")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _clean_resulting_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,.;:：-'\"‘’“”")
    # Keep the final segment after chronology separators/bullets.  Do not split on
    # ordinary spaces because Korean legal names can contain them.
    for sep in ("：", ":", "•", "·", " - ", " – ", " — ", "|"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1].strip()
    text = re.sub(r"^(?:및|또한|당사(?:의)?|회사(?:의)?|상호(?:를|를)?)[\s:：-]+", "", text).strip()
    return text


def parse_resulting_name_chronology(text: str, current_name: str) -> Optional[Dict[str, Any]]:
    """Parse dated resulting-name rows and return the immediate predecessor."""
    compact = re.sub(r"\s+", " ", str(text or ""))
    dates = list(DATE_ANY_RE.finditer(compact))
    entries: List[Dict[str, Any]] = []
    for idx, dm in enumerate(dates):
        end = dates[idx + 1].start() if idx + 1 < len(dates) else min(len(compact), dm.end() + 420)
        segment = compact[dm.end(): min(end, dm.end() + 420)]
        cm = CHANGE_RE.search(segment)
        if not cm:
            continue
        name = _clean_resulting_name(cm.group("name"))
        if not name:
            continue
        entries.append({
            "date": _date_value(dm),
            "name": name,
            "position": dm.start(),
        })

    current_norm = base.normalize_name(current_name)
    current_indices = [
        i for i, entry in enumerate(entries)
        if base.normalize_name(entry["name"]) == current_norm
    ]
    if not current_indices:
        return None
    # The most recent exact current-name row is the legal-name boundary of interest.
    idx = current_indices[-1]
    predecessor = None
    for prev in reversed(entries[:idx]):
        norm = base.normalize_name(prev["name"])
        if norm and norm != current_norm:
            predecessor = prev["name"]
            break
    if not predecessor:
        return None
    return {
        "date": entries[idx]["date"],
        "predecessor": predecessor,
        "successor": entries[idx]["name"],
        "chronology": entries,
        "evidence_type": "OFFICIAL_RESULTING_NAME_CHRONOLOGY",
    }


def parse_multi_change_prose(text: str, current_name: str) -> Optional[Dict[str, Any]]:
    """Parse prose listing successive name changes in one sentence.

    Example: ``2002년 ... A에서 B로, 2023년 ... CURRENT로 변경``.  The predecessor
    of CURRENT is B, not A.
    """
    compact = re.sub(r"\s+", " ", str(text or ""))
    current_norm = base.normalize_name(current_name)
    # First collect dated resulting-name mentions near name-change language.
    mentions: List[Dict[str, str]] = []
    for dm in DATE_ANY_RE.finditer(compact):
        segment = compact[dm.end(): dm.end() + 360]
        stop = DATE_ANY_RE.search(segment)
        if stop:
            segment = segment[:stop.start()]
        # Accept both 'NAME로 상호 변경' and chain prose ending in 'NAME로 변경'.
        candidates = re.findall(
            r"([가-힣A-Za-z0-9&.·㈜()\-\s]{2,120}?)(?:으로|로)(?=\s*(?:상호|사명|회사명)?\s*(?:변경|,|\.))",
            segment,
            re.I,
        )
        for raw in candidates:
            name = _clean_resulting_name(raw)
            if name:
                mentions.append({"date": _date_value(dm), "name": name})
    for idx, item in enumerate(mentions):
        if base.normalize_name(item["name"]) != current_norm:
            continue
        for prev in reversed(mentions[:idx]):
            if base.normalize_name(prev["name"]) and base.normalize_name(prev["name"]) != current_norm:
                return {
                    "date": item["date"],
                    "predecessor": prev["name"],
                    "successor": item["name"],
                    "chronology": mentions,
                    "evidence_type": "OFFICIAL_MULTI_CHANGE_PROSE",
                }
    return None


def parse_official_name_chain(text: str, current_name: str) -> Optional[Dict[str, Any]]:
    return (
        parse_resulting_name_chronology(text, current_name)
        or parse_multi_change_prose(text, current_name)
        or legacy.parse_official_rename_chronology(text, current_name)
        or legacy.parse_official_rename_text(text, current_name)
    )


def _unwrap_search_href(href: str) -> str:
    value = unquote(str(href or "")).replace("&amp;", "&")
    parsed = urlparse(value)
    if value.startswith("/url?"):
        q = parse_qs(parsed.query)
        return (q.get("q") or q.get("url") or [""])[0]
    if "duckduckgo.com/l/" in value:
        q = parse_qs(parsed.query)
        return (q.get("uddg") or [""])[0]
    return value


def _official_urls_from_search(html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    urls: List[str] = []
    for a in soup.find_all("a", href=True):
        urls.append(_unwrap_search_href(str(a["href"])))
    # Preserve the legacy raw/encoded extraction too.
    urls.extend(legacy._official_urls_from_search_html(html))
    out: List[str] = []
    for url in urls:
        host = base._host(url)
        if host not in OFFICIAL_DISCLOSURE_HOSTS and not any(host.endswith("." + h) for h in OFFICIAL_DISCLOSURE_HOSTS):
            continue
        clean = str(url).split("#")[0].rstrip("),.;]}")
        if clean and clean not in out:
            out.append(clean)
    return out


def _search_official_disclosures(http: Any, brand: str) -> List[str]:
    queries = [
        f'site:kind.krx.co.kr/external "{brand}" "상호의 변경"',
        f'site:kind.krx.co.kr/external "{brand}" "상호 변경"',
        f'site:kind.krx.co.kr/external "{brand}" "회사의 연혁"',
        f'site:dart.fss.or.kr "{brand}" "상호의 변경"',
    ]
    found: List[str] = []
    for query in queries:
        encoded = quote_plus(query)
        searches = [
            "https://html.duckduckgo.com/html/?q=" + encoded,
            "https://www.bing.com/search?q=" + encoded + "&count=20",
            "https://www.google.com/search?q=" + encoded + "&num=20",
        ]
        for search_url in searches:
            response = http.get(search_url)
            if not response or response.status_code >= 400:
                continue
            found.extend(_official_urls_from_search(response.text))
            found = _dedupe(found)
            if found:
                break
        if len(found) >= 12:
            break
    return found[:20]


def _dart_navi_candidates(audit: Dict[str, Any], current_name: str) -> List[str]:
    legal = (((audit.get("stages") or {}).get("legal_identity") or {}).get("resolved") or {})
    key = str(legal.get("select_key") or "").strip()
    if not key:
        return []
    # These are DART's platform-wide periodic-report navigation categories.  They are
    # queried as bounded official fallbacks and accepted only if their fetched content
    # contains an exact current-name change chain.
    params_base = {"naviCrpCik": key, "naviCrpNm": current_name}
    urls: List[str] = []
    for code in ("A001", "A002", "A003"):
        params = {"naviCode": code, **params_base}
        urls.append("https://dart.fss.or.kr/navi/searchNavi.do?" + urlencode(params))
    return urls


def _official_company_history_pages(audit: Dict[str, Any]) -> List[str]:
    stage = ((audit.get("stages") or {}).get("official_site") or {})
    pages = list(stage.get("sample_pages") or [])
    chosen: List[str] = []
    for url in pages:
        marker = str(url).casefold()
        if any(x in marker for x in ("history", "company", "about", "overview", "whoweare")):
            chosen.append(url)
    root = str(stage.get("resolved_official_root") or "").strip()
    if root:
        chosen.append(root)
    return _dedupe(chosen)[:12]


def discover(http: Any, discovery: Dict[str, Any], audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if any(
        isinstance(x, dict) and x.get("event_type") == "rename"
        for x in discovery.get("corporate_restructuring_evidence", []) or []
    ):
        return None
    current = str(discovery.get("current_legal_name") or discovery.get("requested_company_name") or "").strip()
    if not current:
        return None
    brand = legacy._strip_suffix(current)

    candidate_urls = [
        *_official_company_history_pages(audit),
        *_dart_navi_candidates(audit, current),
        *_search_official_disclosures(http, brand),
    ]
    checked: List[Dict[str, Any]] = []
    for url in _dedupe(candidate_urls)[:36]:
        response = http.get(url)
        if not response or response.status_code >= 400:
            continue
        host = base._host(response.url)
        official_company_host = base._same_org_host(
            str((((audit.get("stages") or {}).get("official_site") or {}).get("resolved_official_root") or ""),
            response.url,
        )
        official_disclosure = host in OFFICIAL_DISCLOSURE_HOSTS or any(host.endswith("." + h) for h in OFFICIAL_DISCLOSURE_HOSTS)
        if not official_company_host and not official_disclosure:
            continue
        text = " ".join(BeautifulSoup(response.text, "html.parser").stripped_strings)
        if base.normalize_name(current) not in base.normalize_name(text):
            continue
        parsed = parse_official_name_chain(text, current)
        checked.append({"url": response.url, "parsed": parsed})
        if parsed:
            parsed["source_locator"] = response.url
            audit.setdefault("stages", {})["rename_chronology_recovery_candidates"] = checked
            return parsed
    audit.setdefault("stages", {})["rename_chronology_recovery_candidates"] = checked
    return None


def enrich(discovery: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
    if any(
        isinstance(x, dict) and x.get("event_type") == "rename"
        for x in discovery.get("corporate_restructuring_evidence", []) or []
    ):
        return discovery
    http = base.Http()
    rename = discover(http, discovery, audit)
    if rename:
        legacy.apply_rename(discovery, audit, rename)
        audit.setdefault("stages", {})["rename_chronology_recovery"] = rename
    audit.setdefault("http_attempts", []).extend(http.audit)
    return discovery
