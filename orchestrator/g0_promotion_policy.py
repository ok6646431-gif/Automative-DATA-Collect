"""Classify G0 review items into promotion-blocking and downstream review-only issues.

Identity, scope, and legal-entity ambiguity must remain fail-closed. In contrast, a
verified company discovery should not be kept stale merely because one public document
in the requested history window has not yet been resolved. Document completeness is
already represented explicitly in document_evidence.gaps and can continue downstream as
REVIEW_REQUIRED without blocking promotion of newer verified identity/site evidence.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple


NONBLOCKING_PROMOTION_CODES = {
    "CORPORATE_DOCUMENT_COVERAGE_INCOMPLETE",
}


def apply(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    blocking = []
    deferred = []
    for item in discovery.get("unresolved_items", []) or []:
        if str(item.get("code") or "") in NONBLOCKING_PROMOTION_CODES:
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
            "Verified identity/site discovery may be promoted with explicit document "
            "coverage gaps; identity/scope/legal ambiguity remains fail-closed."
        ),
    }
    audit["gate_status"] = "PASS" if not blocking else "REVIEW_REQUIRED"
    return discovery, documents, audit
