"""Preserve stronger verified document delivery routes across zero-touch promotions.

Fresh Discovery owns document identity and coverage.  This module only carries forward
previously verified transport routes for the *same verified legal entity* and the same
(document_type, report_year) semantic document.  It fails closed on entity ambiguity.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from orchestrator.zero_touch_discovery import normalize_name

VERIFICATION_RANK = {
    "UNVERIFIED": 0,
    "PARTIAL": 1,
    "SOURCE_VERIFIED": 2,
    "VERIFIED": 3,
}
STRONG_STATES = {"SOURCE_VERIFIED", "VERIFIED"}


def _dart_keys(discovery: Dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for item in discovery.get("identity_evidence", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("verification_state") or "") not in STRONG_STATES:
            continue
        locator = str(item.get("source_locator") or "")
        for pattern in (r"selectKey=(\d{6,12})", r"selectKey%3D(\d{6,12})"):
            keys.update(re.findall(pattern, locator, re.I))
    return keys


def same_verified_entity(existing: Dict[str, Any], fresh: Dict[str, Any]) -> bool:
    old_name = normalize_name(existing.get("current_legal_name") or existing.get("requested_company_name"))
    new_name = normalize_name(fresh.get("current_legal_name") or fresh.get("requested_company_name"))
    if not old_name or old_name != new_name:
        return False
    old_keys = _dart_keys(existing)
    new_keys = _dart_keys(fresh)
    return bool(old_keys and new_keys and old_keys.intersection(new_keys))


def _year(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _semantic_key(doc: Dict[str, Any]) -> Tuple[str, Optional[int]]:
    return str(doc.get("document_type") or ""), _year(doc.get("report_year"))


def _route(source: Dict[str, Any], role: str) -> Optional[Dict[str, Any]]:
    url = str(source.get("source_url") or "").strip()
    state = str(source.get("verification_status") or "")
    if not url.startswith(("http://", "https://")) or state not in STRONG_STATES:
        return None
    out: Dict[str, Any] = {
        "source_url": url,
        "verification_status": state,
        "source_role": role,
    }
    for key in ("source_locator", "expected_extension", "notes"):
        if source.get(key) is not None:
            out[key] = source.get(key)
    return out


def _dedupe_routes(routes: Iterable[Optional[Dict[str, Any]]], exclude_url: str = "") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = {exclude_url} if exclude_url else set()
    for item in routes:
        if not item:
            continue
        url = str(item.get("source_url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)
    return out


def merge_document_routes(
    existing_company: Dict[str, Any],
    existing_documents: Dict[str, Any],
    fresh_company: Dict[str, Any],
    fresh_documents: Dict[str, Any],
) -> Dict[str, Any]:
    """Return fresh document evidence with safe prior routes carried forward."""
    merged = copy.deepcopy(fresh_documents)
    if not same_verified_entity(existing_company, fresh_company):
        return merged

    old_by_key: Dict[Tuple[str, Optional[int]], Dict[str, Any]] = {}
    for old in existing_documents.get("documents", []) or []:
        if not isinstance(old, dict):
            continue
        key = _semantic_key(old)
        if key[0] and key[1] is not None:
            old_by_key[key] = old

    for fresh in merged.get("documents", []) or []:
        if not isinstance(fresh, dict):
            continue
        old = old_by_key.get(_semantic_key(fresh))
        if not old:
            continue

        old_primary = _route(old, "PREVIOUS_VERIFIED_PRIMARY")
        fresh_primary = _route(fresh, "FRESH_DISCOVERY_PRIMARY")
        old_rank = VERIFICATION_RANK.get(str(old.get("verification_status") or ""), 0)
        fresh_rank = VERIFICATION_RANK.get(str(fresh.get("verification_status") or ""), 0)

        old_fallbacks = [
            _route(x, "PREVIOUS_VERIFIED_FALLBACK")
            for x in (old.get("fallback_sources", []) or [])
            if isinstance(x, dict)
        ]
        fresh_fallbacks = [
            _route(x, str(x.get("source_role") or "FRESH_DISCOVERY_FALLBACK"))
            for x in (fresh.get("fallback_sources", []) or [])
            if isinstance(x, dict)
        ]

        # A previously byte/transport-VERIFIED primary must not be silently replaced by
        # a newly source-verified route.  Equal-strength fresh routes remain primary.
        if old_primary and old_rank > fresh_rank:
            previous_fresh = fresh_primary
            for key in ("source_url", "source_locator", "expected_extension", "verification_status"):
                if key in old:
                    fresh[key] = old.get(key)
                else:
                    fresh.pop(key, None)
            fresh["fallback_sources"] = _dedupe_routes(
                [previous_fresh, *fresh_fallbacks, *old_fallbacks],
                exclude_url=str(fresh.get("source_url") or ""),
            )
            fresh["route_merge_status"] = "PRESERVED_STRONGER_PREVIOUS_PRIMARY"
        else:
            fresh["fallback_sources"] = _dedupe_routes(
                [*fresh_fallbacks, old_primary, *old_fallbacks],
                exclude_url=str(fresh.get("source_url") or ""),
            )
            fresh["route_merge_status"] = "PRESERVED_PREVIOUS_ALTERNATES"

    return merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--existing-company", required=True)
    parser.add_argument("--existing-documents", required=True)
    parser.add_argument("--fresh-company", required=True)
    parser.add_argument("--fresh-documents", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    def load(path: str) -> Dict[str, Any]:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    result = merge_document_routes(
        load(args.existing_company),
        load(args.existing_documents),
        load(args.fresh_company),
        load(args.fresh_documents),
    )
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
