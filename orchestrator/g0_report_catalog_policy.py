"""Interpret verified official report catalogs without inventing annual publications.

A requested history window is a collection target, not a claim that every issuer
published one sustainability report every year. When one verified first-party catalog
explicitly exposes report years on both sides of a missing year and the missing year is
absent from that catalog, preserve the absence as SOURCE_VERIFIED/NOT_PUBLISHED rather
than treating it as a collector failure.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Set
from urllib.parse import urlparse

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


def normalize_verified_catalog_gaps(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    """Downgrade only source-verified interior catalog holes to NOT_PUBLISHED."""
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
        # corroborate at least two already byte-verified report records from that page.
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
