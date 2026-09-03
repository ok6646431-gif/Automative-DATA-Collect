"""Recover legal-name continuity from KIND without search-engine dependency.

This adapter is intentionally narrow and fail-closed.  For a DART-verified listed
company it uses the six-digit company/stock code to query KIND's company-by-company
disclosure search, locates official ``변경상장(상호변경)`` disclosures, then follows a
subsequent periodic report through the public disclosure viewer to the actual document
body.  The existing chronology parser decides whether an OLD -> current legal-name
chain is strong enough to promote.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from orchestrator import g0_public_disclosure_enrichment as legacy
from orchestrator import g0_rename_chronology_recovery as chronology
from orchestrator import zero_touch_discovery as base

KIND = "https://kind.krx.co.kr"
SEARCH_MAIN = KIND + "/disclosure/searchdisclosurebycorp.do?method=searchDisclosureByCorpMain"
SEARCH_ENDPOINT = KIND + "/disclosure/searchdisclosurebycorp.do"
VIEWER = KIND + "/common/disclsviewer.do"
PERIODIC_WORDS = ("사업보고서", "반기보고서", "분기보고서")
RENAME_WORDS = ("상호변경", "상호 변경")


def _dedupe(values: Iterable[Any]) -> List[Any]:
    out: List[Any] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def extract_company_code(legal: Dict[str, Any]) -> str:
    """Return a verified-looking six-digit listed-company code, never a DART corp key."""
    for key in ("company_code", "stock_code", "listed_company_code"):
        raw = str(legal.get(key) or "").strip()
        m = re.fullmatch(r"A?(\d{6})", raw, re.I)
        if m:
            return m.group(1)
    raw_text = str(legal.get("raw_text") or "")
    for pattern in (
        r"(?:Company\s*Code|종목코드|단축코드)\s*[:：]?\s*A?(\d{6})(?!\d)",
        r"\bA(\d{6})\b",
    ):
        m = re.search(pattern, raw_text, re.I)
        if m:
            return m.group(1)
    return ""


def _row_date(text: str) -> str:
    m = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", text)
    if not m:
        return ""
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def parse_search_rows(html: str) -> Tuple[List[Dict[str, str]], int]:
    soup = BeautifulSoup(html or "", "html.parser")
    rows: List[Dict[str, str]] = []
    for tr in soup.find_all("tr"):
        text = " ".join(tr.stripped_strings)
        viewer = None
        for a in tr.find_all("a"):
            onclick = str(a.get("onclick") or "")
            m = re.search(r"openDisclsViewer\s*\(\s*['\"](20\d{12})['\"]", onclick)
            if m:
                viewer = (a, m.group(1))
                break
        if not viewer:
            continue
        a, acpt = viewer
        title = str(a.get("title") or " ".join(a.stripped_strings)).strip()
        issuer = ""
        company_anchor = tr.find("a", id="companysum")
        if company_anchor:
            issuer = str(company_anchor.get("title") or " ".join(company_anchor.stripped_strings)).strip()
        rows.append({
            "date": _row_date(text),
            "title": title,
            "acceptance_no": acpt,
            "issuer": issuer,
        })
    page_text = " ".join(soup.stripped_strings)
    m_total = re.search(r"전체\s*([\d,]+)\s*건", page_text)
    total = int(m_total.group(1).replace(",", "")) if m_total else len(rows)
    return rows, total


def _search_payload(code: str, company_name: str, year: int, page: int) -> Dict[str, str]:
    return {
        "method": "searchDisclosureByCorpSub",
        "currentPageSize": "100",
        "pageIndex": str(page),
        "searchCodeType": "",
        "orderIndex": "1",
        "repIsuSrtCd": "A" + code,
        "allRepIsuSrtCd": "",
        "forward": "searchdisclosurebycorp_sub",
        "searchMode": "",
        "kosreq": "",
        "outsvcno": "",
        "orderMode": "",
        "orderStat": "",
        "reportNm": "",
        "reportCd": "",
        "searchCorpName": legacy._strip_suffix(company_name),
        "fromDate": f"{year:04d}0101",
        "toDate": f"{year:04d}1231",
        "reportNmTemp": "",
        "lastReport": "T",
    }


def search_year(http: Any, code: str, company_name: str, year: int, max_pages: int = 12) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    total = None
    pages = 1
    for page in range(1, max_pages + 1):
        if page > pages:
            break
        response = http.post(
            SEARCH_ENDPOINT,
            data=_search_payload(code, company_name, year, page),
            headers={"Referer": SEARCH_MAIN, "X-Requested-With": "XMLHttpRequest"},
        )
        if not response or response.status_code >= 400:
            break
        decoded = chronology._decode_response_text(response, company_name)
        current, total_i = parse_search_rows(decoded)
        if total is None:
            total = total_i
            pages = max(1, min(max_pages, math.ceil(total_i / 100)))
        rows.extend(current)
        if not current:
            break
    unique: List[Dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        key = row.get("acceptance_no", "")
        if key and key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def _selected_main_doc(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    select = soup.find("select", id="mainDoc") or soup.find("select", attrs={"name": "mainDoc"})
    if not select:
        return ""
    option = select.find("option", selected=True) or select.find("option")
    raw = str(option.get("value") or "") if option else ""
    m = re.match(r"(20\d{12})", raw)
    return m.group(1) if m else ""


def _setpath_body_url(html: str, base_url: str) -> str:
    for m in re.finditer(r"(?:parent\.|opener\.|top\.)?setPath\s*\((.*?)\)\s*;?", html or "", re.I | re.S):
        quoted = re.findall(r"['\"]([^'\"]*)['\"]", m.group(1))
        if len(quoted) >= 2 and quoted[1]:
            url = urljoin(base_url, quoted[1])
            if base._host(url) == "kind.krx.co.kr":
                return url
    return ""


def fetch_disclosure_body(http: Any, acceptance_no: str, company_name: str) -> Optional[Dict[str, str]]:
    wrapper_url = VIEWER + "?method=search&acptno=" + acceptance_no
    wrapper = http.get(wrapper_url, headers={"Referer": SEARCH_MAIN})
    if not wrapper or wrapper.status_code >= 400:
        return None
    wrapper_html = chronology._decode_response_text(wrapper, company_name)
    doc_no = _selected_main_doc(wrapper_html)
    if not doc_no:
        return None
    soup = BeautifulSoup(wrapper_html, "html.parser")
    form = soup.find("form", id="docpathfrm") or soup.find("form", attrs={"name": "docpathfrm"})
    action = urljoin(wrapper_url, str(form.get("action") or VIEWER)) if form else VIEWER
    params: Dict[str, str] = {"method": "searchContents", "docNo": doc_no, "goAction2": ""}
    if form:
        for tag in form.find_all("input"):
            name = str(tag.get("name") or "").strip()
            if name:
                params[name] = str(tag.get("value") or "")
        params["docNo"] = doc_no
    path_response = http.get(action, params=params, headers={"Referer": wrapper_url})
    if not path_response or path_response.status_code >= 400:
        return None
    path_html = chronology._decode_response_text(path_response, company_name)
    body_url = _setpath_body_url(path_html, action)
    if not body_url:
        return None
    body_response = http.get(body_url, headers={"Referer": wrapper_url})
    if not body_response or body_response.status_code >= 400:
        return None
    body_html = chronology._decode_response_text(body_response, company_name)
    text = " ".join(BeautifulSoup(body_html, "html.parser").stripped_strings)
    return {
        "acceptance_no": acceptance_no,
        "doc_no": doc_no,
        "wrapper_url": wrapper_url,
        "body_url": body_response.url,
        "text": text,
    }


def _is_rename_title(title: str) -> bool:
    compact = re.sub(r"\s+", "", str(title or ""))
    return "상호변경" in compact and ("변경상장" in compact or "상호변경" == compact)


def _is_periodic_title(title: str) -> bool:
    text = str(title or "")
    return any(word in text for word in PERIODIC_WORDS)


def _requested_year_bounds(discovery: Dict[str, Any]) -> Tuple[int, int]:
    policy = discovery.get("collection_policy") or {}
    requested = policy.get("requested_history_window") or {}
    start = requested.get("start_year")
    end = requested.get("end_year")
    years: List[int] = []
    for cfg in (policy.get("sources") or {}).values():
        if not isinstance(cfg, dict):
            continue
        window = cfg.get("requested_window") or {}
        if window.get("start_year") is not None:
            years.append(int(window["start_year"]))
        if window.get("end_year") is not None:
            years.append(int(window["end_year"]))
        years.extend(int(x) for x in (cfg.get("requested_survey_rounds") or []) if str(x).isdigit())
    if start is None:
        start = min(years) if years else datetime.now().year - 5
    if end is None:
        end = max(years) if years else datetime.now().year
    return int(start), int(end)


def _audit_legal(audit: Dict[str, Any]) -> Dict[str, Any]:
    return dict((((audit.get("stages") or {}).get("legal_identity") or {}).get("resolved") or {}))


def discover(http: Any, discovery: Dict[str, Any], audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return an official rename chain, or None.  Record any detected rename signal."""
    current = str(discovery.get("current_legal_name") or discovery.get("requested_company_name") or "").strip()
    legal = _audit_legal(audit)
    code = extract_company_code(legal)
    stage: Dict[str, Any] = {"company_code": code or None, "years_checked": [], "rename_disclosures": [], "periodic_reports_checked": []}
    audit.setdefault("stages", {})["kind_disclosure_recovery"] = stage
    if not current or not code:
        stage["status"] = "NOT_APPLICABLE_NO_LISTED_COMPANY_CODE"
        return None

    start_year, end_year = _requested_year_bounds(discovery)
    end_year = max(end_year, datetime.now().year)
    # Bound network work even if a malformed request supplied a very old year.
    start_year = max(start_year, end_year - 14)
    all_rows: List[Dict[str, str]] = []
    for year in range(start_year, end_year + 1):
        rows = search_year(http, code, current, year)
        stage["years_checked"].append({"year": year, "row_count": len(rows)})
        all_rows.extend(rows)

    rename_rows = [row for row in all_rows if _is_rename_title(row.get("title", ""))]
    rename_rows.sort(key=lambda x: (x.get("date", ""), x.get("acceptance_no", "")))
    stage["rename_disclosures"] = [dict(x) for x in rename_rows]
    if not rename_rows:
        stage["status"] = "NO_RENAME_DISCLOSURE_FOUND"
        return None

    # The latest change is the only one that can directly bound the current legal name.
    signal = rename_rows[-1]
    signal_date = signal.get("date", "")
    periodic = [
        row for row in all_rows
        if _is_periodic_title(row.get("title", ""))
        and row.get("date", "") >= signal_date
    ]
    periodic.sort(key=lambda x: (x.get("date", ""), x.get("acceptance_no", "")))

    for row in periodic[:6]:
        body = fetch_disclosure_body(http, row["acceptance_no"], current)
        checked = {"row": dict(row), "resolved": bool(body)}
        if body:
            parsed = chronology.parse_official_name_chain(body["text"], current)
            checked.update({"doc_no": body["doc_no"], "body_url": body["body_url"], "parsed": parsed})
            stage["periodic_reports_checked"].append(checked)
            if parsed and base.normalize_name(parsed.get("successor")) == base.normalize_name(current):
                parsed.update({
                    "source_locator": body["body_url"],
                    "evidence_type": "KIND_PERIODIC_REPORT_RENAME_CHAIN",
                    "kind_acceptance_no": row["acceptance_no"],
                    "kind_doc_no": body["doc_no"],
                    "kind_rename_signal_acceptance_no": signal.get("acceptance_no"),
                })
                stage["status"] = "VERIFIED_RENAME_CHAIN"
                stage["verified"] = {k: v for k, v in parsed.items() if k != "chronology"}
                return parsed
        else:
            stage["periodic_reports_checked"].append(checked)

    # Resolve the listing body too: it strongly proves a rename signal/predecessor even
    # when a later periodic report is unavailable, but its listing date is not silently
    # treated as the legal rename effective date.
    listing_body = fetch_disclosure_body(http, signal["acceptance_no"], current)
    if listing_body:
        text = listing_body["text"]
        predecessor = ""
        m = re.search(r"◎\s*([^\n]{2,120}?(?:주식회사|\(주\)|㈜))\s*변경상장\s*\(\s*상호변경\s*\)", text)
        if m:
            predecessor = m.group(1).strip()
        stage["listing_body"] = {
            "doc_no": listing_body["doc_no"],
            "body_url": listing_body["body_url"],
            "predecessor_signal": predecessor or None,
        }
    stage["status"] = "RENAME_SIGNAL_FOUND_CHAIN_UNRESOLVED"
    return None


