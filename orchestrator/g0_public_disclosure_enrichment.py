"""Generic official-disclosure enrichment for G0 legal-name continuity.

Search engines are locator-only.  A rename is promoted only after an official KRX/KIND
or DART page itself supplies an exact date and a legal-name change chain.  The parser
supports both prose (OLD -> NEW) and chronology rows such as
``2023.05.23 : NEW_NAME로 상호 변경``.
"""

from __future__ import annotations

import html as html_lib
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from orchestrator import zero_touch_discovery as base

OFFICIAL_DISCLOSURE_HOSTS = ("kind.krx.co.kr", "dart.fss.or.kr")
DATE_RE = re.compile(
    r"(?:(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일|(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2}))"
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
    return re.sub(r"(?:\s*주식회사|\s*\(주\)|\s*㈜)\s*$", "", text).strip()


def _successor_variants(current_name: str) -> List[str]:
    raw = str(current_name or "").strip()
    values = [raw, _strip_suffix(raw)]
    if raw.endswith("주식회사"):
        values.append(raw[:-4].strip() + "(주)")
    if raw.endswith("(주)"):
        values.append(raw[:-3].strip())
    return _dedupe(values)


def _date_value(match: re.Match[str]) -> str:
    if match.group(1):
        y, m, d = match.group(1), match.group(2), match.group(3)
    else:
        y, m, d = match.group(4), match.group(5), match.group(6)
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _nearest_date_before(text: str, anchor: int, max_distance: int = 500) -> Optional[str]:
    candidates = [(m.end(), _date_value(m)) for m in DATE_RE.finditer(text[:anchor])]
    if not candidates:
        return None
    end, value = max(candidates, key=lambda x: x[0])
    return value if anchor - end <= max_distance else None


def _clean_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,.;:：-'\"‘’“”")
    # Chronology rows often contain bullet/section prose before the legal name.  Keep
    # only the segment after the last hard separator, never arbitrary whitespace.
    for sep in ("：", ":", "•", "·", " - ", " – ", " — "):
        if sep in text:
            text = text.rsplit(sep, 1)[-1].strip()
    if "에서" in text:
        text = text.rsplit("에서", 1)[-1].strip()
    return text


def parse_official_rename_text(text: str, current_name: str) -> Optional[Dict[str, str]]:
    """Parse a direct OLD -> current-name rename statement from official text."""
    compact = re.sub(r"\s+", " ", str(text or ""))
    current_norm = base.normalize_name(current_name)
    for successor in sorted(_successor_variants(current_name), key=len, reverse=True):
        if not successor:
            continue
        sr = re.escape(successor)
        patterns = (
            rf"(?P<old>[가-힣A-Za-z0-9&.·㈜()\- ]{{2,120}}?)\s*에서\s*(?P<new>{sr})\s*(?:으로|로)\s*(?:상호(?:가|를)?|사명(?:이|을)?)\s*변경",
            rf"(?:상호|사명)(?:를|을)?\s*(?P<old>[가-힣A-Za-z0-9&.·㈜()\- ]{{2,120}}?)\s*에서\s*(?P<new>{sr})\s*(?:으로|로)\s*변경",
        )
        for pattern in patterns:
            for m in re.finditer(pattern, compact, re.I):
                old = _clean_name(m.group("old"))
                if not old or base.normalize_name(old) == current_norm:
                    continue
                date = _nearest_date_before(compact, m.start("new"))
                if date:
                    return {"date": date, "predecessor": old, "successor": m.group("new").strip()}
    return None


def parse_official_rename_chronology(text: str, current_name: str) -> Optional[Dict[str, Any]]:
    """Parse date/resulting-name chronology and infer the immediately prior legal name.

    Example supported shape::
      2002.03.16 : OLD_NAME(주)으로 상호 변경
      2023.05.23 : CURRENT_NAME(주)로 상호 변경
    """
    compact = re.sub(r"\s+", " ", str(text or ""))
    entries: List[Dict[str, Any]] = []
    for dm in DATE_RE.finditer(compact):
        after = compact[dm.end(): dm.end() + 260]
        # Stop at the next explicit date so one row cannot consume the following row.
        next_date = DATE_RE.search(after)
        if next_date:
            after = after[:next_date.start()]
        m = re.search(
            r"(?P<name>[가-힣A-Za-z0-9&.·㈜()\- ]{2,120}?)(?:으로|로)\s*(?:상호|사명)(?:가|를|을|이)?\s*변경",
            after,
            re.I,
        )
        if not m:
            continue
        name = _clean_name(m.group("name"))
        if not name:
            continue
        entries.append({"date": _date_value(dm), "name": name, "position": dm.start()})

    current_norm = base.normalize_name(current_name)
    for idx, entry in enumerate(entries):
        if base.normalize_name(entry["name"]) != current_norm:
            continue
        predecessor = None
        for prev in reversed(entries[:idx]):
            if base.normalize_name(prev["name"]) and base.normalize_name(prev["name"]) != current_norm:
                predecessor = prev["name"]
                break
        if predecessor:
            return {
                "date": entry["date"],
                "predecessor": predecessor,
                "successor": entry["name"],
                "chronology": entries,
            }
    return None


def requests_quote(value: str) -> str:
    from urllib.parse import quote_plus
    return quote_plus(value)


def _official_urls_from_search_html(payload: str) -> List[str]:
    """Extract official disclosure URLs from hrefs and encoded/raw search-result text."""
    decoded = html_lib.unescape(unquote(str(payload or "")))
    urls: List[str] = []
    if "<" in decoded:
        soup = BeautifulSoup(decoded, "html.parser")
        for a in soup.find_all("a", href=True):
            href = unquote(str(a["href"]))
            if href.startswith("/url?"):
                q = parse_qs(urlparse(href).query)
                href = (q.get("q") or q.get("url") or [""])[0]
            urls.append(href)
    # Bing/Google occasionally wrap the target inside JavaScript/JSON rather than an
    # actionable href.  Regex recovery remains locator-only; every target is fetched
    # and re-verified on the official host before use.
    urls.extend(re.findall(r"https?://[^\s\"'<>]+", decoded, re.I))
    out: List[str] = []
    for href in urls:
        href = href.replace("&amp;", "&").rstrip("),.;]}")
        host = base._host(href)
        if host in OFFICIAL_DISCLOSURE_HOSTS or any(host.endswith("." + x) for x in OFFICIAL_DISCLOSURE_HOSTS):
            clean = href.split("#")[0]
            if clean not in out:
                out.append(clean)
    return out


def _search_result_urls(http: Any, query: str) -> List[str]:
    # Bing first: fewer automated-query throttles in Actions. Google is bounded fallback.
    searches = [
        "https://www.bing.com/search?q=" + requests_quote(query) + "&count=20",
        "https://www.google.com/search?q=" + requests_quote(query) + "&num=20",
    ]
    for search_url in searches:
        r = http.get(search_url)
        if not r or r.status_code >= 400:
            continue
        found = _official_urls_from_search_html(r.text)
        if found:
            return found
    return []


def discover_official_rename(http: Any, discovery: Dict[str, Any], audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if any(isinstance(x, dict) and x.get("event_type") == "rename" for x in discovery.get("corporate_restructuring_evidence", []) or []):
        return None
    current = str(discovery.get("current_legal_name") or discovery.get("requested_company_name") or "").strip()
    if not current:
        return None
    brand = _strip_suffix(current)
    queries = [
        f'site:kind.krx.co.kr/external "{brand}" "상호의 변경"',
        f'site:kind.krx.co.kr/external "{brand}" "상호 변경"',
        f'site:kind.krx.co.kr/external "{brand}" "연 혁"',
        f'site:dart.fss.or.kr "{brand}" "상호의 변경"',
    ]
    candidates: List[str] = []
    for query in queries:
        candidates.extend(_search_result_urls(http, query))
        candidates = _dedupe(candidates)
        if len(candidates) >= 12:
            break
    checked: List[Dict[str, Any]] = []
    for url in candidates[:16]:
        r = http.get(url)
        if not r or r.status_code >= 400:
            continue
        text = " ".join(BeautifulSoup(r.text, "html.parser").stripped_strings)
        if base.normalize_name(current) not in base.normalize_name(text):
            continue
        parsed = parse_official_rename_chronology(text, current) or parse_official_rename_text(text, current)
        checked.append({"url": r.url, "parsed": parsed})
        if not parsed:
            continue
        parsed.update({
            "source_locator": r.url,
            "evidence_type": "OFFICIAL_DISCLOSURE_RENAME_CHAIN",
        })
        audit.setdefault("stages", {})["public_disclosure_rename_candidates"] = checked
        return parsed
    audit.setdefault("stages", {})["public_disclosure_rename_candidates"] = checked
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
        if isinstance(alias, dict) and alias.get("alias_type") in {
            "requested_name", "english_legal_name", "current_brand_name", "current_alias", "current_legal_alias"
        }:
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
