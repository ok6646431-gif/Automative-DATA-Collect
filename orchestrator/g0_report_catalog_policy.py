"""Interpret verified official report catalogs without inventing annual publications.

A requested history window is a collection target, not a claim that every issuer
published one sustainability report every year. A multi-year report catalog is useful
publication evidence, but the catalog page itself is not several annual reports. Only
separate year-specific targets may satisfy annual document coverage.

When one verified first-party catalog explicitly exposes report years on both sides of
a missing year and the missing year is absent from that catalog, preserve the absence
as SOURCE_VERIFIED/NOT_PUBLISHED rather than treating it as a collector failure.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Set
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup

from orchestrator import zero_touch_discovery as base


REPORT_TOKENS = (
    "지속가능경영보고서",
    "지속가능경영 보고서",
    "지속가능 보고서",
    "sustainability report",
    "integrated report",
    "통합보고서",
    "통합 보고서",
    "esg report",
)


def _same_page_locator(value: str) -> str:
    value = str(value or "").strip().split("#", 1)[0]
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return value


def _document_target_key(value: str) -> str:
    """Normalize only fragments when deciding whether two records share one target.

    Query strings are retained because they frequently identify distinct official
    document/viewer resources. A fragment alone cannot turn one fetched page into
    separate annual documents.
    """
    value = str(value or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ""))


def _catalog_supports_nonpublication(year: int, catalog_years: Iterable[int]) -> bool:
    """True only for a bounded interior hole in a sufficiently rich catalog."""
    years = sorted({int(y) for y in catalog_years if y})
    return len(years) >= 3 and year not in years and min(years) < year < max(years)


def _years_from_verified_catalog(http: Any, locator: str) -> Set[int]:
    locator = _same_page_locator(locator)
    if not locator:
        return set()
    r = http.get(locator)
    if not r or r.status_code >= 400:
        return set()
    ctype = str(r.headers.get("content-type") or "").casefold()
    if "html" not in ctype and not str(r.text or "").lstrip().startswith("<"):
        return set()
    soup = BeautifulSoup(r.text, "html.parser")
    text = " ".join(soup.stripped_strings)
    low = text.casefold()
    years: Set[int] = set()
    for match in re.finditer(r"(?<!\d)(20\d{2})(?!\d)", text):
        year = int(match.group(1))
        context = low[max(0, match.start() - 140): min(len(low), match.end() + 180)]
        if any(token in context for token in REPORT_TOKENS):
            years.add(year)
    return years


def _demote_shared_digital_catalogs(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Fail closed when one fetched HTML target is claimed as several annual reports.

    A true multi-year catalog may list many report years. It may support discovery and
    publisher-cadence evidence, but one URL/response target cannot simultaneously be
    the full 2022, 2023, 2024 ... annual report. Distinct year-specific query targets
    are preserved because their normalized target keys differ.
    """
    docs = [d for d in documents.get("documents", []) or [] if isinstance(d, dict)]
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for doc in docs:
        if doc.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        if str(doc.get("representation") or "").upper() != "DIGITAL_REPORT":
            continue
        key = _document_target_key(str(doc.get("source_url") or ""))
        if key:
            groups[key].append(doc)

    invalid_groups: Dict[str, List[Dict[str, Any]]] = {}
    for key, values in groups.items():
        years = set()
        for doc in values:
            try:
                years.add(int(doc.get("report_year")))
            except (TypeError, ValueError):
                pass
        if len(years) > 1:
            invalid_groups[key] = values

    if not invalid_groups:
        audit.setdefault("stages", {})["multi_year_catalog_guard"] = {
            "status": "NO_SHARED_MULTI_YEAR_DIGITAL_TARGET",
            "demoted_catalogs": [],
        }
        return []

    invalid_ids = {id(doc) for values in invalid_groups.values() for doc in values}
    kept = [doc for doc in docs if id(doc) not in invalid_ids]
    demoted: List[Dict[str, Any]] = []
    for target, values in sorted(invalid_groups.items()):
        years = sorted({int(d["report_year"]) for d in values if str(d.get("report_year") or "").isdigit()})
        locator = next((str(d.get("source_locator") or "") for d in values if d.get("source_locator")), target)
        digest = hashlib.sha1(target.encode("utf-8")).hexdigest()[:12]
        evidence_id = f"AUTO_SUSTAINABILITY_CATALOG_{digest}"
        if not any(d.get("document_id") == evidence_id for d in kept):
            kept.append({
                "document_id": evidence_id,
                "document_type": "OTHER_OFFICIAL_DOCUMENT",
                "title": "Official sustainability report catalog",
                "report_year": None,
                "source_url": target,
                "source_locator": locator or target,
                "expected_extension": "html",
                "verification_status": "SOURCE_VERIFIED",
                "importance": "EVIDENCE_ONLY",
                "representation": "REPORT_CATALOG",
                "coverage_role": "REPORT_CATALOG_ONLY",
                "catalog_years": years,
                "notes": (
                    "Verified first-party multi-year report catalog. The shared page is "
                    "preserved once as discovery evidence and does not itself satisfy any "
                    "individual annual-report coverage year."
                ),
            })
        demoted.append({
            "source_url": target,
            "source_locator": locator,
            "years": years,
            "removed_document_ids": [str(d.get("document_id") or "") for d in values],
            "reason": "ONE_FETCH_TARGET_CANNOT_BE_MULTIPLE_ANNUAL_DIGITAL_REPORTS",
        })

    documents["documents"] = kept

    # Restore blocking gaps only for years that lost their sole annual-document claim.
    covered_years = set()
    for doc in kept:
        if doc.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        try:
            covered_years.add(int(doc.get("report_year")))
        except (TypeError, ValueError):
            pass
    existing_gap_years = set()
    for gap in documents.get("gaps", []) or []:
        if gap.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        try:
            existing_gap_years.add(int(gap.get("year")))
        except (TypeError, ValueError):
            pass
    for item in demoted:
        for year in item["years"]:
            if year in covered_years or year in existing_gap_years:
                continue
            documents.setdefault("gaps", []).append({
                "gap_id": f"AUTO_SUSTAINABILITY_{year}_TARGET_UNRESOLVED",
                "source_key": "CORP_DOCS",
                "document_type": "SUSTAINABILITY_REPORT",
                "year": year,
                "verification_status": "SOURCE_VERIFIED",
                "status": "PUBLISHED_DOCUMENT_TARGET_UNRESOLVED",
                "severity": "MEDIUM",
                "blocking": True,
                "reason": (
                    "The first-party catalog indicates an annual report for this year, "
                    "but no distinct year-specific document target was verified. The "
                    "catalog page itself is not promoted as the annual report."
                ),
                "source_locator": item.get("source_locator") or item.get("source_url"),
            })
            existing_gap_years.add(year)

    documents["discovery_status"] = (
        "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE"
        if not any(g.get("blocking") for g in documents.get("gaps", []) or [])
        else "PARTIAL"
    )
    audit.setdefault("stages", {})["multi_year_catalog_guard"] = {
        "status": "SHARED_MULTI_YEAR_DIGITAL_TARGET_DEMOTED",
        "demoted_catalogs": demoted,
    }
    return demoted