def _append_unresolved(discovery: Dict[str, Any], item: Dict[str, Any]) -> None:
    items = discovery.setdefault("unresolved_items", [])
    code = item.get("code")
    if not any(isinstance(x, dict) and x.get("code") == code for x in items):
        items.append(item)


def enforce_historical_continuity_gate(discovery: Dict[str, Any], audit: Dict[str, Any]) -> None:
    """Fail closed when official evidence says a rename occurred but predecessor is unresolved."""
    rename_events = [
        x for x in discovery.get("corporate_restructuring_evidence", []) or []
        if isinstance(x, dict) and x.get("event_type") == "rename"
    ]
    if rename_events:
        discovery["unresolved_items"] = [
            x for x in discovery.get("unresolved_items", []) or []
            if not (isinstance(x, dict) and x.get("code") == "HISTORICAL_LEGAL_NAME_PREDECESSOR_UNRESOLVED")
        ]
        return

    stages = audit.get("stages") or {}
    official_recovery = (stages.get("official_site") or {}).get("recovery") or {}
    site_signals = official_recovery.get("rename_signals") or []
    kind_stage = stages.get("kind_disclosure_recovery") or {}
    kind_signals = kind_stage.get("rename_disclosures") or []
    if not site_signals and not kind_signals:
        return

    source = None
    if kind_signals:
        source = KIND + "/disclosure/searchdisclosurebycorp.do?method=searchDisclosureByCorpMain"
    elif site_signals:
        source = site_signals[0].get("url") if isinstance(site_signals[0], dict) else None
    _append_unresolved(discovery, {
        "code": "HISTORICAL_LEGAL_NAME_PREDECESSOR_UNRESOLVED",
        "subject": discovery.get("current_legal_name") or discovery.get("requested_company_name"),
        "detail": "Official evidence indicates a company-name change within the requested history, but the predecessor legal name and effective boundary were not both verified. Historical collection terms must not be promoted unbounded.",
        "source_locator": source,
    })


def enrich(discovery: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
    if any(isinstance(x, dict) and x.get("event_type") == "rename" for x in discovery.get("corporate_restructuring_evidence", []) or []):
        enforce_historical_continuity_gate(discovery, audit)
        return discovery
    http = base.Http()
    rename = discover(http, discovery, audit)
    if rename:
        legacy.apply_rename(discovery, audit, rename)
        audit.setdefault("stages", {})["kind_disclosure_recovery_verified"] = {
            k: v for k, v in rename.items() if k != "chronology"
        }
    audit.setdefault("http_attempts", []).extend(http.audit)
    enforce_historical_continuity_gate(discovery, audit)
    return discovery
