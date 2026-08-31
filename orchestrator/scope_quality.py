"""Requested-scope collection quality gates.

Collectors intentionally preserve company-wide raw evidence.  This module decides a
different question: whether the *user-requested scope* is complete.  A raw failure
outside that scope remains visible as a warning but must not downgrade the requested
site archive.  Study-enrichment references (BAT/guidelines) are tracked separately
from company/public-data collection completeness.
"""

import json
from pathlib import Path

try:
    from .request_builder import build as build_request
    from .requested_scope import resolve_requested_scope
    from .collection_completeness import (
        INCOMPLETE_STATES,
        document_rows,
        public_rows,
        validation_for,
        merge_validations,
        read_json,
        read_csv,
        write_csv,
        stable_id,
    )
except ImportError:
    from request_builder import build as build_request
    from requested_scope import resolve_requested_scope
    from collection_completeness import (
        INCOMPLETE_STATES,
        document_rows,
        public_rows,
        validation_for,
        merge_validations,
        read_json,
        read_csv,
        write_csv,
        stable_id,
    )


def _write_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def scoped_envinfo_attachment_status(package_root, profile=None, scope=None):
    """Return failed ENV-INFO attachments split by requested scope.

    For COMPANY scope every raw failure is blocking. For SITE_SET scope only a failed
    attachment whose source-native compId belongs to the resolved requested site set is
    blocking. Other failures are preserved as company-wide raw warnings.
    """
    root = Path(package_root)
    profile = profile or (read_json(root / "Company_Profile.json", {}) or {})
    scope = scope or resolve_requested_scope(root, profile)
    failed = [
        r for r in read_csv(root / "output" / "ENVINFO" / "attachment_index.csv")
        if str(r.get("collection_status") or "").upper() not in {"", "DOWNLOADED"}
    ]
    mode = str(scope.get("mode") or "COMPANY").upper()
    if mode != "SITE_SET":
        return {
            "mode": mode,
            "raw_failed": failed,
            "scoped_failed": failed,
            "outside_scope_failed": [],
            "target_envinfo_ids": sorted(scope.get("target_source_ids", {}).get("ENVINFO", set())),
        }

    target = {str(x) for x in scope.get("target_source_ids", {}).get("ENVINFO", set())}
    scoped = [r for r in failed if str(r.get("compId") or "") in target]
    outside = [r for r in failed if str(r.get("compId") or "") not in target]
    return {
        "mode": mode,
        "raw_failed": failed,
        "scoped_failed": scoped,
        "outside_scope_failed": outside,
        "target_envinfo_ids": sorted(target),
    }


def _reconcile_envinfo_attachment_row(rows, package_root, profile, scope):
    state = scoped_envinfo_attachment_status(package_root, profile, scope)
    raw_n = len(state["raw_failed"])
    scoped_n = len(state["scoped_failed"])
    outside_n = len(state["outside_scope_failed"])

    for item in rows:
        if (
            item.get("source") == "ENVINFO"
            and item.get("period_kind") == "ARTIFACT"
            and item.get("period") == "ATTACHMENTS"
        ):
            if scoped_n:
                item["completeness_state"] = "ARTIFACT_INCOMPLETE"
                item["query_state"] = "COMPLETE"
                item["data_present"] = "Y"
                item["evidence"] = (
                    f"requested_scope_failed={scoped_n}; company_raw_failed={raw_n}; "
                    f"outside_scope_failed={outside_n}; target_envinfo_ids={len(state['target_envinfo_ids'])}"
                )
                item["user_note"] = "요청한 사업장 범위 안의 ENV-INFO 첨부자료 다운로드 실패가 있음"
            else:
                item["completeness_state"] = "RAW_SCOPE_WARNING"
                item["query_state"] = "COMPLETE_FOR_REQUESTED_SCOPE"
                item["data_present"] = "Y"
                names = sorted({
                    f"{r.get('compNm','')}:{r.get('year','')}:{r.get('original_filename','')}"
                    for r in state["outside_scope_failed"]
                })
                item["evidence"] = (
                    f"requested_scope_failed=0; company_raw_failed={raw_n}; "
                    f"outside_scope_failed={outside_n}; examples={' | '.join(names[:3])}"
                )
                item["user_note"] = (
                    "회사 전체 Raw 수집에는 실패가 남아 있으나 요청한 사업장 범위 밖이므로 "
                    "요청범위 completeness를 저하하지 않음"
                )
            break
    return state


