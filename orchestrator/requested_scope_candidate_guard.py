"""Fail-closed guard for requested SITE_SET candidates that never bind to Site_Master.

A verified requested location must not silently disappear merely because other requested
locations were successfully mapped. Raw collection remains company-wide, but archive
completeness is blocked until every requested candidate is either bound to a canonical
site or explicitly resolved by an evidence-backed scope policy.

Co-located first-party organizational units need special care. Two official units can
share one road address without being the same legal environmental facility. Therefore
this module never merges their identities by address. It can, however, resolve the
*collection boundary only* when a sibling canonical site is already directly inside the
requested scope, at least two independent address-bearing public sources corroborate
that same reporting anchor, and no source-native row separately names the unresolved
unit. The relationship stays explicit and auditable as COLLECTION_ONLY.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import scope_quality as base
import requested_scope as requested
from requested_scope import resolve_requested_scope

STATE = "REQUESTED_SCOPE_CANDIDATE_UNRESOLVED"
RELATION = "COLOCATED_PUBLIC_REPORTING_SCOPE"
STRONG_IDENTITY = {"CONFIRMED", "VERIFIED", "SOURCE_VERIFIED"}


def unresolved_candidate_rows(scope: Dict[str, Any]) -> List[Dict[str, str]]:
    if str(scope.get("mode") or "").upper() != "SITE_SET":
        return []
    rows: List[Dict[str, str]] = []
    for item in scope.get("unresolved_candidates", []) or []:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "").strip()
        name = str(item.get("site_name_raw") or "").strip()
        address = str(item.get("address_raw") or "").strip()
        reason = str(item.get("reason") or "UNRESOLVED").strip()
        period = candidate_id or name or address or "UNKNOWN_REQUESTED_SITE"
        rows.append({
            "source": "REQUEST_SCOPE",
            "period_kind": "SITE_CANDIDATE",
            "period": period,
            "expected": "Y",
            "query_state": "UNRESOLVED_BINDING",
            "data_present": "N",
            "completeness_state": STATE,
            "evidence": (
                f"candidate_id={candidate_id}; site_name={name}; address={address}; reason={reason}"
            ),
            "user_note": (
                "공식적으로 확인된 요청 거점이 통합 Site_Master의 canonical site에 연결되지 않았음. "
                "다른 요청 거점이 연결되었다는 이유로 이 거점을 요청범위에서 자동 제외하지 않음"
            ),
        })
    return rows


def _official_candidates_at_address(profile: Dict[str, Any], address_key: str) -> List[Dict[str, Any]]:
    out = []
    for item in profile.get("site_candidates", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("verification_state") or "").upper() not in requested.STRONG_VERIFICATION:
            continue
        identity = str(item.get("identity_status") or "").upper()
        if identity and identity not in STRONG_IDENTITY:
            continue
        if requested.normalize_address(item.get("address_raw")) == address_key:
            out.append(item)
    return out


def _collection_relation_for_candidate(
    package: Path,
    profile: Dict[str, Any],
    scope: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any] | None:
    """Return a collection-only relationship without asserting site identity.

    This deliberately requires a canonical sibling that is *already* in requested
    scope. The policy may explain coverage for an unresolved co-located sibling, but
    it may never expand a request to a new canonical site by address alone.
    """
    if str(candidate.get("reason") or "") != "COLOCATED_OFFICIAL_UNIT_NOT_DISTINCTLY_CONFIRMED":
        return None

    candidate_id = str(candidate.get("candidate_id") or "")
    profile_candidate = next(
        (
            x for x in profile.get("site_candidates", []) or []
            if isinstance(x, dict) and str(x.get("candidate_id") or "") == candidate_id
        ),
        None,
    )
    if not profile_candidate:
        return None
    if str(profile_candidate.get("verification_state") or "").upper() not in requested.STRONG_VERIFICATION:
        return None
    identity = str(profile_candidate.get("identity_status") or "").upper()
    if identity and identity not in STRONG_IDENTITY:
        return None

    address_key = requested.normalize_address(profile_candidate.get("address_raw"))
    if not address_key:
        return None
    official_units = _official_candidates_at_address(profile, address_key)
    if len(official_units) < 2:
        return None

    target_canonical = {str(x) for x in scope.get("target_canonical_site_ids", set()) if str(x)}
    sites = base.read_csv(package / "Site_Master.csv")
    identities = base.read_csv(package / "Source_Identity.csv")
    canonical_at_address = [
        row for row in sites
        if str(row.get("identity_status") or "").upper() == "CONFIRMED"
        and str(row.get("canonical_site_id") or "") in target_canonical
        and requested.normalize_address(row.get("canonical_address_key")) == address_key
    ]
    if len(canonical_at_address) != 1:
        return None
    canonical = canonical_at_address[0]
    canonical_id = str(canonical.get("canonical_site_id") or "")

    # The public reporting anchor must directly name another verified official unit at
    # this address. A generic company-only canonical label is not enough.
    sibling_names = [
        unit.get("site_name_raw")
        for unit in official_units
        if str(unit.get("candidate_id") or "") != candidate_id
    ]
    if not any(
        requested._site_name_match(name, canonical.get("canonical_site_name"), profile)
        for name in sibling_names
    ):
        return None

    corroborating_sources = set()
    for row in identities:
        if str(row.get("canonical_site_id") or "") != canonical_id:
            continue
        if str(row.get("match_status") or "").upper() != "CONFIRMED":
            continue
        source = str(row.get("source_key") or "")
        if source not in requested.CORE_SOURCES:
            continue
        # Address-bearing evidence is required. Addressless name-only TMS rows cannot
        # establish a shared physical reporting boundary.
        if requested.normalize_address(row.get("source_address_raw")) != address_key:
            continue
        entity_ok, _ = requested._source_entity_compatible(
            row.get("source_site_name_raw"), profile, official_units
        )
        if entity_ok:
            corroborating_sources.add(source)
    if len(corroborating_sources) < 2:
        return None

    # If any public source actually exposes the unresolved unit by name at this same
    # address, absence cannot be used as a collection-boundary explanation. Keep it
    # unresolved so the distinct source-native identity can be investigated instead.
    for row in identities:
        if str(row.get("source_key") or "") not in requested.CORE_SOURCES:
            continue
        if requested.normalize_address(row.get("source_address_raw")) != address_key:
            continue
        if requested._site_name_match(
            profile_candidate.get("site_name_raw"), row.get("source_site_name_raw"), profile
        ):
            return None

    return {
        "candidate_id": candidate_id,
        "site_name_raw": str(profile_candidate.get("site_name_raw") or candidate.get("site_name_raw") or ""),
        "address_raw": str(profile_candidate.get("address_raw") or candidate.get("address_raw") or ""),
        "relation_type": RELATION,
        "resolution_scope": "COLLECTION_ONLY",
        "identity_merge": False,
        "coverage_canonical_site_id": canonical_id,
        "coverage_canonical_site_name": str(canonical.get("canonical_site_name") or ""),
        "corroborating_source_keys": sorted(corroborating_sources),
        "evidence_rule": (
            "verified co-located official units; sibling canonical already directly in requested scope; "
            ">=2 independent confirmed address-bearing public sources; no distinct source-native row "
            "naming this official unit"
        ),
        "caveat": (
            "Collection-scope resolution only. This does not assert that the two official organizational "
            "units are the same legal environmental facility."
        ),
    }


def resolve_collection_relations(
    package: Path, profile: Dict[str, Any], scope: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    relations: List[Dict[str, Any]] = []
    remaining: List[Dict[str, Any]] = []
    for item in scope.get("unresolved_candidates", []) or []:
        if not isinstance(item, dict):
            continue
        relation = _collection_relation_for_candidate(package, profile, scope, item)
        if relation:
            relations.append(relation)
        else:
            remaining.append(item)
    return relations, remaining


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _persist_requested_scope_relations(
    package: Path,
    relations: List[Dict[str, Any]],
    remaining: List[Dict[str, Any]],
) -> None:
    if not relations:
        return
    path = package / "Requested_Scope.json"
    payload = base.read_json(path, {}) or {}
    payload["schema_version"] = "1.2"
    payload["unresolved_candidates"] = remaining
    existing = [x for x in payload.get("candidate_scope_relations", []) or [] if isinstance(x, dict)]
    by_id = {str(x.get("candidate_id") or ""): x for x in existing if x.get("candidate_id")}
    for relation in relations:
        by_id[str(relation.get("candidate_id") or "")] = relation
    payload["candidate_scope_relations"] = list(by_id.values())
    payload["scope_relation_principle"] = (
        "Collection-only co-location relations can close a requested collection boundary without "
        "merging official organizational-unit identities or asserting legal-facility equivalence."
    )
    _write_json(path, payload)


def audit_collection_for_requested_scope(package_root, profile_path, request_path=None, evidence_path=None):
    """Run normal scope audit, then enforce or explicitly resolve unbound candidates."""
    package = Path(package_root)
    profile = base.read_json(profile_path, {}) or {}
    summary = base.audit_collection_for_requested_scope(
        package_root, profile_path, request_path, evidence_path
    )
    scope = resolve_requested_scope(package, profile)
    relations, remaining = resolve_collection_relations(package, profile, scope)
    effective_scope = dict(scope)
    effective_scope["unresolved_candidates"] = remaining
    effective_scope["candidate_scope_relations"] = relations
    _persist_requested_scope_relations(package, relations, remaining)

    extras = unresolved_candidate_rows(effective_scope)
    if not extras:
        revised = dict(summary or {})
        if relations:
            revised["schema_version"] = "1.4"
            revised["candidate_scope_relations"] = relations
            revised["unresolved_requested_candidates"] = []
            principles = list(revised.get("principles") or [])
            note = (
                "A co-located official unit may be resolved for collection scope only when a directly "
                "requested sibling reporting anchor is corroborated by at least two independent "
                "address-bearing public sources and no distinct source-native row names the unit; "
                "this never merges site identity."
            )
            if note not in principles:
                principles.append(note)
            revised["principles"] = principles
            _write_json(package / "Collection_Completeness.json", revised)
            integration = base.read_json(package / "Integration_Summary.json", {}) or {}
            integration["collection_completeness"] = revised
            _write_json(package / "Integration_Summary.json", integration)
            manifest = base.read_json(package / "Master_Manifest.json", {}) or {}
            manifest["collection_completeness"] = revised
            _write_json(package / "Master_Manifest.json", manifest)
        return revised

    completeness_path = package / "Collection_Completeness.csv"
    rows = base.read_csv(completeness_path)
    existing = {
        (str(x.get("completeness_state") or ""), str(x.get("period") or ""))
        for x in rows
    }
    added = [
        x for x in extras
        if (x["completeness_state"], x["period"]) not in existing
    ]
    if added:
        rows.extend(added)
        base.write_csv(completeness_path, rows)

    no_data = [x for x in rows if x.get("completeness_state") == "NO_DATA_CONFIRMED"]
    outside_entity = [
        x for x in rows if x.get("completeness_state") == "OUTSIDE_CURRENT_ENTITY_PERIOD"
    ]
    warnings = [x for x in rows if x.get("completeness_state") == "RAW_SCOPE_WARNING"]
    incomplete = [
        x for x in rows
        if x.get("completeness_state") in base.INCOMPLETE_STATES
        or x.get("completeness_state") == STATE
    ]
    complete = [
        x for x in rows
        if x.get("completeness_state") in {
            "DATA_PRESENT", "NO_DATA_CONFIRMED", "OUTSIDE_CURRENT_ENTITY_PERIOD"
        }
    ]

    revised = dict(summary or {})
    revised["schema_version"] = "1.4"
    revised["status"] = "REVIEW_REQUIRED" if incomplete else "COMPLETE"
    revised["checked_items"] = len(rows)
    revised["complete_items"] = len(complete)
    revised["incomplete_items"] = len(incomplete)
    revised["warning_items"] = len(warnings)
    revised["no_data_confirmed_items"] = len(no_data)
    revised["outside_current_entity_items"] = len(outside_entity)
    revised["incomplete_keys"] = [
        f"{x.get('source')}:{x.get('period_kind')}:{x.get('period')}:{x.get('completeness_state')}"
        for x in incomplete
    ]
    revised["candidate_scope_relations"] = relations
    revised["unresolved_requested_candidates"] = [
        {
            "candidate_id": str(x.get("candidate_id") or ""),
            "site_name_raw": str(x.get("site_name_raw") or ""),
            "address_raw": str(x.get("address_raw") or ""),
            "reason": str(x.get("reason") or ""),
        }
        for x in remaining
        if isinstance(x, dict)
    ]
    principles = list(revised.get("principles") or [])
    note = (
        "Every verified requested SITE_SET candidate must bind to a canonical site or be explicitly "
        "resolved; successful binding of sibling candidates never permits silent scope loss."
    )
    if note not in principles:
        principles.append(note)
    revised["principles"] = principles
    _write_json(package / "Collection_Completeness.json", revised)

    integration = base.read_json(package / "Integration_Summary.json", {}) or {}
    company_id = str(
        integration.get("company_id")
        or profile.get("company_id")
        or base.stable_id("COMP_", profile.get("company_display_name"))
    )
    validations = [base.validation_for(company_id, x) for x in added]
    if validations:
        review_count = base.merge_validations(package, validations)
    else:
        review_count = len(base.read_json(package / "REVIEW_REQUIRED.json", []) or [])
    integration["collection_completeness"] = revised
    integration["validation_queue"] = len(base.read_csv(package / "Validation_Queue.csv"))
    _write_json(package / "Integration_Summary.json", integration)

    manifest = base.read_json(package / "Master_Manifest.json", {}) or {}
    manifest["collection_completeness"] = revised
    if incomplete and manifest.get("package_health") == "PASS":
        manifest["package_health"] = "DEGRADED"
    manifest["review_count"] = review_count
    manifest["validation"] = "REVIEW_REQUIRED" if review_count else "PASS"
    _write_json(package / "Master_Manifest.json", manifest)
    return revised
