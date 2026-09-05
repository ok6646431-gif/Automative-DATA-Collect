"""Enforce issuer identity and representation semantics for annual report coverage.

A same-group or same-domain report is not automatically a report of the requested legal
entity. Likewise, a highlight/brief PDF is supporting material rather than a full annual
report. Modern issuers can also publish an annual report as a verified first-party digital
report without a monolithic PDF. This layer handles those cases without company-specific
URLs or names.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set, Tuple
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from orchestrator import zero_touch_discovery as base

REPORT_MARKERS = (
    "지속가능경영보고서", "지속가능경영 보고서", "지속가능 보고서", "기업시민보고서",
    "통합보고서", "통합 보고서", "sustainability report", "sustainability_report",
    "sustainability-report", "integrated report", "esg report",
)
SUMMARY_TOKENS = ("하이라이트", "highlight", "요약", "summary", "brief", "브리프")
GENERIC_PREFIX_TOKENS = {
    "annual", "esg", "corporate", "citizenship", "report", "reports", "sustainability",
    "integrated", "kor", "eng", "kr", "en", "korean", "english",
}


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _identity_cores(discovery: Dict[str, Any]) -> Set[str]:
    names = [
        discovery.get("requested_company_name"),
        discovery.get("current_legal_name"),
    ]
    for alias in discovery.get("company_aliases", []) or []:
        if isinstance(alias, dict) and alias.get("alias_type") != "former_legal_name":
            names.append(alias.get("name"))
    return {base.normalize_name(x) for x in names if base.normalize_name(x)}


def _clean_issuer_prefix(prefix: str) -> str:
    text = unquote(str(prefix or "")).replace("_", " ").replace("-", " ")
    text = re.sub(r"(?<!\d)(?:19|20)\d{2}(?!\d)", " ", text)
    text = re.sub(r"\b(?:kor|eng|kr|en|korean|english)\b", " ", text, flags=re.I)
    tokens = [x for x in re.split(r"\s+", text.strip()) if x]
    while tokens and tokens[0].casefold() in GENERIC_PREFIX_TOKENS:
        tokens.pop(0)
    while tokens and tokens[-1].casefold() in GENERIC_PREFIX_TOKENS:
        tokens.pop()
    return base.normalize_name(" ".join(tokens))


def _explicit_issuer(value: str) -> str:
    raw = unquote(str(value or ""))
    if "://" in raw:
        raw = urlparse(raw).path.rsplit("/", 1)[-1]
    folded = raw.casefold()
    positions: List[Tuple[int, str]] = []
    for marker in REPORT_MARKERS:
        idx = folded.find(marker.casefold())
        if idx >= 0:
            positions.append((idx, marker))
    if not positions:
        return ""
    idx, _ = min(positions, key=lambda x: x[0])
    prefix = raw[:idx]
    prefix = re.split(r"[|/\\:]+", prefix)[-1]
    core = _clean_issuer_prefix(prefix)
    # A year/language-only prefix is not an issuer statement.
    return core if len(core) >= 2 else ""


def entity_alignment(discovery: Dict[str, Any], title: str, url: str) -> Tuple[str, List[str]]:
    identities = _identity_cores(discovery)
    issuers = _dedupe([_explicit_issuer(title), _explicit_issuer(url)])
    issuers = [x for x in issuers if x]
    if any(issuer in identities for issuer in issuers):
        return "ALIGNED", issuers
    if issuers:
        return "CONFLICT", issuers
    return "UNKNOWN", []


def is_summary_representation(title: str, url: str) -> bool:
    value = unquote(f"{title} {url}").casefold()
    return any(token.casefold() in value for token in SUMMARY_TOKENS)


def _digital_report_entries(
    text: str,
    locator: str,
    discovery: Dict[str, Any],
    start_year: int,
    end_year: int,
) -> Dict[int, Dict[str, Any]]:
    flattened = re.sub(r"\s+", " ", str(text or ""))
    marker_pattern = "|".join(re.escape(x) for x in sorted(REPORT_MARKERS, key=len, reverse=True))
    pattern = re.compile(
        rf"(?<!\d)(?P<year>20\d{{2}})(?!\d)(?:\s*년)?(?P<middle>.{{0,55}}?)(?P<marker>{marker_pattern})",
        re.I,
    )
    entries: Dict[int, Dict[str, Any]] = {}
    identities = _identity_cores(discovery)
    page_norm = base.normalize_name(flattened)
    page_identity_signal = any(identity and identity in page_norm for identity in identities)
    for match in pattern.finditer(flattened):
        year = int(match.group("year"))
        if year < start_year or year > end_year:
            continue
        phrase = match.group(0)
        status, issuers = entity_alignment(discovery, phrase, "")
        if status == "CONFLICT":
            continue
        if status == "UNKNOWN" and not page_identity_signal:
            continue
        entries.setdefault(year, {
            "document_id": f"AUTO_SUSTAINABILITY_DIGITAL_{year}",
            "document_type": "SUSTAINABILITY_REPORT",
            "title": phrase.strip(),
            "report_year": year,
            "source_url": locator,
            "source_locator": locator,
            "expected_extension": "html",
            "verification_status": "SOURCE_VERIFIED",
            "importance": "CORE",
            "representation": "DIGITAL_REPORT",
            "entity_alignment": status,
            "notes": (
                "Verified first-party annual report published in digital/HTML form; "
                "accepted for annual coverage without inventing a PDF."
            ),
        })
    return entries


def normalize(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    policy = discovery.get("collection_policy") or {}
    window = policy.get("requested_history_window") or {}
    start_year = int(window.get("start_year") or 2020)
    end_year = int(window.get("end_year") or start_year)

    supporting: List[Dict[str, Any]] = []
    annual: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    demoted: List[Dict[str, Any]] = []
    for doc in documents.get("documents", []) or []:
        if doc.get("document_type") != "SUSTAINABILITY_REPORT":
            supporting.append(doc)
            continue
        title = str(doc.get("title") or "")
        url = str(doc.get("source_url") or "")
        alignment, issuers = entity_alignment(discovery, title, url)
        if alignment == "CONFLICT":
            rejected.append({
                "document_id": doc.get("document_id"),
                "report_year": doc.get("report_year"),
                "title": title,
                "source_url": url,
                "explicit_issuers": issuers,
                "reason": "EXPLICIT_REPORT_ISSUER_DOES_NOT_MATCH_REQUESTED_LEGAL_ENTITY",
            })
            continue
        if is_summary_representation(title, url):
            item = dict(doc)
            item["document_type"] = "SUSTAINABILITY_REPORT_SUMMARY"
            item["importance"] = "SUPPORTING"
            item["coverage_role"] = "SUPPORTING_SUMMARY_ONLY"
            supporting.append(item)
            demoted.append({
                "document_id": doc.get("document_id"), "report_year": doc.get("report_year"),
                "reason": "SUMMARY_OR_HIGHLIGHT_DOES_NOT_SATISFY_FULL_ANNUAL_REPORT_COVERAGE",
            })
            continue
        item = dict(doc)
        item["entity_alignment"] = alignment
        annual.append(item)

    strict_stage = (audit.get("stages") or {}).get("strict_report_enrichment") or {}
    trusted_starts = _dedupe(strict_stage.get("trusted_secondary_starts") or [])[:6]
    http = base.Http(timeout=(5, 15))
    digital: Dict[int, Dict[str, Any]] = {}
    catalog_diagnostics: List[Dict[str, Any]] = []
    for locator in trusted_starts:
        r = http.get(locator)
        if not r or r.status_code >= 400:
            catalog_diagnostics.append({"locator": locator, "status": "UNREACHABLE"})
            continue
        ctype = str(r.headers.get("content-type") or "").casefold()
        if "html" not in ctype and not str(r.text or "").lstrip().startswith("<"):
            continue
        text = " ".join(BeautifulSoup(r.text, "html.parser").stripped_strings)
        found = _digital_report_entries(text, r.url, discovery, start_year, end_year)
        catalog_diagnostics.append({"locator": r.url, "digital_years": sorted(found)})
        for year, item in found.items():
            digital.setdefault(year, item)

    annual_by_year: Dict[int, Dict[str, Any]] = {}
    for doc in annual:
        try:
            year = int(doc.get("report_year"))
        except (TypeError, ValueError):
            continue
        annual_by_year.setdefault(year, doc)
    for year, doc in digital.items():
        annual_by_year.setdefault(year, doc)

    found_years = set(annual_by_year)
    old_annual_gaps: Dict[int, Dict[str, Any]] = {}
    other_gaps: List[Dict[str, Any]] = []
    for gap in documents.get("gaps", []) or []:
        if gap.get("document_type") != "SUSTAINABILITY_REPORT":
            other_gaps.append(gap)
            continue
        try:
            old_annual_gaps[int(gap.get("year"))] = gap
        except (TypeError, ValueError):
            other_gaps.append(gap)

    annual_gaps: List[Dict[str, Any]] = []
    for year in range(start_year, end_year + 1):
        if year in found_years:
            continue
        existing = old_annual_gaps.get(year)
        if existing:
            annual_gaps.append(existing)
        else:
            annual_gaps.append({
                "gap_id": f"AUTO_SUSTAINABILITY_{year}_UNRESOLVED",
                "source_key": "CORP_DOCS",
                "document_type": "SUSTAINABILITY_REPORT",
                "year": year,
                "verification_status": "UNVERIFIED",
                "status": "DISCOVERY_GAP",
                "severity": "MEDIUM",
                "blocking": True,
                "reason": "No entity-aligned full annual report or verified digital annual report was resolved.",
                "source_locator": trusted_starts[0] if trusted_starts else None,
            })

    documents["documents"] = [*supporting, *[annual_by_year[y] for y in sorted(annual_by_year)]]
    documents["gaps"] = [*other_gaps, *annual_gaps]
    documents["discovery_status"] = (
        "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE"
        if not any(g.get("blocking") for g in documents["gaps"])
        else "PARTIAL"
    )
    audit.setdefault("stages", {})["report_entity_representation_policy"] = {
        "rejected_entity_mismatch": rejected,
        "demoted_summary_documents": demoted,
        "trusted_catalogs_checked": catalog_diagnostics,
        "digital_annual_years": sorted(digital),
        "annual_years_after_policy": sorted(annual_by_year),
    }
    audit.setdefault("http_attempts", []).extend(http.audit)
    return documents
