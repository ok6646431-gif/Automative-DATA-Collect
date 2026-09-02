"""Public DART company-finder adapter used by G0 Discovery.

The DART finder has changed parameter names/rendering over time. This adapter avoids
binding G0 to one HTML version: it tries brand spelling variants, known public query
fields, dynamically replays visible forms, parses company-result row identifiers from
links/onclick/hidden values, and finally uses search-engine result URLs only as
locators. Returned IDs are always re-verified on DART by the caller.
"""

from __future__ import annotations

import html as html_lib
import re
from typing import Any, Dict, Iterable, List, Sequence
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

KOREAN_TO_LATIN = {v: k.casefold() for k, v in LATIN_TO_KOREAN.items()}
CORP_SUFFIX_RE = re.compile(r"주식회사|유한회사|합자회사|합명회사|\(주\)|㈜|co\.?\s*,?\s*ltd\.?|corp\.?|inc\.?|limited|ltd\.?", re.I)
CODE_FIELD_RE = re.compile(
    r"(?:selectKey|textCrpCik|crpCik|corpCik|corpCode|corpCd|crpCd|crpCode|companyCode)"
    r"[^0-9]{0,40}([0-9]{6,12})",
    re.I,
)
EIGHT_DIGIT_RE = re.compile(r"(?<!\d)(\d{8})(?!\d)")


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _normalize_company(value: str) -> str:
    text = str(value or "").casefold().strip()
    for korean, latin in KOREAN_TO_LATIN.items():
        text = text.replace(korean.casefold(), latin)
    text = CORP_SUFFIX_RE.sub("", text)
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


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
    """Extract explicit selectKey-style IDs from raw or encoded content."""
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
        # Avoid BeautifulSoup's URL-like input warning when source is only a URL.
        if "<" not in source:
            continue
        soup = BeautifulSoup(source, "html.parser")
        for a in soup.find_all("a", href=True):
            href = html_lib.unescape(unquote(a["href"]))
            if href.startswith("/url?"):
                q = parse_qs(urlparse(href).query)
                href = (q.get("q") or q.get("url") or [href])[0]
            for pattern in patterns:
                keys.extend(re.findall(pattern, href, re.I))
    return _dedupe(keys)


def _tag_payload(tag: Any) -> str:
    attrs: List[str] = []
    for node in [tag, *tag.find_all(True)]:
        for key in ("href", "onclick", "value", "data-value", "data-crp", "data-corp", "data-code", "id", "name"):
            value = node.get(key)
            if value:
                attrs.append(str(value))
    return " ".join([" ".join(tag.stripped_strings), *attrs])


def _company_match(context: str, company: str) -> bool:
    target = _normalize_company(company)
    if not target:
        return False
    normalized_context = _normalize_company(context)
    if target in normalized_context or normalized_context in target:
        return True
    return any(
        _normalize_company(v) and _normalize_company(v) in normalized_context
        for v in query_variants(company)
    )


def extract_company_codes(payload: str, company: str) -> List[str]:
    """Extract candidate DART IDs only from result context matching the company.

    DART company-finder pages do not always expose a literal ``selectKey=`` URL.
    Older/current renderers may put the 8-digit company code in a hidden input or a
    JavaScript onclick function. We therefore inspect matched result containers and
    let the caller re-open each candidate on official DART before verification.
    """
    text = html_lib.unescape(unquote(str(payload or "")))
    keys: List[str] = []

    # Field-labeled identifiers are stronger than generic numbers. Preserve them when
    # the whole response itself clearly contains the requested company.
    if _company_match(text, company):
        keys.extend(CODE_FIELD_RE.findall(text))

    if "<" not in text:
        return _dedupe(keys)
    soup = BeautifulSoup(text, "html.parser")

    # Prefer row/list/card-like result containers. This catches onclick arguments,
    # hidden values and hrefs while keeping unrelated script/static IDs out.
    containers: List[Any] = []
    for tag in soup.find_all(["tr", "li", "article"]):
        payload_text = _tag_payload(tag)
        if _company_match(payload_text, company):
            containers.append(tag)
    if not containers:
        # Some DART renderers use generic div blocks instead of table rows.
        for tag in soup.find_all("div"):
            visible = " ".join(tag.stripped_strings)
            if visible and len(visible) <= 1400 and _company_match(visible, company):
                containers.append(tag)

    for tag in containers[:30]:
        context = _tag_payload(tag)
        keys.extend(CODE_FIELD_RE.findall(context))
        keys.extend(EIGHT_DIGIT_RE.findall(context))

    # Direct actionable elements can sit outside the visible text container.
    for node in soup.find_all(attrs={"onclick": True}) + soup.find_all("input") + soup.find_all("a", href=True):
        raw = " ".join(filter(None, [
            str(node.get("onclick") or ""), str(node.get("value") or ""), str(node.get("href") or ""),
        ]))
        codes = CODE_FIELD_RE.findall(raw) + EIGHT_DIGIT_RE.findall(raw)
        if not codes:
            continue
        parent = node.find_parent(["tr", "li", "article", "div"])
        context = _tag_payload(parent) if parent else _tag_payload(node)
        if _company_match(context, company):
            keys.extend(codes)
    return _dedupe(keys)


