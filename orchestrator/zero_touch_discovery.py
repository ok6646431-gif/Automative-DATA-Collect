"""Fail-closed G0 Discovery producer: company name -> verified collection inputs.

This module intentionally stops before the existing collectors.  It resolves a legal
entity from public DART pages, uses the DART-listed official website as the trust
anchor for corporate-document/site discovery, and emits the existing Discovery
contracts.  Search engines, when used, are candidate locators only: a fact is never
VERIFIED unless the final evidence page is DART or an official-company page.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
DART = "https://dart.fss.or.kr"
EN_DART = "https://englishdart.fss.or.kr"
KST = timezone(timedelta(hours=9))
REPORT_WORDS = ("지속가능", "esg", "sustainability", "통합보고", "integrated report", "보고서", "report")
SITE_WORDS = ("사업장", "공장", "조선소", "본사", "주소", "위치", "오시는길", "찾아오시는길", "location", "plant", "factory", "shipyard")
POLICY_WORDS = ("환경경영", "환경관리", "hse", "she", "environment", "안전·보건·환경", "안전보건환경")
CORP_SUFFIXES = (
    "주식회사", "유한회사", "합자회사", "합명회사", "(주)", "㈜", "co.,ltd.", "co., ltd.",
    "co ltd", "corporation", "corp.", "corp", "inc.", "inc", "limited", "ltd.", "ltd",
)
INITIAL_REPLACEMENTS = {
    "에이치디": "hd", "에이치디현대": "hd현대", "엘지": "lg", "에스케이": "sk",
    "케이티": "kt", "에스케이씨": "skc",
}


class DiscoveryError(RuntimeError):
    pass


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_name(value: Any) -> str:
    text = str(value or "").casefold().strip()
    for src, dst in INITIAL_REPLACEMENTS.items():
        text = text.replace(src, dst)
    text = text.replace("＆", "&")
    for suffix in CORP_SUFFIXES:
        text = text.replace(suffix, "")
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def _slug(value: str) -> str:
    ascii_bits = re.findall(r"[a-z0-9]+", normalize_name(value))
    if ascii_bits:
        base = "-".join(ascii_bits)[:42]
    else:
        base = "company"
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"


def _dedupe(values: Iterable[Any]) -> List[Any]:
    out: List[Any] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold().removeprefix("www.")


def _same_org_host(a: str, b: str) -> bool:
    ha, hb = _host(a), _host(b)
    return bool(ha and hb and (ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)))


def _official_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    if not re.match(r"^https?://", text, re.I):
        text = "https://" + text
    return text


@dataclass
class Page:
    url: str
    text: str
    html: str
    status_code: int


class Http:
    def __init__(self, timeout: Tuple[int, int] = (6, 18)) -> None:
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "ko,en;q=0.8"})
        self.timeout = timeout
        self.audit: List[Dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> Optional[requests.Response]:
        try:
            r = self.s.get(url, timeout=self.timeout, allow_redirects=True, **kwargs)
            self.audit.append({"method": "GET", "url": url, "final_url": r.url, "status": r.status_code, "bytes": len(r.content) if not kwargs.get("stream") else None})
            return r
        except Exception as exc:
            self.audit.append({"method": "GET", "url": url, "error": f"{type(exc).__name__}: {exc}"})
            return None

    def post(self, url: str, **kwargs: Any) -> Optional[requests.Response]:
        try:
            r = self.s.post(url, timeout=self.timeout, allow_redirects=True, **kwargs)
            self.audit.append({"method": "POST", "url": url, "final_url": r.url, "status": r.status_code, "bytes": len(r.content)})
            return r
        except Exception as exc:
            self.audit.append({"method": "POST", "url": url, "error": f"{type(exc).__name__}: {exc}"})
            return None


def _soup_text(html: str) -> str:
    return " ".join(BeautifulSoup(html or "", "html.parser").stripped_strings)


def _extract_select_keys(html: str) -> List[str]:
    keys = re.findall(r"selectKey\s*[=:]\s*['\"]?(\d{6,12})", html or "", re.I)
    keys += re.findall(r"selectPopup\.ax\?[^\"'<>]*selectKey=(\d{6,12})", html or "", re.I)
    keys += re.findall(r"historyFmlNm\.ax\?[^\"'<>]*selectKey=(\d{6,12})", html or "", re.I)
    return _dedupe(keys)


def _search_engine_official_dart(http: Http, company: str) -> List[str]:
    query = f'site:englishdart.fss.or.kr/dsbc001/selectPopup.ax "{company}"'
    urls = [
        "https://www.google.com/search?" + urlencode({"q": query, "num": 10}),
        "https://html.duckduckgo.com/html/?" + urlencode({"q": query}),
        "https://www.bing.com/search?" + urlencode({"q": query, "count": 10}),
    ]
    keys: List[str] = []
    for url in urls:
        r = http.get(url)
        if not r or r.status_code >= 400:
            continue
        keys.extend(_extract_select_keys(r.text))
        # Search engines often percent-encode the official URL.
        decoded = requests.utils.unquote(r.text)
        keys.extend(_extract_select_keys(decoded))
        if keys:
            break
    return _dedupe(keys)


def discover_dart_keys(http: Http, company: str) -> List[str]:
    common = {
        "textCrpNm": company, "textCrpNM": company, "corporationType": "all",
        "currentPage": "1", "maxResults": "100", "searchIndex": "",
        "includeHistory": "true", "history": "Y",
    }
    attempts: Sequence[Tuple[str, str]] = (
        ("GET", DART + "/corp/searchCorp.ax"),
        ("GET", DART + "/corp/searchCorpEx.ax"),
        ("POST", DART + "/corp/searchCorp.ax"),
        ("POST", DART + "/corp/searchCorpEx.ax"),
    )
    keys: List[str] = []
    for method, url in attempts:
        r = http.get(url, params=common) if method == "GET" else http.post(url, data=common)
        if r and r.status_code < 500:
            keys.extend(_extract_select_keys(r.text))
    if not keys:
        keys.extend(_search_engine_official_dart(http, company))
    return _dedupe(keys)


def parse_dart_company(html: str, select_key: str, source_url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    pairs: Dict[str, str] = {}
    for tr in soup.find_all("tr"):
        cells = [" ".join(x.stripped_strings).strip() for x in tr.find_all(["th", "td"])]
        if len(cells) >= 2:
            pairs[cells[0].casefold()] = cells[1]
    text = _soup_text(html)

    def pick(*labels: str) -> str:
        for label in labels:
            key = label.casefold()
            for lhs, rhs in pairs.items():
                if key in lhs and rhs:
                    return rhs.strip()
        return ""

    korean = pick("Company Name (Korean)", "회사명", "회사이름")
    english = pick("Company Name (English)", "영문")
    website = pick("Website", "홈페이지")
    established = pick("Establishment Date", "설립일")
    address = pick("Address", "주소")
    tax_id = pick("Taxpayer Identification Number", "사업자등록번호")
    corp_reg = pick("Corporation Registration Number", "법인등록번호")
    if not korean:
        m = re.search(r"Company Name \(Korean\)\s+([^\n|]+)", text, re.I)
        korean = m.group(1).strip() if m else ""
    return {
        "select_key": select_key,
        "korean_name": korean,
        "english_name": english,
        "website": website,
        "establishment_date": established,
        "address": address,
        "tax_id": tax_id,
        "corporation_registration_number": corp_reg,
        "source_url": source_url,
        "raw_text": text[:6000],
    }


def fetch_dart_company(http: Http, key: str) -> Optional[Dict[str, Any]]:
    url = EN_DART + "/dsbc001/selectPopup.ax?" + urlencode({"selectKey": key})
    r = http.get(url)
    if not r or r.status_code >= 400:
        return None
    parsed = parse_dart_company(r.text, key, r.url)
    if not parsed["korean_name"]:
        # Korean company overview is a secondary official parser fallback.
        kr = http.get(DART + "/dsae001/main.do", params={"selectKey": key})
        if kr and kr.status_code < 400:
            txt = _soup_text(kr.text)
            parsed["raw_text"] += " " + txt[:4000]
    return parsed


def legal_match_score(requested: str, candidate: Dict[str, Any]) -> int:
    q = normalize_name(requested)
    ko = normalize_name(candidate.get("korean_name"))
    en = normalize_name(candidate.get("english_name"))
    if not q or not ko:
        return 0
    if q == ko:
        return 100
    if q in ko or ko in q:
        return 92
    if q and q in en:
        return 88
    # Token overlap is candidate-ranking only and never sufficient by itself to VERIFY.
    qt = set(re.findall(r"[a-z]+|[가-힣]{2,}|\d+", q))
    kt = set(re.findall(r"[a-z]+|[가-힣]{2,}|\d+", ko + en))
    return 50 + min(30, 10 * len(qt & kt)) if qt & kt else 0


def resolve_legal_identity(http: Http, company: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    keys = discover_dart_keys(http, company)
    candidates = [x for x in (fetch_dart_company(http, k) for k in keys[:20]) if x]
    ranked = sorted(((legal_match_score(company, c), c) for c in candidates), key=lambda x: x[0], reverse=True)
    if not ranked:
        return None, []
    top_score, top = ranked[0]
    tied = [c for score, c in ranked if score >= max(88, top_score - 3)]
    if top_score < 88 or len(tied) != 1:
        return None, [dict(c, match_score=s) for s, c in ranked]
    return top, [dict(c, match_score=s) for s, c in ranked]


def discover_dart_name_history(http: Http, key: str) -> List[str]:
    url = DART + "/corp/historyFmlNm.ax"
    responses = [http.get(url, params={"selectKey": key}), http.post(url, data={"selectKey": key})]
    names: List[str] = []
    for r in responses:
        if not r or r.status_code >= 400:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for tr in soup.find_all("tr"):
            cells = [" ".join(x.stripped_strings).strip() for x in tr.find_all("td")]
            if not cells:
                continue
            value = cells[-1]
            if value and "회사" not in value and len(value) >= 2:
                names.append(value)
        # Some DART versions render data in JS/JSON rather than table rows.
        for m in re.finditer(r'"(?:corpNm|fmlNm|companyName)"\s*:\s*"([^"]+)"', r.text):
            names.append(m.group(1))
    return _dedupe(names)


def search_official_domain_links(http: Http, domain: str, terms: str) -> List[str]:
    if not domain:
        return []
    query = f"site:{domain} {terms}"
    urls = [
        "https://www.google.com/search?" + urlencode({"q": query, "num": 20}),
        "https://www.bing.com/search?" + urlencode({"q": query, "count": 20}),
        "https://html.duckduckgo.com/html/?" + urlencode({"q": query}),
    ]
    found: List[str] = []
    for search_url in urls:
        r = http.get(search_url)
        if not r or r.status_code >= 400:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/url?q="):
                href = parse_qs(urlparse(href).query).get("q", [""])[0]
            if href.startswith("//"):
                href = "https:" + href
            if href.startswith("http") and (_host(href) == domain or _host(href).endswith("." + domain)):
                found.append(href.split("#")[0])
        if found:
            break
    return _dedupe(found)


def _priority(link_text: str, href: str) -> int:
    value = (link_text + " " + href).casefold()
    score = 0
    for word in REPORT_WORDS:
        if word in value:
            score += 8
    for word in SITE_WORDS:
        if word in value:
            score += 5
    for word in POLICY_WORDS:
        if word in value:
            score += 5
    for word in ("회사소개", "기업소개", "company", "about", "history", "연혁", "news", "홍보"):
        if word in value:
            score += 3
    return score


def crawl_official(http: Http, start_url: str, company: str, max_pages: int = 90) -> Tuple[List[Page], List[Tuple[str, str, str]]]:
    first = http.get(start_url)
    if not first or first.status_code >= 400:
        return [], []
    root = first.url
    allowed_hosts = {_host(start_url), _host(root)} - {""}
    seeds: List[str] = [root]
    domain = _host(root)
    for terms in (
        f'"{company}" 지속가능 보고서', f'"{company}" ESG 보고서',
        f'"{company}" 상호 변경', f'"{company}" 사업장 주소',
    ):
        seeds.extend(search_official_domain_links(http, domain, terms))
    q: deque[Tuple[int, str]] = deque((100, u) for u in _dedupe(seeds))
    seen: set[str] = set()
    pages: List[Page] = []
    linked: List[Tuple[str, str, str]] = []  # source page, text, target

    while q and len(pages) < max_pages:
        # Small queue: selecting highest priority keeps report/company pages ahead of generic menus.
        best_i = max(range(len(q)), key=lambda i: q[i][0])
        prio, url = q[best_i]
        del q[best_i]
        url = url.split("#")[0]
        if url in seen or _host(url) not in allowed_hosts:
            continue
        seen.add(url)
        r = first if url == root and not pages else http.get(url)
        if not r or r.status_code >= 400:
            continue
        ctype = (r.headers.get("content-type") or "").casefold()
        if "html" not in ctype and not r.text.lstrip().startswith("<"):
            continue
        html = r.text
        text = _soup_text(html)
        pages.append(Page(r.url, text, html, r.status_code))
        soup = BeautifulSoup(html, "html.parser")
        outgoing: List[Tuple[int, str]] = []
        for a in soup.find_all("a", href=True):
            label = " ".join(a.stripped_strings).strip()
            target = urljoin(r.url, a["href"]).split("#")[0]
            scheme = urlparse(target).scheme
            if scheme not in {"http", "https"}:
                continue
            linked.append((r.url, label, target))
            if _host(target) in allowed_hosts and target not in seen:
                p = _priority(label, target)
                # Avoid crawling low-value assets and infinite calendars/query permutations.
                if not re.search(r"\.(?:jpg|jpeg|png|gif|svg|css|js|zip|hwp|xlsx?|docx?|pptx?)(?:\?|$)", target, re.I):
                    outgoing.append((p, target))
        for item in sorted(outgoing, reverse=True)[:80]:
            q.append(item)
    return pages, linked


def verify_pdf(http: Http, url: str, source_locator: str) -> Tuple[bool, str, str]:
    headers = {"Range": "bytes=0-15", "Referer": source_locator or url}
    r = http.get(url, headers=headers, stream=True)
    if not r or r.status_code >= 400:
        return False, "", ""
    try:
        head = next(r.iter_content(chunk_size=16), b"")
    except Exception:
        head = b""
    finally:
        r.close()
    ctype = (r.headers.get("content-type") or "").casefold()
    is_pdf = head.startswith(b"%PDF") or "application/pdf" in ctype
    return is_pdf, r.url, ctype


def _year_from(value: str) -> Optional[int]:
    years = [int(x) for x in re.findall(r"(?<!\d)(20\d{2})(?!\d)", value or "")]
    years = [x for x in years if 2000 <= x <= datetime.now(KST).year + 1]
    return years[0] if years else None


def discover_documents(http: Http, official_root: str, pages: Sequence[Page], links: Sequence[Tuple[str, str, str]], start_year: int, current_year: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    official_hosts = {_host(official_root)}
    report_index_pages: List[str] = []
    for page in pages:
        ptext = page.text.casefold()
        if sum(1 for w in REPORT_WORDS if w in ptext) >= 2 and len(re.findall(r"20\d{2}", ptext)) >= 2:
            report_index_pages.append(page.url)
    for source, label, target in links:
        value = (label + " " + target).casefold()
        year = _year_from(label + " " + target)
        if not year or year < start_year - 2 or year > current_year + 1:
            continue
        reportish = any(w in value for w in REPORT_WORDS)
        downloadable = bool(re.search(r"\.pdf(?:\?|$)", target, re.I) or "download" in target.casefold())
        if not (reportish or downloadable):
            continue
        is_pdf, final_url, ctype = verify_pdf(http, target, source)
        if not is_pdf:
            continue
        score = 0
        if any(w in value for w in ("지속가능", "sustainability", "esg")):
            score += 20
        if any(w in value for w in ("통합보고", "integrated report")):
            score += 15
        if "kor" in value or "국문" in value or "korean" in value:
            score += 5
        if re.search(r"\.pdf(?:\?|$)", final_url or target, re.I):
            score += 4
        if source in report_index_pages:
            score += 4
        candidates.append({
            "year": year, "label": label.strip() or f"{year} official report", "url": final_url or target,
            "source_locator": source, "score": score, "content_type": ctype,
        })

    best: Dict[int, Dict[str, Any]] = {}
    for c in candidates:
        if c["year"] not in best or c["score"] > best[c["year"]]["score"]:
            best[c["year"]] = c
    documents: List[Dict[str, Any]] = []
    for year in sorted(best):
        c = best[year]
        documents.append({
            "document_id": f"AUTO_SUSTAINABILITY_{year}",
            "document_type": "SUSTAINABILITY_REPORT",
            "title": c["label"],
            "report_year": year,
            "source_url": c["url"],
            "source_locator": c["source_locator"],
            "expected_extension": "pdf",
            "verification_status": "SOURCE_VERIFIED",
            "importance": "CORE",
            "notes": "Automatically discovered from a DART-anchored official-company page and verified as PDF by response bytes/content-type.",
        })

    # Current environment/HSE pages are supporting evidence, not annual series.
    seen_policy: set[str] = set()
    for page in pages:
        value = (page.url + " " + page.text[:2500]).casefold()
        if not any(w in value for w in POLICY_WORDS):
            continue
        if page.url in seen_policy:
            continue
        seen_policy.add(page.url)
        documents.append({
            "document_id": "AUTO_ENVIRONMENT_PAGE_" + hashlib.sha1(page.url.encode()).hexdigest()[:10],
            "document_type": "ENVIRONMENTAL_MANAGEMENT",
            "title": next((x for x in page.text.split(" ") if x), "Official environmental management page")[:120],
            "report_year": current_year,
            "source_url": page.url,
            "source_locator": page.url,
            "expected_extension": "html",
            "verification_status": "SOURCE_VERIFIED",
            "importance": "SUPPORTING",
        })
        if len(seen_policy) >= 4:
            break

    gaps: List[Dict[str, Any]] = []
    years_found = {int(d["report_year"]) for d in documents if d["document_type"] == "SUSTAINABILITY_REPORT" and d.get("report_year")}
    for year in range(start_year, current_year + 1):
        if year in years_found:
            continue
        if year == current_year and report_index_pages and max(years_found or {0}) == current_year - 1:
            gaps.append({
                "gap_id": f"AUTO_SUSTAINABILITY_{year}_NOT_LISTED",
                "source_key": "CORP_DOCS", "document_type": "SUSTAINABILITY_REPORT", "year": year,
                "verification_status": "SOURCE_VERIFIED", "status": "NOT_PUBLISHED", "severity": "LOW", "blocking": False,
                "reason": f"As of {datetime.now(KST).date().isoformat()}, verified official report index pages list reports through {current_year - 1}, not {current_year}.",
                "source_locator": report_index_pages[0],
            })
        else:
            gaps.append({
                "gap_id": f"AUTO_SUSTAINABILITY_{year}_UNRESOLVED",
                "source_key": "CORP_DOCS", "document_type": "SUSTAINABILITY_REPORT", "year": year,
                "verification_status": "UNVERIFIED", "status": "DISCOVERY_GAP", "severity": "MEDIUM", "blocking": True,
                "reason": "No verified annual report file was discovered within the bounded official-site crawl.",
                "source_locator": report_index_pages[0] if report_index_pages else official_root,
            })
    status = "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE" if not any(g.get("blocking") for g in gaps) else "PARTIAL"
    return {
        "schema_version": "1.0", "discovery_status": status, "documents": documents, "gaps": gaps,
        "discovery_scope": {
            "history_window": {"start_year": start_year, "end_year": current_year},
            "annual_series": ["SUSTAINABILITY_REPORT"],
            "current_public_document_categories": ["SUSTAINABILITY_REPORT", "ENVIRONMENTAL_MANAGEMENT"],
            "scope_note": "Automatically discovered only from the DART-anchored official-company web boundary; off-domain files are accepted only when linked by an official page.",
        },
    }, {"report_index_pages": report_index_pages, "report_candidates": candidates}


PROVINCES = "서울|부산|대구|인천|광주|대전|울산|세종|경기|경기도|강원|강원도|충북|충청북도|충남|충청남도|전북|전라북도|전남|전라남도|경북|경상북도|경남|경상남도|제주|제주도"
ADDRESS_RE = re.compile(rf"((?:{PROVINCES})\s+[가-힣0-9]+(?:시|군|구)?\s+(?:[가-힣0-9]+(?:읍|면|동|구)\s+)?[가-힣0-9·.\-]+(?:로|길|대로)\s*\d+(?:[-~]\d+)?)")


def discover_site_candidates(company: str, pages: Sequence[Page], dart: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    hits: Dict[str, Dict[str, Any]] = {}
    for page in pages:
        value = page.text
        page_signal = sum(1 for w in SITE_WORDS if w in (page.url + " " + value[:4000]).casefold())
        if page_signal == 0:
            continue
        for m in ADDRESS_RE.finditer(value):
            raw = re.sub(r"\s+", " ", m.group(1)).strip()
            key = re.sub(r"[^0-9가-힣]+", "", raw)
            entry = hits.setdefault(key, {"address": raw, "count": 0, "score": 0, "pages": []})
            entry["count"] += 1
            entry["score"] += page_signal
            entry["pages"].append(page.url)
    if dart.get("address"):
        raw = dart["address"].strip()
        key = re.sub(r"[^0-9가-힣]+", "", raw)
        entry = hits.setdefault(key, {"address": raw, "count": 0, "score": 0, "pages": []})
        entry["count"] += 2; entry["score"] += 10; entry["pages"].append(dart["source_url"])

    ranked = sorted(hits.values(), key=lambda x: (x["score"], x["count"]), reverse=True)
    verified = [x for x in ranked if x["score"] >= 5 and (x["count"] >= 2 or dart["source_url"] in x["pages"])]
    sites: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    if verified and (len(verified) == 1 or verified[0]["score"] >= verified[1]["score"] + 5):
        top = verified[0]
        cid = _slug(company + " " + top["address"])
        sites.append({
            "candidate_id": cid, "site_name_raw": f"{company} 주요 사업장", "address_raw": top["address"],
            "business_unit_raw": "official-site primary location", "source_locator": top["pages"][0],
            "identity_status": "VERIFIED", "verification_state": "VERIFIED",
        })
        scope = {
            "mode": "SITE_SET", "label": f"{company} 주요 사업장", "candidate_ids": [cid],
            "raw_collection_policy": "PRESERVE_COMPANY_WIDE", "archive_policy": "FILTER_TO_REQUESTED_SCOPE", "analysis_policy": "FILTER_TO_REQUESTED_SCOPE",
        }
    else:
        scope = {"mode": "COMPANY", "label": company, "raw_collection_policy": "PRESERVE_COMPANY_WIDE", "archive_policy": "FILTER_TO_REQUESTED_SCOPE", "analysis_policy": "FILTER_TO_REQUESTED_SCOPE"}
        unresolved.append({
            "code": "SITE_SCOPE_NOT_UNIQUELY_RESOLVED", "subject": company,
            "detail": "Company identity is verified, but a single primary domestic site was not independently resolved from official pages. Company-wide scope is preserved; no site is guessed.",
            "source_locator": dart.get("source_url"),
        })
    return sites, scope, unresolved


def _extract_rename_date_and_names(pages: Sequence[Page], current_name: str, known_history: Sequence[str]) -> Optional[Dict[str, Any]]:
    current_norm = normalize_name(current_name)
    history = [x for x in known_history if normalize_name(x) and normalize_name(x) != current_norm]
    for page in pages:
        text = page.text
        if not any(w in text for w in ("상호", "사명", "회사명", "명칭")) or "변경" not in text:
            continue
        if current_norm not in normalize_name(text):
            continue
        date_patterns = [
            r"(20\d{2})[.년\-\s]+(\d{1,2})[.월\-\s]+(\d{1,2})일?",
            r"(20\d{2})-(\d{1,2})-(\d{1,2})",
        ]
        date = None
        for pat in date_patterns:
            m = re.search(pat, text)
            if m:
                try:
                    date = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                    break
                except Exception:
                    pass
        predecessor = next((h for h in history if normalize_name(h) in normalize_name(text)), None)
        if date and predecessor:
            return {"date": date, "predecessor": predecessor, "source_locator": page.url}
    return None


def build_collection_policy(current_year: int, start_year: int) -> Dict[str, Any]:
    # Platform disclosure calendars, not company-specific assumptions. The collectors
    # still determine DATA_FOUND/NO_DATA per company and completeness remains explicit.
    return {
        "minimum_history_years": 5,
        "requested_history_window": {"start_year": start_year, "end_year": current_year},
        "sources": {
            "ENVINFO": {"requested_window": {"start_year": start_year, "end_year": min(current_year, 2024)}, "prefer_full_history": False, "max_details": 500},
            "PRTR": {"requested_window": {"start_year": start_year, "end_year": min(current_year, 2024)}, "prefer_full_history": False},
            "CHEM_STATS": {"requested_survey_rounds": [y for y in (2020, 2022, 2024) if start_year <= y <= current_year], "available_survey_rounds": [y for y in (2020, 2022, 2024) if start_year <= y <= current_year], "prefer_full_history": True},
            "CLEANSYS_AIR": {"requested_window": {"start_year": start_year, "end_year": min(current_year, 2025)}, "prefer_full_history": False},
            "SOOSIRO_WATER": {"requested_window": {"start_year": start_year, "end_year": min(current_year, 2025)}, "daily_available_years": [2024] if start_year <= 2024 <= current_year else [], "prefer_full_history": False},
        },
    }


def _request_id(company: str, now: datetime) -> str:
    return f"{_slug(company)}-env-g0-{now.strftime('%Y%m%d')}"


def discover(company: str, start_year: int = 2020, max_pages: int = 90) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    now = datetime.now(KST)
    current_year = now.year
    http = Http()
    audit: Dict[str, Any] = {"schema_version": "g0-audit-1.0", "requested_company_name": company, "started_at": now.isoformat(), "stages": {}}

    legal, legal_candidates = resolve_legal_identity(http, company)
    audit["stages"]["legal_identity"] = {"candidates": legal_candidates, "resolved": legal}
    if not legal:
        discovery = {
            "schema_version": "1.0", "request_id": _request_id(company, now), "requested_company_name": company,
            "current_legal_name": company, "company_verification_state": "REVIEW_REQUIRED", "confidence": "LOW",
            "company_aliases": [], "historical_legal_names": [], "corporate_restructuring_evidence": [],
            "domestic_site_candidates": [], "identity_evidence": [], "related_entity_exclusions": [],
            "requested_scope": {"mode": "COMPANY", "label": company},
            "unresolved_items": [{"code": "LEGAL_ENTITY_NOT_UNIQUELY_RESOLVED", "subject": company, "detail": "Public DART candidate discovery did not yield one uniquely verified legal entity."}],
            "event_evidence_references": [], "collection_policy": build_collection_policy(current_year, start_year),
        }
        docs = {"schema_version": "1.0", "request_id": discovery["request_id"], "discovery_status": "NOT_RUN", "documents": [], "gaps": []}
        audit["gate_status"] = "REVIEW_REQUIRED"; audit["http_attempts"] = http.audit
        return discovery, docs, audit

    official_start = _official_url(legal.get("website"))
    pages: List[Page] = []
    links: List[Tuple[str, str, str]] = []
    if official_start:
        pages, links = crawl_official(http, official_start, company, max_pages=max_pages)
    audit["stages"]["official_site"] = {"dart_website": legal.get("website"), "pages_crawled": len(pages), "links_seen": len(links), "sample_pages": [p.url for p in pages[:30]]}

    dart_history = discover_dart_name_history(http, legal["select_key"])
    rename = _extract_rename_date_and_names(pages, legal["korean_name"], dart_history)
    audit["stages"]["name_history"] = {"dart_history": dart_history, "bounded_rename": rename}

    aliases: List[Dict[str, Any]] = [{"name": company, "alias_type": "requested_name", "verification_state": "VERIFIED", "source_locator": legal["source_url"]}]
    if legal.get("english_name"):
        aliases.append({"name": legal["english_name"], "alias_type": "english_legal_name", "verification_state": "VERIFIED", "source_locator": legal["source_url"]})
    historical: List[Dict[str, Any]] = []
    restructuring: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    entity_start_year = None
    if legal.get("establishment_date"):
        m = re.search(r"(19\d{2}|20\d{2})", legal["establishment_date"])
        entity_start_year = int(m.group(1)) if m else None
    current_period: Dict[str, Any] = {"start_year": entity_start_year} if entity_start_year else {}

    history_clean = [x for x in dart_history if normalize_name(x) not in {normalize_name(legal["korean_name"]), normalize_name(company)}]
    if history_clean:
        if rename:
            rename_year = int(rename["date"][:4])
            current_period = {"start_year": rename_year}
            for old in history_clean:
                historical.append({
                    "name": old, "alias_type": "former_legal_name",
                    "active_period": {"start_year": start_year, "end_year": rename_year},
                    "verification_state": "VERIFIED", "source_locator": rename["source_locator"],
                })
            restructuring.append({
                "event_type": "rename", "effective_period": {"start_year": rename_year, "end_year": rename_year},
                "effective_date": rename["date"], "predecessor": rename["predecessor"], "successor": legal["korean_name"],
                "verification_state": "VERIFIED", "source_locator": rename["source_locator"],
            })
        else:
            for old in history_clean:
                historical.append({"name": old, "alias_type": "former_legal_name", "verification_state": "SOURCE_VERIFIED", "source_locator": DART + "/corp/historyFmlNm.ax?" + urlencode({"selectKey": legal["select_key"]})})
            unresolved.append({
                "code": "HISTORICAL_NAME_PERIOD_UNRESOLVED", "subject": " | ".join(history_clean),
                "detail": "DART confirms prior company names, but the bounded official-site crawl did not independently verify the rename effective date. Historical aliases are preserved but must not be searched unbounded.",
                "source_locator": DART + "/corp/historyFmlNm.ax?" + urlencode({"selectKey": legal["select_key"]}),
            })

    sites, requested_scope, site_unresolved = discover_site_candidates(company, pages, legal)
    unresolved.extend(site_unresolved)
    audit["stages"]["site_scope"] = {"sites": sites, "requested_scope": requested_scope, "unresolved": site_unresolved}

    docs, doc_audit = discover_documents(http, official_start, pages, links, start_year, current_year) if pages else (
        {"schema_version": "1.0", "discovery_status": "PARTIAL", "documents": [], "gaps": [{"gap_id": "OFFICIAL_SITE_UNRESOLVED", "status": "DISCOVERY_GAP", "blocking": True}]},
        {"report_index_pages": [], "report_candidates": []},
    )
    docs["request_id"] = _request_id(company, now)
    audit["stages"]["corporate_documents"] = doc_audit
    blocking_doc_gaps = [g for g in docs.get("gaps", []) if g.get("blocking")]
    if blocking_doc_gaps:
        unresolved.append({"code": "CORPORATE_DOCUMENT_COVERAGE_INCOMPLETE", "subject": company, "detail": f"{len(blocking_doc_gaps)} annual report coverage gap(s) remain after official-site discovery.", "source_locator": official_start})

    identity_evidence = [{
        "source_locator": legal["source_url"],
        "source_value_raw": f"{legal.get('korean_name')} / {legal.get('english_name')} / establishment {legal.get('establishment_date')} / website {legal.get('website')}",
        "verification_state": "VERIFIED", "confidence": "HIGH",
    }]
    discovery = {
        "schema_version": "1.0", "request_id": docs["request_id"], "requested_company_name": company,
        "current_legal_name": legal["korean_name"], "current_legal_name_active_period": current_period,
        "company_verification_state": "VERIFIED", "confidence": "HIGH", "requested_scope": requested_scope,
        "company_aliases": _dedupe(aliases), "historical_legal_names": historical,
        "corporate_restructuring_evidence": restructuring, "domestic_site_candidates": sites,
        "identity_evidence": identity_evidence, "related_entity_exclusions": [], "unresolved_items": unresolved,
        "event_evidence_references": [], "collection_policy": build_collection_policy(current_year, start_year),
    }

    # G0 promotion is deliberately stricter than schema validity. A legally verified
    # company can still stop at REVIEW_REQUIRED when historical continuity, site scope,
    # or annual report coverage is unresolved.
    audit["gate_status"] = "PASS" if not unresolved else "REVIEW_REQUIRED"
    audit["http_attempts"] = http.audit
    audit["finished_at"] = datetime.now(KST).isoformat()
    return discovery, docs, audit


def main() -> int:
    p = argparse.ArgumentParser(description="Company-name-only Discovery producer")
    p.add_argument("--input", default="requests/zero_touch_request.json")
    p.add_argument("--company-name", default="")
    p.add_argument("--out-dir", default="generated-discovery")
    p.add_argument("--start-year", type=int, default=2020)
    p.add_argument("--max-pages", type=int, default=90)
    args = p.parse_args()
    company = args.company_name.strip()
    if not company:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        company = str(payload.get("company_name") or "").strip()
    if not company:
        raise DiscoveryError("company_name is required")
    out = Path(args.out_dir)
    discovery, docs, audit = discover(company, start_year=args.start_year, max_pages=args.max_pages)
    _write_json(out / "company_discovery.json", discovery)
    _write_json(out / "document_evidence.json", docs)
    _write_json(out / "event_evidence.json", {"schema_version": "1.0", "request_id": discovery["request_id"], "discovery_status": "NOT_RUN", "events": []})
    _write_json(out / "Discovery_Audit.json", audit)
    result = {
        "company": company, "request_id": discovery["request_id"], "current_legal_name": discovery["current_legal_name"],
        "company_verification_state": discovery.get("company_verification_state"), "gate_status": audit["gate_status"],
        "unresolved_count": len(discovery.get("unresolved_items", [])), "document_count": len(docs.get("documents", [])),
        "output_dir": str(out),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if audit["gate_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