def audit_collection_for_requested_scope(package_root, profile_path, request_path=None, evidence_path=None):
    """Run the completeness gate using the requested site scope as the blocking boundary."""
    package = Path(package_root)
    output = package / "output"
    profile = read_json(profile_path, {}) or {}
    request = (
        read_json(request_path, {})
        if request_path and Path(request_path).exists()
        else build_request(profile)
    ) or {}
    evidence = (
        read_json(evidence_path, {})
        if evidence_path and Path(evidence_path).exists()
        else {}
    ) or {}

    scope = resolve_requested_scope(package, profile)
    rows = public_rows(output, request) + document_rows(package, profile, evidence)
    env_scope = _reconcile_envinfo_attachment_row(rows, package, profile, scope)

    incomplete = [x for x in rows if x.get("completeness_state") in INCOMPLETE_STATES]
    no_data = [x for x in rows if x.get("completeness_state") == "NO_DATA_CONFIRMED"]
    complete = [
        x for x in rows
        if x.get("completeness_state") in {"DATA_PRESENT", "NO_DATA_CONFIRMED"}
    ]
    warnings = [x for x in rows if x.get("completeness_state") == "RAW_SCOPE_WARNING"]

    write_csv(package / "Collection_Completeness.csv", rows)
    write_csv(package / "Collection_No_Data.csv", no_data)
    summary = {
        "schema_version": "1.1",
        "status": "REVIEW_REQUIRED" if incomplete else "COMPLETE",
        "scope_mode": scope.get("mode"),
        "scope_label": scope.get("label"),
        "target_candidate_ids": scope.get("target_candidate_ids", []),
        "target_canonical_site_ids": sorted(scope.get("target_canonical_site_ids", set())),
        "checked_items": len(rows),
        "complete_items": len(complete),
        "incomplete_items": len(incomplete),
        "warning_items": len(warnings),
        "no_data_confirmed_items": len(no_data),
        "incomplete_keys": [
            f"{x['source']}:{x['period_kind']}:{x['period']}:{x['completeness_state']}"
            for x in incomplete
        ],
        "warnings": [
            {
                "source": x.get("source"),
                "period_kind": x.get("period_kind"),
                "period": x.get("period"),
                "state": x.get("completeness_state"),
                "note": x.get("user_note"),
            }
            for x in warnings
        ],
        "no_data_confirmed": [
            {
                "source": x["source"],
                "period_kind": x["period_kind"],
                "period": x["period"],
                "note": x["user_note"],
            }
            for x in no_data
        ],
        "envinfo_attachment_scope": {
            "company_raw_failed": len(env_scope["raw_failed"]),
            "requested_scope_failed": len(env_scope["scoped_failed"]),
            "outside_scope_failed": len(env_scope["outside_scope_failed"]),
        },
        "principles": [
            "Company-wide raw collection is preserved independently from requested-scope completeness.",
            "Only failures inside the resolved requested site set can block a SITE_SET completeness decision.",
            "A successful query with no disclosed row is NO_DATA_CONFIRMED and is reported separately.",
            "Every strongly verified declared official document must have a real delivered file.",
            "Annual official-document series must cover the full requested history window; latest-N is not sufficient.",
        ],
    }
    _write_json(package / "Collection_Completeness.json", summary)

    integration = read_json(package / "Integration_Summary.json", {}) or {}
    company_id = str(
        integration.get("company_id")
        or profile.get("company_id")
        or stable_id("COMP_", profile.get("company_display_name"))
    )
    additions = [validation_for(company_id, x) for x in incomplete]
    review_count = (
        merge_validations(package, additions)
        if additions
        else len(read_json(package / "REVIEW_REQUIRED.json", []) or [])
    )
    integration["collection_completeness"] = summary
    integration["validation_queue"] = len(read_csv(package / "Validation_Queue.csv"))
    _write_json(package / "Integration_Summary.json", integration)

    manifest = read_json(package / "Master_Manifest.json", {}) or {}
    manifest["collection_completeness"] = summary
    if incomplete and manifest.get("package_health") == "PASS":
        manifest["package_health"] = "DEGRADED"
    manifest["review_count"] = review_count
    manifest["validation"] = "REVIEW_REQUIRED" if review_count else "PASS"
    _write_json(package / "Master_Manifest.json", manifest)
    return summary