def company_result_probe(payload: str, company: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Return bounded, non-full-page diagnostics for audit artifacts."""
    text = html_lib.unescape(unquote(str(payload or "")))
    if "<" not in text:
        return []
    soup = BeautifulSoup(text, "html.parser")
    probes: List[Dict[str, Any]] = []
    for tag in soup.find_all(["tr", "li", "article", "div"]):
        visible = re.sub(r"\s+", " ", " ".join(tag.stripped_strings)).strip()
        if not visible or len(visible) > 1600 or not _company_match(visible, company):
            continue
        raw = _tag_payload(tag)
        codes = _dedupe(CODE_FIELD_RE.findall(raw) + EIGHT_DIGIT_RE.findall(raw))
        if not codes and len(visible) > 500:
            continue
        probes.append({"text": visible[:500], "candidate_codes": codes[:12]})
        if len(probes) >= limit:
            break
    return probes


def _extract_response_keys(http: Any, response: Any, company: str, meta: Dict[str, Any]) -> List[str]:
    explicit = extract_select_keys(response.text)
    contextual = extract_company_codes(response.text, company)
    keys = _dedupe([*explicit, *contextual])
    if hasattr(http, "audit"):
        probes = company_result_probe(response.text, company)
        if keys or probes:
            http.audit.append({
                "kind": "DART_RESULT_PROBE",
                **meta,
                "candidate_keys": keys[:30],
                "contexts": probes,
                "response_bytes": len(response.content),
            })
    return keys


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
    keys = _extract_response_keys(http, base, company, {"endpoint": endpoint, "method": "GET_BASE", "variant": company})
    soup = BeautifulSoup(base.text, "html.parser")
    for form in soup.find_all("form"):
        payload = _form_payload(form, company)
        if not payload:
            continue
        action = urljoin(base.url, form.get("action") or endpoint)
        method = (form.get("method") or "GET").upper()
        r = http.post(action, data=payload) if method == "POST" else http.get(action, params=payload)
        if r and r.status_code < 500:
            keys.extend(_extract_response_keys(http, r, company, {"endpoint": action, "method": "DYNAMIC_" + method, "variant": company}))
    return _dedupe(keys)


def _search_engine_keys(http: Any, company: str) -> List[str]:
    queries: List[str] = []
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
        common_variants: Sequence[Dict[str, str]] = [
            {"textCrpNm": variant, "corporationType": "all", "currentPage": "1", "maxResults": "100", "searchIndex": "", "selectKey": ""},
            {"textCrpNM": variant, "corporationType": "all", "currentPage": "1", "maxResults": "100", "searchIndex": "", "selectKey": ""},
            {"crpNm": variant, "corporationType": "all", "currentPage": "1", "maxResults": "100"},
        ]
        for endpoint in endpoints:
            for payload in common_variants:
                for method in ("GET", "POST"):
                    r = http.get(endpoint, params=payload) if method == "GET" else http.post(endpoint, data=payload)
                    if r and r.status_code < 500:
                        keys.extend(_extract_response_keys(http, r, variant, {
                            "endpoint": endpoint,
                            "method": method,
                            "variant": variant,
                            "fields": sorted(payload),
                        }))
            keys.extend(_dynamic_form_attempts(http, endpoint, variant))
        if keys:
            break
    if not keys:
        keys.extend(_search_engine_keys(http, company))
    return _dedupe(keys)
