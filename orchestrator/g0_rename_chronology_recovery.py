"""Recover legal-name continuity from official chronology-style evidence.

This fallback is used only when the earlier explicit rename adapters did not establish a
bounded legal-name change.  It accepts evidence from verified first-party company pages
and official DART/KRX disclosures, repairs ambiguous legacy HTML encodings before
parsing, and requires an exact normalized match to the current legal name before a
predecessor is promoted.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urljoin, urlparse

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


def _decode_response_text(response: Any, current_name: str = "") -> str:
    """Choose the most credible decoding for a fetched official HTML response.

    Some KIND/KRX pages omit or misstate their charset.  ``requests`` can then expose
    UTF-8 bytes as mojibake.  We score the declared text plus bounded candidate decodes
    from the original bytes; presence of the already verified current legal name is the
    strongest signal, followed by Korean legal-history vocabulary and Hangul density.
    """
    candidates: List[str] = []
    try:
        candidates.append(str(response.text or ""))
    except Exception:
        pass
    raw = getattr(response, "content", b"") or b""
    encodings = _dedupe([
        str(getattr(response, "encoding", "") or ""),
        str(getattr(response, "apparent_encoding", "") or ""),
        "utf-8", "cp949", "euc-kr",
    ])
    if raw:
        for encoding in encodings:
            try:
                candidates.append(bytes(raw).decode(encoding, errors="strict"))
            except (UnicodeDecodeError, LookupError, TypeError):
                continue
    candidates = _dedupe(candidates)
    if not candidates:
        return ""

    current_norm = base.normalize_name(current_name)

    def score(text: str) -> int:
        normalized = base.normalize_name(text)
        value = 0
        if current_norm and current_norm in normalized:
            value += 500
        for token, weight in (("상호", 45), ("사명", 30), ("변경", 45), ("연혁", 20), ("회사", 10)):
            if token in text:
                value += weight
        value += min(180, len(re.findall(r"[가-힣]", text)) // 8)
        value -= text.count("�") * 20
        value -= min(120, sum(text.count(x) for x in ("ì", "ë", "ê", "í", "\x80", "\x81")))
        return value

    return max(candidates, key=score)


def _date_value(match: re.Match[str]) -> str:
    if match.group("y1"):
        y, m, d = match.group("y1"), match.group("m1"), match.group("d1")
    else:
        y, m, d = match.group("y2"), match.group("m2"), match.group("d2")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _clean_resulting_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,.;:：-'\"‘’“”")
    for sep in ("：", ":", "•", " - ", " – ", " — ", "|"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1].strip()
    return re.sub(r"^(?:및|또한|당사(?:의)?|회사(?:의)?)[\s:：-]+", "", text).strip()


def parse_resulting_name_chronology(text: str, current_name: str) -> Optional[Dict[str, Any]]:
    """Parse dated resulting-name rows and return the immediate predecessor."""
    compact = re.sub(r"\s+", " ", str(text or ""))
    dates = list(DATE_ANY_RE.finditer(compact))
    entries: List[Dict[str, Any]] = []
    for idx, dm in enumerate(dates):
        end = dates[idx + 1].start() if idx + 1 < len(dates) else min(len(compact), dm.end() + 420)
        segment = compact[dm.end(): min(end, dm.end() + 420)]
        change = CHANGE_RE.search(segment)
        if not change:
            continue
        name = _clean_resulting_name(change.group("name"))
        if name:
            entries.append({"date": _date_value(dm), "name": name, "position": dm.start()})

    current_norm = base.normalize_name(current_name)
    current_indices = [i for i, entry in enumerate(entries) if base.normalize_name(entry["name"]) == current_norm]
    if not current_indices:
        return None
    idx = current_indices[-1]
    predecessor = next(
        (entry["name"] for entry in reversed(entries[:idx]) if base.normalize_name(entry["name"]) not in {"", current_norm}),
        None,
    )
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
    compact = re.sub(r"\s+", " ", str(text or ""))
    mentions: List[Dict[str, str]] = []
    for dm in DATE_ANY_RE.finditer(compact):
        segment = compact[dm.end(): dm.end() + 360]
        next_date = DATE_ANY_RE.search(segment)
        if next_date:
            segment = segment[:next_date.start()]
        for raw in re.findall(
            r"([가-힣A-Za-z0-9&.·㈜()\-\s]{2,120}?)(?:으로|로)(?=\s*(?:상호|사명|회사명)?\s*(?:변경|,|\.))",
            segment,
            re.I,
        ):
            name = _clean_resulting_name(raw)
            if name:
                mentions.append({"date": _date_value(dm), "name": name})

    current_norm = base.normalize_name(current_name)
    for idx, item in enumerate(mentions):
        if base.normalize_name(item["name"]) != current_norm:
            continue
        predecessor = next(
            (x["name"] for x in reversed(mentions[:idx]) if base.normalize_name(x["name"]) not in {"", current_norm}),
            None,
        )
        if predecessor:
            return {
                "date": item["date"], "predecessor": predecessor, "successor": item["name"],
                "chronology": mentions, "evidence_type": "OFFICIAL_MULTI_CHANGE_PROSE",
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
        return (parse_qs(parsed.query).get("uddg") or [""])[0]
    return value


def _official_urls_from_search(html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    urls = [_unwrap_search_href(str(a["href"])) for a in soup.find_all("a", href=True)]
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
        for search_url in (
            "https://html.duckduckgo.com/html/?q=" + encoded,
            "https://www.bing.com/search?q=" + encoded + "&count=20",
            "https://www.google.com/search?q=" + encoded + "&num=20",
        ):
            response = http.get(search_url)
            if not response or response.status_code >= 400:
                continue
            found.extend(_official_urls_from_search(_decode_response_text(response)))
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
    return [
        "https://dart.fss.or.kr/navi/searchNavi.do?" + urlencode({
            "naviCode": code, "naviCrpCik": key, "naviCrpNm": current_name,
        })
        for code in ("A001", "A002", "A003")
    ]


def _official_company_history_pages(audit: Dict[str, Any]) -> List[str]:
    stage = ((audit.get("stages") or {}).get("official_site") or {})
    pages = [
        str(url) for url in stage.get("sample_pages") or []
        if any(token in str(url).casefold() for token in ("history", "company", "about", "overview", "whoweare"))
    ]
    root = str(stage.get("resolved_official_root") or "").strip()
    if root:
        pages.append(root)
    return _dedupe(pages)[:12]


def _same_official_boundary(url: str, audit: Dict[str, Any]) -> bool:
    host = base._host(url)
    if host in OFFICIAL_DISCLOSURE_HOSTS or any(host.endswith("." + h) for h in OFFICIAL_DISCLOSURE_HOSTS):
        return True
    stage = ((audit.get("stages") or {}).get("official_site") or {})
    roots = [str(stage.get("resolved_official_root") or ""), *(stage.get("sample_pages") or [])]
    return any(root and base._same_org_host(root, url) for root in roots)


def _follow_dart_report_links(source_url: str, html: str) -> List[str]:
    """Recover bounded DART report links exposed by a corporate navigation page."""
    soup = BeautifulSoup(html or "", "html.parser")
    targets: List[str] = []
    for tag in soup.find_all(["a", "button", "tr", "td"]):
        blob = " ".join(tag.stripped_strings) + " " + " ".join(f"{k}={v}" for k, v in tag.attrs.items())
        if not any(token in blob for token in ("사업보고서", "반기보고서", "분기보고서", "rcpNo", "rcpno")):
            continue
        href = str(tag.get("href") or "")
        if href:
            target = urljoin(source_url, href).split("#")[0]
            if base._host(target) == "dart.fss.or.kr":
                targets.append(target)
        for rcp in re.findall(r"(?:rcpNo|rcpno)[^0-9]{0,8}(20\d{12})", blob):
            targets.append("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + rcp)
    return _dedupe(targets)[:20]


def discover(http: Any, discovery: Dict[str, Any], audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if any(isinstance(x, dict) and x.get("event_type") == "rename" for x in discovery.get("corporate_restructuring_evidence", []) or []):
        return None
    current = str(discovery.get("current_legal_name") or discovery.get("requested_company_name") or "").strip()
    if not current:
        return None
    brand = legacy._strip_suffix(current)
    queue = _dedupe([
        *_official_company_history_pages(audit),
        *_dart_navi_candidates(audit, current),
        *_search_official_disclosures(http, brand),
    ])
    checked: List[Dict[str, Any]] = []
    seen: set[str] = set()
    while queue and len(seen) < 44:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        response = http.get(url)
        if not response or response.status_code >= 400 or not _same_official_boundary(response.url, audit):
            continue
        decoded = _decode_response_text(response, current)
        text = " ".join(BeautifulSoup(decoded, "html.parser").stripped_strings)
        parsed = parse_official_name_chain(text, current) if base.normalize_name(current) in base.normalize_name(text) else None
        checked.append({"url": response.url, "parsed": parsed})
        if parsed:
            parsed["source_locator"] = response.url
            audit.setdefault("stages", {})["rename_chronology_recovery_candidates"] = checked
            return parsed
        if base._host(response.url) == "dart.fss.or.kr":
            for target in _follow_dart_report_links(response.url, decoded):
                if target not in seen and target not in queue:
                    queue.append(target)
    audit.setdefault("stages", {})["rename_chronology_recovery_candidates"] = checked
    return None


def enrich(discovery: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
    if any(isinstance(x, dict) and x.get("event_type") == "rename" for x in discovery.get("corporate_restructuring_evidence", []) or []):
        return discovery
    http = base.Http()
    rename = discover(http, discovery, audit)
    if rename:
        legacy.apply_rename(discovery, audit, rename)
        audit.setdefault("stages", {})["rename_chronology_recovery"] = rename
    audit.setdefault("http_attempts", []).extend(http.audit)
    return discovery
