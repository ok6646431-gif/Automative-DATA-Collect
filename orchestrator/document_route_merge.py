"""Preserve verified document delivery routes across zero-touch promotions.

Fresh Discovery owns document identity and coverage. Previously verified transport
routes are carried forward only for the same DART-anchored legal entity. A persistent
DART-keyed registry is consulted before the immediately previous current-company files,
so switching companies cannot erase accepted routes.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from orchestrator.zero_touch_discovery import normalize_name

VERIFICATION_RANK = {"UNVERIFIED": 0, "PARTIAL": 1, "SOURCE_VERIFIED": 2, "VERIFIED": 3}
STRONG_STATES = {"SOURCE_VERIFIED", "VERIFIED"}
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "requests" / "verified_document_routes.json"


def dart_keys(discovery: Dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for item in discovery.get("identity_evidence", []) or []:
        if not isinstance(item, dict) or str(item.get("verification_state") or "") not in STRONG_STATES:
            continue
        locator = str(item.get("source_locator") or "")
        for pattern in (r"selectKey=(\d{6,12})", r"selectKey%3D(\d{6,12})"):
            keys.update(re.findall(pattern, locator, re.I))
    return keys


_dart_keys = dart_keys


def same_verified_entity(existing: Dict[str, Any], fresh: Dict[str, Any]) -> bool:
    old_name = normalize_name(existing.get("current_legal_name") or existing.get("requested_company_name"))
    new_name = normalize_name(fresh.get("current_legal_name") or fresh.get("requested_company_name"))
    if not old_name or old_name != new_name:
        return False
    old_keys, new_keys = dart_keys(existing), dart_keys(fresh)
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
    out: Dict[str, Any] = {"source_url": url, "verification_status": state, "source_role": role}
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


def _blocking_gap_keys(documents: Dict[str, Any]) -> set[Tuple[str, Optional[int]]]:
    keys: set[Tuple[str, Optional[int]]] = set()
    for gap in documents.get("gaps", []) or []:
        if not isinstance(gap, dict) or not gap.get("blocking"):
            continue
        key = (str(gap.get("document_type") or ""), _year(gap.get("year")))
        if key[0] and key[1] is not None:
            keys.add(key)
    return keys


def _recompute_discovery_status(documents: Dict[str, Any]) -> None:
    documents["discovery_status"] = (
        "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE"
        if not any(isinstance(g, dict) and g.get("blocking") for g in documents.get("gaps", []) or [])
        else "PARTIAL"
    )


def _registry_entry(fresh_company: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Load only the exactly matching verified DART entity from persistent memory."""
    keys = sorted(dart_keys(fresh_company))
    if len(keys) != 1 or not REGISTRY_PATH.exists():
        return None
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        entry = (registry.get("entities") or {}).get(keys[0])
        if not isinstance(entry, dict):
            return None
        if not same_verified_entity(entry.get("company") or {}, fresh_company):
            return None
        return entry
    except Exception:
        return None


def merge_document_routes(
    existing_company: Dict[str, Any],
    existing_documents: Dict[str, Any],
    fresh_company: Dict[str, Any],
    fresh_documents: Dict[str, Any],
    _skip_registry: bool = False,
) -> Dict[str, Any]:
    """Return fresh evidence with safe prior routes carried forward.

    The persistent registry is applied first. The immediately previous current-company
    evidence is then applied if it is the same verified entity. A prior document can be
    restored only when fresh Discovery contains an exact matching blocking gap.
    """
    merged = copy.deepcopy(fresh_documents)

    if not _skip_registry:
        entry = _registry_entry(fresh_company)
        if entry:
            merged = merge_document_routes(
                entry.get("company") or {}, entry.get("document_evidence") or {},
                fresh_company, merged, _skip_registry=True,
            )

    if not same_verified_entity(existing_company, fresh_company):
        return merged

    old_by_key: Dict[Tuple[str, Optional[int]], Dict[str, Any]] = {}
    for old in existing_documents.get("documents", []) or []:
        if not isinstance(old, dict):
            continue
        key = _semantic_key(old)
        if not key[0] or key[1] is None:
            continue
        previous = old_by_key.get(key)
        if previous is None or VERIFICATION_RANK.get(str(old.get("verification_status") or ""), 0) > VERIFICATION_RANK.get(str(previous.get("verification_status") or ""), 0):
            old_by_key[key] = old

    fresh_keys: set[Tuple[str, Optional[int]]] = set()
    for fresh in merged.get("documents", []) or []:
        if not isinstance(fresh, dict):
            continue
        key = _semantic_key(fresh)
        if key[0] and key[1] is not None:
            fresh_keys.add(key)
        old = old_by_key.get(key)
        if not old:
            continue

        old_primary = _route(old, "PREVIOUS_VERIFIED_PRIMARY")
        fresh_primary = _route(fresh, "FRESH_DISCOVERY_PRIMARY")
        old_rank = VERIFICATION_RANK.get(str(old.get("verification_status") or ""), 0)
        fresh_rank = VERIFICATION_RANK.get(str(fresh.get("verification_status") or ""), 0)
        old_fallbacks = [_route(x, "PREVIOUS_VERIFIED_FALLBACK") for x in (old.get("fallback_sources", []) or []) if isinstance(x, dict)]
        fresh_fallbacks = [_route(x, str(x.get("source_role") or "FRESH_DISCOVERY_FALLBACK")) for x in (fresh.get("fallback_sources", []) or []) if isinstance(x, dict)]

        if old_primary and old_rank > fresh_rank:
            previous_fresh = fresh_primary
            for field in ("source_url", "source_locator", "expected_extension", "verification_status"):
                if field in old:
                    fresh[field] = old.get(field)
                else:
                    fresh.pop(field, None)
            fresh["fallback_sources"] = _dedupe_routes([previous_fresh, *fresh_fallbacks, *old_fallbacks], exclude_url=str(fresh.get("source_url") or ""))
            fresh["route_merge_status"] = "PRESERVED_STRONGER_PREVIOUS_PRIMARY"
        else:
            fresh["fallback_sources"] = _dedupe_routes([*fresh_fallbacks, old_primary, *old_fallbacks], exclude_url=str(fresh.get("source_url") or ""))
            fresh["route_merge_status"] = "PRESERVED_PREVIOUS_ALTERNATES"

    gap_keys = _blocking_gap_keys(merged)
    restored_keys: set[Tuple[str, Optional[int]]] = set()
    for key, old in old_by_key.items():
        if key in fresh_keys or key not in gap_keys or _route(old, "PREVIOUS_VERIFIED_PRIMARY") is None:
            continue
        restored = copy.deepcopy(old)
        restored["route_merge_status"] = "RESTORED_PREVIOUS_VERIFIED_DOCUMENT"
        merged.setdefault("documents", []).append(restored)
        restored_keys.add(key)

    if restored_keys:
        merged["gaps"] = [
            gap for gap in (merged.get("gaps", []) or [])
            if not (
                isinstance(gap, dict) and gap.get("blocking")
                and (str(gap.get("document_type") or ""), _year(gap.get("year"))) in restored_keys
            )
        ]
        _recompute_discovery_status(merged)

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

    result = merge_document_routes(load(args.existing_company), load(args.existing_documents), load(args.fresh_company), load(args.fresh_documents))
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
