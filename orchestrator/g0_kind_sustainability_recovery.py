"""Positive-only sustainability-report recovery from official KIND disclosures.

KIND provides one standardized official disclosure surface across listed issuers.  It is
used here as a recovery/fallback lane, not as proof that a missing report does not exist.
Company-first discovery remains authoritative for freshness; KIND can only add a
byte-verified report or a fallback route for a year that still needs coverage.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_kind_disclosure_recovery as kind
from orchestrator import g0_rename_chronology_recovery as chronology
from orchestrator import zero_touch_discovery as base

STRONG_VERIFICATION = {"VERIFIED", "SOURCE_VERIFIED"}
REPORT_TITLE_MARKERS = ("지속가능경영보고서", "지속가능 경영보고서", "sustainability report", "esg report", "통합보고서")


def _dedupe(values: Iterable[Any]) -> List[Any]:
    out: List[Any] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def _identity_names(discovery: Dict[str, Any]) -> List[str]:
    names = [discovery.get("current_legal_name"), discovery.get("requested_company_name")]
    for alias in discovery.get("company_aliases", []) or []:
        if isinstance(alias, dict) and alias.get("alias_type") != "former_legal_name":
            names.append(alias.get("name"))
    return [str(x).strip() for x in names if str(x or "").strip()]


def _issuer_aligned(issuer: str, discovery: Dict[str, Any]) -> bool:
    issuer_norm = base.normalize_name(issuer)
    if not issuer_norm:
        return False
    identities = {base.normalize_name(x) for x in _identity_names(discovery)}
    return issuer_norm in identities


def _missing_years(documents: Dict[str, Any]) -> List[int]:
    full = set()
    for doc in documents.get("documents", []) or []:
        if doc.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        if str(doc.get("verification_status") or "").upper() not in STRONG_VERIFICATION:
            continue
        try:
            full.add(int(doc.get("report_year")))
        except (TypeError, ValueError):
            pass
    years = []
    for gap in documents.get("gaps", []) or []:
        if gap.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        try:
            year = int(gap.get("year"))
        except (TypeError, ValueError):
            continue
        if year not in full:
            years.append(year)
    if years:
        return sorted(set(years))
    scope = documents.get("discovery_scope") or {}
    window = scope.get("effective_current_entity_history_window") or scope.get("requested_history_window") or scope.get("history_window") or {}
    try:
        start, end = int(window.get("start_year")), int(window.get("end_year"))
    except (TypeError, ValueError):
        return []
    return [year for year in range(start, end + 1) if year not in full]


def _is_sustainability_disclosure(title: str) -> bool:
    compact = re.sub(r"\s+", "", str(title or "")).casefold()
    return "지속가능경영보고서" in compact or "sustainabilityreport" in compact


def _report_name(body_text: str) -> str:
    text = re.sub(r"\s+", " ", str(body_text or "")).strip()
    patterns = (
        r"(?:^|\s)1\.\s*보고서\s*명칭\s*[:|]?\s*(.+?)(?=\s*2\.\s*검증기관|\s*2\.)",
        r"보고서\s*명칭\s*[:|]?\s*(.+?)(?=\s*검증기관|\s*작성기준|\s*제출처)",
    )
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return m.group(1).strip(" |:-")[:300]
    return ""


def _report_year(name: str, wanted: Sequence[int]) -> Optional[int]:
    years = [int(x) for x in re.findall(r"(?<!\d)(20\d{2})(?!\d)", str(name or ""))]
    for year in years:
        if year in wanted:
            return year
    return years[0] if len(set(years)) == 1 and years[0] in wanted else None


def _viewer_parts(http: Any, acceptance_no: str, company_name: str) -> Tuple[str, str, List[str]]:
    wrapper_url = kind.VIEWER + "?method=search&acptno=" + acceptance_no
    wrapper = http.get(wrapper_url, headers={"Referer": kind.SEARCH_MAIN})
    if not wrapper or wrapper.status_code >= 400:
        return wrapper_url, "", []
    wrapper_html = chronology._decode_response_text(wrapper, company_name)
    doc_no = kind._selected_main_doc(wrapper_html)
    if not doc_no:
        return wrapper_url, "", []
    soup = BeautifulSoup(wrapper_html, "html.parser")
    form = soup.find("form", id="docpathfrm") or soup.find("form", attrs={"name": "docpathfrm"})
    action = urljoin(wrapper_url, str(form.get("action") or kind.VIEWER)) if form else kind.VIEWER
    params: Dict[str, str] = {"method": "searchContents", "docNo": doc_no, "goAction2": ""}
    if form:
        for tag in form.find_all("input"):
            name = str(tag.get("name") or "").strip()
            if name:
                params[name] = str(tag.get("value") or "")
        params["docNo"] = doc_no
    path_response = http.get(action, params=params, headers={"Referer": wrapper_url})
    if not path_response or path_response.status_code >= 400:
        return wrapper_url, doc_no, []
    path_html = chronology._decode_response_text(path_response, company_name)
    urls: List[str] = []
    for m in re.finditer(r"(?:parent\.|opener\.|top\.)?setPath\s*\((.*?)\)\s*;?", path_html or "", re.I | re.S):
        quoted = re.findall(r"['\"]([^'\"]*)['\"]", m.group(1))
        if len(quoted) >= 2 and quoted[1]:
            target = urljoin(action, quoted[1])
            if base._host(target) == "kind.krx.co.kr":
                urls.append(target)
    body_url = kind._setpath_body_url(path_html, action)
    if body_url:
        urls.append(body_url)
    return wrapper_url, doc_no, _dedupe(urls)


def _pdf_links(html: str, page_url: str) -> List[Tuple[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        label = " ".join(a.stripped_strings).strip()
        url = urljoin(page_url, str(a.get("href") or "").strip())
        combined = (label + " " + url).casefold()
        if ".pdf" in combined:
            out.append((url, label))
    for match in re.findall(r"https?://[^\"'<>\s]+\.pdf(?:\?[^\"'<>\s]*)?", html or "", re.I):
        out.append((match, ""))
    unique = []
    seen = set()
    for item in out:
        if item[0] not in seen:
            seen.add(item[0]); unique.append(item)
    return unique


def _verify_pdf_magic(http: Any, url: str, referer: str) -> bool:
    response = http.get(url, stream=True, headers={"Referer": referer, "Range": "bytes=0-4095"})
    if not response or response.status_code >= 400:
        return False
    try:
        head = b""
        for chunk in response.iter_content(chunk_size=4096):
            if chunk:
                head += chunk
                break
        return head.lstrip().startswith(b"%PDF-")
    except Exception:
        return False
    finally:
        try:
            response.close()
        except Exception:
            pass


def _attachment_candidates(http: Any, acceptance_no: str, company_name: str, report_name: str, year: int) -> List[Dict[str, str]]:
    wrapper_url, doc_no, pages = _viewer_parts(http, acceptance_no, company_name)
    raw: List[Tuple[str, str, str]] = []
    for page_url in pages[:8]:
        response = http.get(page_url, headers={"Referer": wrapper_url})
        if not response or response.status_code >= 400:
            continue
        html = chronology._decode_response_text(response, company_name)
        for url, label in _pdf_links(html, response.url):
            raw.append((url, label, response.url))
    if not raw:
        return []
    ranked = []
    for url, label, locator in raw:
        text = f"{label} {url} {report_name}".casefold()
        score = 0
        if str(year) in text: score += 8
        if any(marker.casefold() in text for marker in REPORT_TITLE_MARKERS): score += 6
        if any(token in text for token in ("kor", "korean", "국문", "한글")): score += 2
        if any(token in text for token in ("eng", "english", "영문")): score -= 1
        ranked.append((score, url, label, locator))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    verified = []
    for score, url, label, locator in ranked[:6]:
        if _verify_pdf_magic(http, url, locator):
            verified.append({
                "source_url": url,
                "source_locator": locator,
                "label": label,
                "doc_no": doc_no,
                "score": str(score),
            })
    return verified


def _existing_full_by_year(documents: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    out = {}
    for doc in documents.get("documents", []) or []:
        if doc.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        try:
            year = int(doc.get("report_year"))
        except (TypeError, ValueError):
            continue
        out.setdefault(year, doc)
    return out


def _merge_route(documents: Dict[str, Any], recovered: Dict[str, Any]) -> str:
    year = int(recovered["report_year"])
    existing = _existing_full_by_year(documents).get(year)
    if not existing:
        documents.setdefault("documents", []).append(recovered)
        return "PRIMARY_RECOVERY"
    if str(existing.get("source_url") or "") == str(recovered.get("source_url") or ""):
        return "DUPLICATE"
    if str(existing.get("verification_status") or "").upper() not in STRONG_VERIFICATION:
        existing.update({
            key: recovered[key]
            for key in ("source_url", "source_locator", "expected_extension", "verification_status")
        })
        existing["notes"] = (str(existing.get("notes") or "") + "; KIND verified recovery replaced weak route").strip("; ")
        return "REPLACED_WEAK_PRIMARY"
    fallbacks = list(existing.get("fallback_sources") or [])
    if not any(str(x.get("source_url") or "") == recovered["source_url"] for x in fallbacks if isinstance(x, dict)):
        fallbacks.append({
            "source_url": recovered["source_url"],
            "source_locator": recovered["source_locator"],
            "expected_extension": "pdf",
            "verification_status": "SOURCE_VERIFIED",
            "source_role": "KIND_VOLUNTARY_DISCLOSURE_FALLBACK",
            "notes": "Official KIND voluntary sustainability-report disclosure; positive-only fallback route.",
        })
        existing["fallback_sources"] = fallbacks
        return "ADDED_FALLBACK"
    return "DUPLICATE_FALLBACK"


def enrich(discovery: Dict[str, Any], documents: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
    wanted = _missing_years(documents)
    stage: Dict[str, Any] = {
        "policy": "POSITIVE_ONLY_STANDARDIZED_OFFICIAL_DISCLOSURE_FALLBACK",
        "wanted_report_years": wanted,
        "filing_years_checked": [],
        "disclosures_considered": [],
        "recovered": [],
    }
    audit.setdefault("stages", {})["kind_sustainability_recovery"] = stage
    if not wanted:
        stage["status"] = "NOT_NEEDED"
        return documents

    legal = kind._audit_legal(audit)
    code = kind.extract_company_code(legal)
    current = str(discovery.get("current_legal_name") or discovery.get("requested_company_name") or "").strip()
    stage["company_code"] = code or None
    if not current or not code:
        stage["status"] = "NOT_APPLICABLE_NO_LISTED_COMPANY_CODE"
        return documents

    now_year = datetime.now().year
    filing_years = sorted({fy for year in wanted for fy in (year, year + 1) if fy <= now_year})
    http = base.Http(timeout=(4, 10))
    rows: List[Dict[str, str]] = []
    for filing_year in filing_years:
        found = kind.search_year(http, code, current, filing_year, max_pages=4)
        stage["filing_years_checked"].append({"year": filing_year, "row_count": len(found)})
        rows.extend(found)

    candidates = [row for row in rows if _is_sustainability_disclosure(row.get("title", ""))]
    candidates.sort(key=lambda x: (x.get("date", ""), x.get("acceptance_no", "")), reverse=True)
    recovered_years = set()
    for row in candidates:
        if not _issuer_aligned(row.get("issuer", ""), discovery):
            stage["disclosures_considered"].append({"row": dict(row), "status": "ISSUER_NOT_ALIGNED"})
            continue
        body = kind.fetch_disclosure_body(http, row.get("acceptance_no", ""), current)
        if not body:
            stage["disclosures_considered"].append({"row": dict(row), "status": "BODY_UNRESOLVED"})
            continue
        name = _report_name(body.get("text", ""))
        year = _report_year(name, wanted)
        considered = {"row": dict(row), "report_name": name, "report_year": year}
        if year is None or year in recovered_years:
            considered["status"] = "YEAR_NOT_NEEDED_OR_AMBIGUOUS"
            stage["disclosures_considered"].append(considered)
            continue
        attachments = _attachment_candidates(http, row["acceptance_no"], current, name, year)
        if not attachments:
            considered["status"] = "NO_BYTE_VERIFIED_PDF_ATTACHMENT"
            stage["disclosures_considered"].append(considered)
            continue
        primary = attachments[0]
        issuer = str(row.get("issuer") or current).strip()
        recovered = {
            "document_id": f"AUTO_SUSTAINABILITY_KIND_{year}_{row['acceptance_no']}",
            "document_type": "SUSTAINABILITY_REPORT",
            "title": f"{issuer} | {name or (str(year) + ' 지속가능경영보고서')}",
            "source_report_title": name,
            "report_year": year,
            "publication_date": row.get("date") or None,
            "source_url": primary["source_url"],
            "source_locator": primary["source_locator"],
            "expected_extension": "pdf",
            "verification_status": "SOURCE_VERIFIED",
            "importance": "CORE",
            "entity_alignment": "ALIGNED",
            "discovery_channel": "KIND_VOLUNTARY_SUSTAINABILITY_DISCLOSURE",
            "kind_acceptance_no": row["acceptance_no"],
            "kind_doc_no": primary.get("doc_no"),
            "notes": (
                "Official KIND voluntary sustainability-report disclosure; issuer identity aligned and PDF magic bytes verified. "
                "Positive-only recovery: absence from KIND is never used to infer that a report is unpublished."
            ),
            "fallback_sources": [
                {
                    "source_url": item["source_url"],
                    "source_locator": item["source_locator"],
                    "expected_extension": "pdf",
                    "verification_status": "SOURCE_VERIFIED",
                    "source_role": "KIND_ALTERNATE_ATTACHMENT",
                    "notes": "Alternate byte-verified PDF attachment from the same official KIND disclosure.",
                }
                for item in attachments[1:]
            ],
        }
        action = _merge_route(documents, recovered)
        recovered_years.add(year)
        considered["status"] = action
        considered["source_url"] = primary["source_url"]
        stage["disclosures_considered"].append(considered)
        stage["recovered"].append({"year": year, "action": action, "acceptance_no": row["acceptance_no"], "source_url": primary["source_url"]})

    stage["status"] = "RECOVERED" if stage["recovered"] else "NO_POSITIVE_RECOVERY"
    audit.setdefault("http_attempts", []).extend(http.audit)
    return documents
