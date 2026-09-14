"""Fail-closed guard for requested SITE_SET candidates that never bind to Site_Master.

A verified requested location must not silently disappear merely because other requested
locations were successfully mapped. Raw collection remains company-wide, but archive
completeness is blocked until every requested candidate is either bound to a canonical
site or explicitly resolved by a later evidence-backed scope policy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import scope_quality as base
from requested_scope import resolve_requested_scope

STATE = "REQUESTED_SCOPE_CANDIDATE_UNRESOLVED"


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


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def audit_collection_for_requested_scope(package_root, profile_path, request_path=None, evidence_path=None):
    """Run the normal scope audit, then block any silently unbound requested candidate."""
    package = Path(package_root)
    profile = base.read_json(profile_path, {}) or {}
    summary = base.audit_collection_for_requested_scope(
        package_root, profile_path, request_path, evidence_path
    )
    scope = resolve_requested_scope(package, profile)
    extras = unresolved_candidate_rows(scope)
    if not extras:
        return summary

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
    revised["schema_version"] = "1.3"
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
    revised["unresolved_requested_candidates"] = [
        {
            "candidate_id": str(x.get("candidate_id") or ""),
            "site_name_raw": str(x.get("site_name_raw") or ""),
            "address_raw": str(x.get("address_raw") or ""),
            "reason": str(x.get("reason") or ""),
        }
        for x in scope.get("unresolved_candidates", []) or []
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
