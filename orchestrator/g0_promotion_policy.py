"""Classify G0 review items into promotion-blocking and downstream review-only issues.

Identity, scope, and legal-entity ambiguity must remain fail-closed. In contrast, a
verified company discovery should not be kept stale merely because one public document
in the requested history window has not yet been resolved. Document completeness is
already represented explicitly in document_evidence.gaps and can continue downstream as
REVIEW_REQUIRED without blocking promotion of newer verified identity/site evidence.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import re


NONBLOCKING_PROMOTION_CODES = {
    "CORPORATE_DOCUMENT_COVERAGE_INCOMPLETE",
}


def _requested_start_year(discovery: Dict[str, Any]) -> int | None:
    window = ((discovery.get("collection_policy") or {}).get("requested_history_window") or {})
    try:
        return int(window.get("start_year")) if window.get("start_year") is not None else None
    except (TypeError, ValueError):
        return None


def _historical_name_issue_is_pre_window(
    item: Dict[str, Any], discovery: Dict[str, Any], audit: Dict[str, Any]
) -> bool:
    if str(item.get("code") or "") != "HISTORICAL_LEGAL_NAME_PREDECESSOR_UNRESOLVED":
        return False
    requested_start = _requested_start_year(discovery)
    if requested_start is None:
        return False
    recovery = (((audit.get("stages") or {}).get("official_site") or {}).get("recovery") or {})
    signals = [x for x in recovery.get("rename_signals") or [] if isinstance(x, dict)]
    if not signals:
        return False
    years = []
    for signal in signals:
        value = signal.get("year")
        match = re.search(r"(?:19|20)\d{2}", str(value or ""))
        if not match:
            return False
        years.append(int(match.group(0)))
    return bool(years) and max(years) < requested_start


def apply(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    blocking = []
    deferred = []
    for item in discovery.get("unresolved_items", []) or []:
        code = str(item.get("code") or "")
        if code in NONBLOCKING_PROMOTION_CODES or _historical_name_issue_is_pre_window(item, discovery, audit):
            deferred.append(item)
        else:
            blocking.append(item)

    discovery["unresolved_items"] = blocking
    audit.setdefault("stages", {})["promotion_policy"] = {
        "blocking_unresolved_items": blocking,
        "deferred_review_items": deferred,
        "deferred_review_count": len(deferred),
        "document_blocking_gap_count": sum(
            1 for g in documents.get("gaps", []) or [] if g.get("blocking")
        ),
        "policy": (
            "Verified current-entity discovery may be promoted with explicit document "
            "coverage gaps and historical-name ambiguity proven to predate the requested "
            "history window; current-window identity/scope/legal ambiguity remains fail-closed."
        ),
    }
    audit["gate_status"] = "PASS" if not blocking else "REVIEW_REQUIRED"
    return discovery, documents, audit
