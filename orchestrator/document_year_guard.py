"""Fail-closed helpers for explicit year evidence in document delivery routes.

A discovery adapter may infer an annual-report year from DOM context while a concrete
PDF/download URL independently carries a different year.  The concrete route is not
sufficient to prove the intended report year, but an explicit conflicting year is
strong negative evidence.  These helpers are deliberately company-agnostic and are
shared by route preservation and final arbitration.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
STRONG_STATES = {"SOURCE_VERIFIED", "VERIFIED"}


def _year(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def explicit_route_years(url: str) -> List[int]:
    """Return explicit 20xx years carried by the concrete route path/query."""
    try:
        parsed = urlparse(str(url or ""))
        evidence = unquote((parsed.path.rsplit("/", 1)[-1] or "") + "?" + (parsed.query or ""))
    except Exception:
        evidence = str(url or "")
    return sorted({int(m.group(1)) for m in YEAR_RE.finditer(evidence)})


def route_year_conflicts(source: Dict[str, Any], report_year: Any) -> bool:
    """True only when a route explicitly carries year evidence excluding report_year."""
    year = _year(report_year)
    if year is None:
        return False
    years = explicit_route_years(str(source.get("source_url") or ""))
    return bool(years and year not in years)


def strong_route_matches_year(source: Dict[str, Any], report_year: Any) -> bool:
    """Require strong verification and positive explicit route-year agreement."""
    year = _year(report_year)
    if year is None:
        return False
    if str(source.get("verification_status") or "") not in STRONG_STATES:
        return False
    years = explicit_route_years(str(source.get("source_url") or ""))
    return bool(years and year in years)