def normalize_verified_catalog_gaps(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    """Demote shared catalog targets, then resolve only verified nonpublication holes."""
    _demote_shared_digital_catalogs(discovery, documents, audit)

    annual = [
        d for d in documents.get("documents", []) or []
        if d.get("document_type") == "SUSTAINABILITY_REPORT"
        and d.get("verification_status") in {"VERIFIED", "SOURCE_VERIFIED"}
        and d.get("report_year")
    ]
    by_locator: Dict[str, Set[int]] = defaultdict(set)
    for d in annual:
        locator = _same_page_locator(str(d.get("source_locator") or ""))
        if locator:
            by_locator[locator].add(int(d["report_year"]))

    http = base.Http()
    verified_catalogs: Dict[str, List[int]] = {}
    for locator, linked_years in by_locator.items():
        if len(linked_years) < 2:
            continue
        catalog_years = _years_from_verified_catalog(http, locator)
        # The fetched page must independently show several annual report years and must
        # corroborate at least two already byte-verified/distinct annual report records.
        if len(catalog_years) >= 3 and len(catalog_years.intersection(linked_years)) >= 2:
            verified_catalogs[locator] = sorted(catalog_years)

    changed: List[Dict[str, Any]] = []
    for gap in documents.get("gaps", []) or []:
        if gap.get("document_type") != "SUSTAINABILITY_REPORT" or not gap.get("blocking"):
            continue
        try:
            year = int(gap.get("year"))
        except (TypeError, ValueError):
            continue
        for locator, catalog_years in verified_catalogs.items():
            if not _catalog_supports_nonpublication(year, catalog_years):
                continue
            gap.update({
                "gap_id": f"AUTO_SUSTAINABILITY_{year}_NOT_LISTED",
                "verification_status": "SOURCE_VERIFIED",
                "status": "NOT_PUBLISHED",
                "severity": "LOW",
                "blocking": False,
                "reason": (
                    "A verified first-party sustainability-report catalog lists report "
                    f"years on both sides of {year} but does not list a {year} report; "
                    "the gap is preserved as publisher cadence/non-publication rather "
                    "than a collector failure."
                ),
                "source_locator": locator,
            })
            changed.append({"year": year, "source_locator": locator})
            break

    documents["discovery_status"] = (
        "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE"
        if not any(g.get("blocking") for g in documents.get("gaps", []) or [])
        else "PARTIAL"
    )
    audit.setdefault("stages", {})["verified_report_catalog_policy"] = {
        "verified_catalogs": verified_catalogs,
        "nonpublication_gaps": changed,
    }
    audit.setdefault("http_attempts", []).extend(http.audit)
    return documents
