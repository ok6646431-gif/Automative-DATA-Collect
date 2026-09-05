"""Normalize annual-document coverage to the verified current legal-entity lifetime.

A user can request history before the current corporation legally existed. Those years
may still be useful as predecessor history, but they are not missing annual reports of
the current entity unless corporate continuity has been independently verified. This
module removes only the false *blocking* coverage obligation; it never invents or
silently promotes predecessor documents.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


def _year(value: Any) -> int | None:
    m = re.search(r"(?:19|20)\d{2}", str(value or ""))
    return int(m.group(0)) if m else None


def _legal_start_year(discovery: Dict[str, Any], audit: Dict[str, Any]) -> int | None:
    period = discovery.get("legal_entity_active_period") or {}
    value = period.get("start_year") if isinstance(period, dict) else None
    if value:
        try:
            return int(value)
        except Exception:
            pass
    legal = (((audit.get("stages") or {}).get("legal_identity") or {}).get("resolved") or {})
    return _year(legal.get("establishment_date"))


def normalize(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    policy = discovery.get("collection_policy") or {}
    requested = policy.get("requested_history_window") or {}
    requested_start = int(requested.get("start_year") or 2020)
    requested_end = int(requested.get("end_year") or requested_start)
    legal_start = _legal_start_year(discovery, audit)

    if legal_start:
        discovery["legal_entity_active_period"] = {"start_year": legal_start}
    effective_start = max(requested_start, legal_start or requested_start)

    removed_gaps: List[Dict[str, Any]] = []
    kept_gaps: List[Dict[str, Any]] = []
    for gap in documents.get("gaps", []) or []:
        year = gap.get("year")
        is_annual = gap.get("document_type") == "SUSTAINABILITY_REPORT"
        if is_annual and isinstance(year, int) and year < effective_start:
            removed_gaps.append(gap)
            continue
        kept_gaps.append(gap)
    documents["gaps"] = kept_gaps

    pre_entity_documents: List[str] = []
    for doc in documents.get("documents", []) or []:
        if doc.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        year = doc.get("report_year")
        if isinstance(year, int) and year < effective_start:
            doc["coverage_role"] = "PRE_ENTITY_HISTORICAL_REFERENCE"
            note = str(doc.get("notes") or "").strip()
            marker = (
                f"Report year predates the verified current legal-entity start "
                f"({effective_start}); preserved as historical reference only."
            )
            doc["notes"] = (note + " " + marker).strip()
            if doc.get("document_id"):
                pre_entity_documents.append(str(doc["document_id"]))

    documents.setdefault("discovery_scope", {})["requested_history_window"] = {
        "start_year": requested_start,
        "end_year": requested_end,
    }
    documents["discovery_scope"]["effective_current_entity_history_window"] = {
        "start_year": effective_start,
        "end_year": requested_end,
    }
    documents["discovery_status"] = (
        "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE"
        if not any(g.get("blocking") for g in kept_gaps)
        else "PARTIAL"
    )

    audit.setdefault("stages", {})["legal_entity_document_window"] = {
        "requested_start_year": requested_start,
        "requested_end_year": requested_end,
        "verified_legal_entity_start_year": legal_start,
        "effective_current_entity_start_year": effective_start,
        "removed_pre_entity_blocking_gap_years": sorted({
            int(g["year"]) for g in removed_gaps if isinstance(g.get("year"), int)
        }),
        "pre_entity_documents_preserved_as_history": pre_entity_documents,
        "policy": (
            "Pre-establishment years are not blocking annual-report gaps for the current "
            "legal entity. Predecessor coverage requires separate verified continuity."
        ),
    }
    return documents
