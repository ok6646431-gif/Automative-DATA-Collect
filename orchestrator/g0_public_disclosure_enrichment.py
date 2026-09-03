"""Generic official-disclosure enrichment for G0 rename continuity.

Search engines are used only to locate candidate KRX/KIND or DART pages. A rename is
promoted only after the official disclosure itself states the predecessor, successor
and effective date. This is intentionally independent from any one company.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from orchestrator import zero_touch_discovery as base

OFFICIAL_DISCLOSURE_HOSTS = ("kind.krx.co.kr", "dart.fss.or.kr")
RENAME_WORDS = ("상호 변경", "상호가 변경", "상호를 변경", "사명 변경", "회사명 변경")
DATE_PATTERNS = (
    re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
    re.compile(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})"),
)


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _strip_suffix(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"(?:\s*주식회사|\s*\(주\)|\s*㈜)\s*$", "", text).strip()
    return text


def _date_candidates(value: str) -> List[Tuple[int, int, str]]:
    candidates: List[Tuple[int, int, str]] = []
    for pat in DATE_PATTERNS:
        for m in pat.finditer(value):
            candidates.append((
                m.start(),
                m.end(),
                f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
            ))
    return sorted(candidates, key=lambda x: (x[0], x[1]))


def _nearest_effective_date(value: str, rename_anchor: int) -> Optional[str]:
    candidates = _date_candidates(value)
    if not candidates:
        return None
    preceding = [x for x in candidates if x[1] <= rename_anchor]
    if preceding:
        return min(preceding, key=lambda x: rename_anchor - x[1])[2]
    return min(candidates, key=lambda x: abs(x[0] - rename_anchor))[2]


def _history_year_hint(http: Any, audit: Dict[str, Any], current_name: str) -> Optional[Dict[str, Any]]:
    stage = ((audit.get("stages") or {}).get("official_site") or {})
    urls = list(stage.get("sample_pages") or [])
    prioritized = [u for u in urls if any(x in u.casefold() for x in ("history", "연혁", "company", "about"))]
    root = str(stage.get("resolved_official_root") or stage.get("dart_website") or "")
    domain = base._host(root)
    if domain:
        for query in (f'"{_strip_suffix(current_name)}" "사명 변경"', f'"{_strip_suffix(current_name)}" "상호 변경"'):
            prioritized.extend(base.search_official_domain_links(http, domain, query))
    for url in _dedupe(prioritized)[:12]:
        r = http.get(url)
        if not r or r.status_code >= 400:
            continue
        text = " ".join(BeautifulSoup(r.text, "html.parser").stripped_strings)
        norm = base.normalize_name(text)
        if base.normalize_name(current_name) not in norm:
            continue
        if not any(word in text for word in RENAME_WORDS):
            continue
        for m in re.finditer(r"(?<!\d)(20\d{2})(?!\d)", text):
            year = int(m.group(1))
            context = text[max(0, m.start() - 250):m.end() + 650]
            if base.normalize_name(current_name) in base.normalize_name(context) and any(w in context for w in RENAME_WORDS):
                return {"year": year, "source_locator": r.url, "context": context[:1200]}
    return None


def _search_result_urls(http: Any, query: str) -> List[str]:
    urls: List[str] = []
    searches = [
        "https://www.google.com/search?q=" + requests_quote(query),
        "https://www.bing.com/search?q=" + requests_quote(query),
        "https://html.duckduckgo.com/html/?q=" + requests_quote(query),
    ]
    for search_url in searches:
        r = http.get(search_url)
        if not r or r.status_code >= 400:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = unquote(str(a["href"]))
            if href.startswith("/url?"):
                q = parse_qs(urlparse(href).query)
                href = (q.get("q") or q.get("url") or [""])[0]
            if href.startswith("//"):
                href = "https:" + href
            host = base._host(href)
            if host in OFFICIAL_DISCLOSURE_HOSTS or any(host.endswith("." + x) for x in OFFICIAL_DISCLOSURE_HOSTS):
                urls.append(href.split("#")[0])
        if urls:
            break
    return _dedupe(urls)


def requests_quote(value: str) -> str:
    from urllib.parse import quote_plus
    return quote_plus(value)


def _clean_company_capture(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,.;:'\"‘’“”")
    # If prose contains an earlier locative particle (e.g. 임시주주총회에서), only the
    # segment after the last such boundary can be the predecessor adjacent to OLD→NEW.
    if "에서" in value:
        value = value.rsplit("에서", 1)[-1].strip()
    tokens = value.split()
    if len(tokens) > 6:
        value = " ".join(tokens[-6:])
    return value


def parse_official_rename_text(text: str, current_name: str) -> Optional[Dict[str, str]]:
    """Parse an explicit OLD -> NEW rename statement from official disclosure text."""
    compact = re.sub(r"\s+", " ", str(text or ""))
    current_norm = base.normalize_name(current_name)
    patterns = (
        r"(?P<old>[가-힣A-Za-z0-9&.·㈜()\- ]{2,80}?)\s*에서\s*(?P<new>[가-힣A-Za-z0-9&.·㈜()\- ]{2,80}?)\s*로\s*상호(?:가|를)?\s*변경",
        r"상호를\s*(?P<old>[가-힣A-Za-z0-9&.·㈜()\- ]{2,80}?)\s*에서\s*(?P<new>[가-힣A-Za-z0-9&.·㈜()\- ]{2,80}?)\s*(?:으로|로)\s*변경",
    )
    for pattern in patterns:
        for m in re.finditer(pattern, compact, re.I):
            old = _clean_company_capture(m.group("old"))
            new = _clean_company_capture(m.group("new"))
            if not old or not new or base.normalize_name(old) == current_norm:
                continue
            new_norm = base.normalize_name(new)
            if not new_norm or not (current_norm in new_norm or new_norm in current_norm):
                continue
            window_start = max(0, m.start() - 450)
            window_end = min(len(compact), m.end() + 250)
            window = compact[window_start:window_end]
            # Anchor date selection at the successor token, not the regex start. The
            # permissive predecessor capture may begin in surrounding prose.
            local_anchor = m.start("new") - window_start
            date = _nearest_effective_date(window, local_anchor)
            if not date:
                continue
            return {"date": date, "predecessor": old, "successor": new}
    return None


def discover_official_rename(http: Any, discovery: Dict[str, Any], audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if any(isinstance(x, dict) and x.get("event_type") == "rename" for x in discovery.get("corporate_restructuring_evidence", []) or []):
        return None
    current = str(discovery.get("current_legal_name") or discovery.get("requested_company_name") or "").strip()
    if not current:
        return None
    hint = _history_year_hint(http, audit, current)
    brand = _strip_suffix(current)
    queries: List[str] = []
    if hint:
        queries.extend([
            f'site:kind.krx.co.kr "{brand}" "상호" "변경" {hint["year"]}',
            f'site:dart.fss.or.kr "{brand}" "상호" "변경" {hint["year"]}',
        ])
    queries.extend([
        f'site:kind.krx.co.kr "{brand}" "상호가 변경"',
        f'site:dart.fss.or.kr "{brand}" "상호가 변경"',
    ])
    candidates: List[str] = []
    for query in queries:
        candidates.extend(_search_result_urls(http, query))
        if len(candidates) >= 12:
            break
    for url in _dedupe(candidates)[:16]:
        r = http.get(url)
        if not r or r.status_code >= 400:
            continue
        text = " ".join(BeautifulSoup(r.text, "html.parser").stripped_strings)
        parsed = parse_official_rename_text(text, current)
        if not parsed:
            continue
        if hint and int(parsed["date"][:4]) != int(hint["year"]):
            continue
        parsed.update({
            "source_locator": r.url,
            "evidence_type": "OFFICIAL_DISCLOSURE_EXPLICIT_RENAME",
            "history_hint": hint,
        })
        return parsed
    return None


def apply_rename(discovery: Dict[str, Any], audit: Dict[str, Any], rename: Dict[str, Any]) -> None:
    predecessor = str(rename.get("predecessor") or "").strip()
    date = str(rename.get("date") or "").strip()
    if not predecessor or not re.match(r"^20\d{2}-\d{2}-\d{2}$", date):
        return
    current = str(discovery.get("current_legal_name") or "")
    if base.normalize_name(predecessor) == base.normalize_name(current):
        return
    rename_year = int(date[:4])
    history_start = int((((discovery.get("collection_policy") or {}).get("requested_history_window") or {}).get("start_year") or rename_year))
    historical = discovery.setdefault("historical_legal_names", [])
    if not any(isinstance(x, dict) and base.normalize_name(x.get("name")) == base.normalize_name(predecessor) for x in historical):
        historical.append({
            "name": predecessor,
            "alias_type": "former_legal_name",
            "active_period": {"start_year": history_start, "end_year": rename_year},
            "verification_state": "VERIFIED",
            "source_locator": rename.get("source_locator"),
        })
    discovery["current_legal_name_active_period"] = {"start_year": rename_year}
    for alias in discovery.get("company_aliases", []) or []:
        if isinstance(alias, dict) and alias.get("alias_type") in {"requested_name", "english_legal_name", "current_brand_name", "current_alias", "current_legal_alias"}:
            alias["active_period"] = {"start_year": rename_year}
    events = discovery.setdefault("corporate_restructuring_evidence", [])
    if not any(isinstance(x, dict) and x.get("event_type") == "rename" and x.get("effective_date") == date for x in events):
        events.append({
            "event_type": "rename",
            "effective_period": {"start_year": rename_year, "end_year": rename_year},
            "effective_date": date,
            "predecessor": predecessor,
            "successor": current,
            "scope": "same legal entity name change",
            "verification_state": "VERIFIED",
            "source_locator": rename.get("source_locator"),
        })
    audit.setdefault("stages", {})["public_disclosure_rename"] = rename


def enrich(discovery: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
    if any(isinstance(x, dict) and x.get("event_type") == "rename" for x in discovery.get("corporate_restructuring_evidence", []) or []):
        return discovery
    http = base.Http()
    rename = discover_official_rename(http, discovery, audit)
    if rename:
        apply_rename(discovery, audit, rename)
    audit.setdefault("http_attempts", []).extend(http.audit)
    return discovery
