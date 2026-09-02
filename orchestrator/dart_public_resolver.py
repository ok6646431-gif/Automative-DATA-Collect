"""Public DART company-finder adapter used by G0 Discovery.

The DART finder has changed parameter names/rendering over time.  This adapter avoids
binding G0 to one HTML version: it tries brand spelling variants, known public query
fields, dynamically replays visible forms, and finally uses search-engine result URLs
only as locators.  Returned IDs are always re-verified on DART by the caller.
"""

from __future__ import annotations

import html as html_lib
import re
from typing import Any, Dict, Iterable, List
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

DART = "https://dart.fss.or.kr"

LATIN_TO_KOREAN = {
    "HD": "에이치디",
    "LG": "엘지",
    "SK": "에스케이",
    "KT": "케이티",
    "CJ": "씨제이",
    "LS": "엘에스",
    "GS": "지에스",
    "LX": "엘엑스",
    "DB": "디비",
}


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def query_variants(company: str) -> List[str]:
    raw = str(company or "").strip()
    values = [raw]
    upper = raw.upper()
    for latin, korean in LATIN_TO_KOREAN.items():
        if upper.startswith(latin):
            values.append(korean + raw[len(latin):])
    # Source-native corporate forms are common on DART company finder.
    bases = list(values)
    for value in bases:
        values.extend([value + " 주식회사", value + "(주)"])
    return _dedupe(values)


def extract_select_keys(payload: str) -> List[str]:
    text = html_lib.unescape(str(payload or ""))
    decoded = unquote(text)
    keys: List[str] = []
    patterns = [
        r"selectKey\s*[=:]\s*['\"]?(\d{6,12})",
        r"selectKey(?:=|%3[Dd])(\d{6,12})",
        r"selectPopup\.ax[^\"'<>\s]*?selectKey(?:=|%3[Dd])(\d{6,12})",
        r"historyFmlNm\.ax[^\"'<>\s]*?selectKey(?:=|%3[Dd])(\d{6,12})",
    ]
    for source in (text, decoded):
        for pattern in patterns:
            keys.extend(re.findall(pattern, source, re.I))
        soup = BeautifulSoup(source, "html.parser")
        for a in soup.find_all("a", href=True):
            href = html_lib.unescape(unquote(a["href"]))
            if href.startswith("/url?"):
                q = parse_qs(urlparse(href).query)
                href = (q.get("q") or q.get("url") or [href])[0]
            for pattern in patterns:
                keys.extend(re.findall(pattern, href, re.I))
    return _dedupe(keys)


def _form_payload(form: Any, company: str) -> Dict[str, str]:
    payload: Dict[str, str] = {}
    name_candidates: List[str] = []
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
        if any(token in marker for token in ("crpnm", "corpnm", "company", "회사명", "corpname")):
            name_candidates.append(name)
    for name in name_candidates:
        payload[name] = company
    # Cover historical DART field spellings even when JS creates the visible input.
    for name in ("textCrpNm", "textCrpNM", "crpNm", "corpNm", "companyName"):
        if name in payload:
            payload[name] = company
    for name in list(payload):
        low = name.casefold()
        if "history" in low or "past" in low:
            payload[name] = payload[name] or "Y"
    return payload


def _dynamic_form_attempts(http: Any, endpoint: str, company: str) -> List[str]:
    base = http.get(endpoint)
    if not base or base.status_code >= 500:
        return []
    keys = extract_select_keys(base.text)
    soup = BeautifulSoup(base.text, "html.parser")
    for form in soup.find_all("form"):
        payload = _form_payload(form, company)
        if not payload:
            continue
        action = urljoin(base.url, form.get("action") or endpoint)
        method = (form.get("method") or "GET").upper()
        r = http.post(action, data=payload) if method == "POST" else http.get(action, params=payload)
        if r and r.status_code < 500:
            keys.extend(extract_select_keys(r.text))
    return _dedupe(keys)


def _search_engine_keys(http: Any, company: str) -> List[str]:
    queries = []
    for variant in query_variants(company)[:4]:
        queries.extend([
            f'site:englishdart.fss.or.kr/dsbc001/selectPopup.ax "{variant}"',
            f'site:dart.fss.or.kr "{variant}" "selectKey"',
        ])
    keys: List[str] = []
    for query in queries:
        urls = [
            "https://www.google.com/search?" + urlencode({"q": query, "num": 20}),
            "https://www.bing.com/search?" + urlencode({"q": query, "count": 20}),
            "https://html.duckduckgo.com/html/?" + urlencode({"q": query}),
        ]
        for url in urls:
            r = http.get(url)
            if r and r.status_code < 500:
                keys.extend(extract_select_keys(r.text))
            if keys:
                return _dedupe(keys)
    return _dedupe(keys)


def discover_dart_keys(http: Any, company: str) -> List[str]:
    endpoints = [DART + "/corp/searchCorp.ax", DART + "/corp/searchCorpEx.ax"]
    keys: List[str] = []
    for variant in query_variants(company):
        common_variants = [
            {"textCrpNm": variant, "corporationType": "all", "currentPage": "1", "maxResults": "100", "searchIndex": "", "selectKey": ""},
            {"textCrpNM": variant, "corporationType": "all", "currentPage": "1", "maxResults": "100", "searchIndex": "", "selectKey": ""},
            {"crpNm": variant, "corporationType": "all", "currentPage": "1", "maxResults": "100"},
        ]
        for endpoint in endpoints:
            for payload in common_variants:
                for method in ("GET", "POST"):
                    r = http.get(endpoint, params=payload) if method == "GET" else http.post(endpoint, data=payload)
                    if r and r.status_code < 500:
                        keys.extend(extract_select_keys(r.text))
            keys.extend(_dynamic_form_attempts(http, endpoint, variant))
        if keys:
            break
    if not keys:
        keys.extend(_search_engine_keys(http, company))
    return _dedupe(keys)