def is_blocking_document_gap(gap):
    """Treat context/coverage notes separately from unresolved document gaps."""
    if not isinstance(gap, dict):
        return False
    if "blocking" in gap:
        return bool(gap.get("blocking"))
    state = str(
        gap.get("status")
        or gap.get("gap_status")
        or gap.get("resolution")
        or ""
    ).upper()
    if state in {
        "UNRESOLVED", "MISSING", "DISCOVERY_MISSING", "DOWNLOAD_FAILED",
        "QUERY_FAILED", "ACCESS_FAILED",
    }:
        return True
    if state in {"NOT_PUBLISHED", "NO_PUBLIC_DOCUMENT", "NO_DATA_CONFIRMED", "OUT_OF_SCOPE"}:
        return False
    # Legacy gaps without an explicit blocking state were frequently contextual
    # notes (availability timing, site-name matching cautions, non-public SOP scope).
    return False


def document_gap_status(package_root):
    gaps = read_json(Path(package_root) / "output" / "CORP_DOCS" / "discovery_gaps.json", []) or []
    blocking = [g for g in gaps if is_blocking_document_gap(g)]
    context = [g for g in gaps if not is_blocking_document_gap(g)]
    return {
        "total": len(gaps),
        "blocking": blocking,
        "context": context,
        "blocking_count": len(blocking),
        "context_count": len(context),
    }


def classify_archive_summary(package_root, summary):
    """Separate collection completeness from study-enrichment readiness."""
    root = Path(package_root)
    result = dict(summary or {})
    checks = dict(result.get("acceptance_checks") or {})
    collection = read_json(root / "Collection_Completeness.json", {}) or {}

    guideline = bool(checks.get("guideline_reference_present"))
    blocking = {
        key: bool(value)
        for key, value in checks.items()
        if key != "guideline_reference_present"
    }
    blocking["collection_completeness_complete"] = collection.get("status") == "COMPLETE"
    study = {"guideline_reference_present": guideline}

    result["acceptance_checks"] = {**blocking, **study}
    result["blocking_acceptance_checks"] = blocking
    result["study_enrichment_checks"] = study
    result["archive_completeness"] = "COMPLETE" if all(blocking.values()) else "INCOMPLETE"
    result["study_enrichment_readiness"] = "READY" if all(study.values()) else "NEEDS_REFERENCE"
    result["collection_completeness_status"] = collection.get("status", "UNKNOWN")
    result["principle"] = (
        "회사/공공 원자료의 요청범위 완결성과 BAT·가이드라인 같은 학습 보강자료의 준비도를 "
        "분리한다. 학습 보강자료가 없다는 이유만으로 회사 원자료 수집을 INCOMPLETE로 판정하지 않는다."
    )

    archive_root = result.get("archive_root")
    if archive_root:
        manifest = root / "Human_Archive" / archive_root / "00_자료목록" / "Archive_Manifest.json"
        if manifest.parent.exists():
            _write_json(manifest, result)
    _write_json(root / "Archive_Summary.json", result)
    return result
