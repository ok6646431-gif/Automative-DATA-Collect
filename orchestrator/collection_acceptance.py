#!/usr/bin/env python3
"""Strict collection-only acceptance gate.

This module intentionally stops before package analysis, Human Archive, and application
materials.  Its only question is whether every requested source was queried with enough
source-native evidence to trust either DATA_FOUND or a confirmed empty result.

A name search that returns no facility identity is not NO_DATA_CONFIRMED.  For
facility-indexed TMS sources, an empty result is accepted only after a source-native
facility ID has been independently discovered and queried successfully.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .collection_completeness import INCOMPLETE_STATES, public_rows
except ImportError:
    from collection_completeness import INCOMPLETE_STATES, public_rows


BLOCKING_SOURCE_STATUSES = {
    "REQUEST_OR_PARSE_FAILED",
    "PARTIAL_FAILURE",
    "REMOTE_HOST_UNREACHABLE",
    "CONFIG_ERROR",
    "COLLECTION_FAILED_RETRY_EXHAUSTED",
    "INVALID_SCOPE",
    "NOT_RUN",
}
TMS_SOURCES = {"CLEANSYS_AIR", "SOOSIRO_WATER"}


def read_json(path: str | Path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def issue(source: str, issue_type: str, detail: str, *, severity: str = "BLOCKING"):
    return {
        "source": source,
        "issue_type": issue_type,
        "severity": severity,
        "detail": detail,
    }


def _validate_cleansys_no_data(status: dict) -> list[dict]:
    if str(status.get("status") or "") != "NO_DATA_CONFIRMED":
        return []
    candidates = int(status.get("candidate_count") or 0)
    attempts = int(status.get("candidate_query_attempts") or 0)
    successes = int(status.get("candidate_query_success") or 0)
    if candidates <= 0 or attempts <= 0 or attempts != successes:
        return [issue(
            "CLEANSYS_AIR",
            "UNSUPPORTED_NO_DATA_CONFIRMATION",
            f"candidate_count={candidates}; candidate_query_attempts={attempts}; candidate_query_success={successes}",
        )]
    return []


def _validate_soosiro_no_data(status: dict) -> list[dict]:
    if str(status.get("status") or "") != "NO_DATA_CONFIRMED":
        return []
    fact_codes = int(status.get("fact_codes") or 0)
    address_seeded = [str(x) for x in status.get("address_seeded_fact_codes") or [] if str(x)]
    fact_list_ok = status.get("fact_list_query_success") is True
    if fact_codes <= 0 or not address_seeded or not fact_list_ok:
        return [issue(
            "SOOSIRO_WATER",
            "UNSUPPORTED_NO_DATA_CONFIRMATION",
            f"fact_codes={fact_codes}; address_seeded_fact_codes={len(address_seeded)}; fact_list_query_success={fact_list_ok}",
        )]
    return []


def _validate_registry_miss(source: str, status: dict) -> list[dict]:
    if str(status.get("status") or "") != "NO_FACILITY_MATCH_CONFIRMED":
        return []
    if status.get("registry_scan_complete") is not True:
        return [issue(source, "UNSUPPORTED_REGISTRY_MISS", "registry_scan_complete is not true")]
    if source == "CLEANSYS_AIR":
        count = int(status.get("index_selectable_option_count") or 0)
        if count <= 0:
            return [issue(source, "UNSUPPORTED_REGISTRY_MISS", f"index_selectable_option_count={count}")]
    if source == "SOOSIRO_WATER":
        count = int(status.get("fact_list_rows") or 0)
        fact_list_ok = status.get("fact_list_query_success") is True
        term_success = int(status.get("annual_term_requests_success") or 0)
        if count <= 0 or not fact_list_ok or term_success <= 0:
            return [issue(
                source,
                "UNSUPPORTED_REGISTRY_MISS",
                f"fact_list_rows={count}; fact_list_query_success={fact_list_ok}; annual_term_requests_success={term_success}",
            )]
    return []


def evaluate(output_root: str | Path, request_path: str | Path) -> dict:
    output = Path(output_root)
    request = read_json(request_path, {}) or {}
    configured = list((request.get("sources") or {}).keys())
    if (output / "CORP_DOCS" / "status.json").exists() and "CORP_DOCS" not in configured:
        configured.append("CORP_DOCS")
    rows = public_rows(output, request)

    issues: list[dict] = []
    warnings: list[dict] = []
    source_results = {}

    for source in configured:
        status_path = output / source / "status.json"
        status = read_json(status_path, None)
        if not isinstance(status, dict):
            issues.append(issue(source, "MISSING_STATUS", str(status_path)))
            source_results[source] = {"status": "MISSING_STATUS"}
            continue

        source_status = str(status.get("status") or "MISSING_STATUS")
        source_results[source] = status

        if source_status in BLOCKING_SOURCE_STATUSES:
            issues.append(issue(source, source_status, "collector reported a blocking collection state"))
        elif source_status == "DISCOVERY_UNRESOLVED":
            issues.append(issue(
                source,
                "SOURCE_ID_DISCOVERY_UNRESOLVED",
                "source was reachable but no source-native facility identity was established; do not convert this to no-data",
            ))

        if source == "CLEANSYS_AIR":
            issues.extend(_validate_cleansys_no_data(status))
            issues.extend(_validate_registry_miss(source, status))
            if status.get("tls_verification") is False:
                warnings.append(issue(
                    source,
                    "TLS_VERIFICATION_FALLBACK_USED",
                    str(status.get("tls_verification_exception") or ""),
                    severity="WARNING",
                ))
        elif source == "SOOSIRO_WATER":
            issues.extend(_validate_soosiro_no_data(status))
            issues.extend(_validate_registry_miss(source, status))
        elif source == "CORP_DOCS":
            discovery_status = str(status.get("discovery_status") or "").upper()
            if discovery_status not in {
                "COMPLETE",
                "VERIFIED_COMPLETE",
                "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE",
            }:
                issues.append(issue(
                    source,
                    "DOCUMENT_DISCOVERY_INCOMPLETE",
                    f"discovery_status={discovery_status or 'MISSING'}",
                ))
            declared = int(status.get("documents_declared") or 0)
            downloaded = int(status.get("downloaded") or 0)
            failed = int(status.get("failed") or 0)
            skipped = int(status.get("skipped") or 0)
            if failed or declared != downloaded + skipped:
                issues.append(issue(
                    source,
                    "DOCUMENT_COLLECTION_INCOMPLETE",
                    f"declared={declared}; downloaded={downloaded}; skipped={skipped}; failed={failed}",
                ))

    for item in rows:
        state = str(item.get("completeness_state") or "")
        if state in INCOMPLETE_STATES:
            issues.append(issue(
                str(item.get("source") or ""),
                state,
                f"{item.get('period_kind')}:{item.get('period')} | {item.get('evidence','')}",
            ))

    # De-duplicate deterministic issue records.
    unique = {}
    for item in issues:
        key = (item["source"], item["issue_type"], item["detail"])
        unique[key] = item
    issues = list(unique.values())

    result = {
        "schema_version": "collection-acceptance-1.0",
        "status": "PASS" if not issues else "REVIEW_REQUIRED",
        "configured_sources": configured,
        "source_results": {
            source: {
                "status": str((source_results.get(source) or {}).get("status") or "MISSING_STATUS"),
                "rows": (source_results.get(source) or {}).get(
                    "rows", (source_results.get(source) or {}).get("annual_rows", "")
                ),
                "errors": (source_results.get(source) or {}).get("errors", ""),
            }
            for source in configured
        },
        "blocking_issue_count": len(issues),
        "warning_count": len(warnings),
        "blocking_issues": issues,
        "warnings": warnings,
        "period_audit": rows,
        "principles": [
            "Source execution success is not the same as collection acceptance.",
            "Facility-indexed TMS no-data requires a source-native facility ID and a successful ID-bound query.",
            "A discovery miss is resolved only when the source-native public facility registry was completely scanned and the selected-period query evidence is retained.",
            "Any failed selected-period query blocks collection acceptance even if other periods returned data.",
            "Declared official corporate documents must be fully downloaded or explicitly skipped under a complete discovery scope.",
        ],
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="output")
    parser.add_argument("--request", default="requests/current.generated.json")
    parser.add_argument("--summary-out", default="Collection_Acceptance.json")
    args = parser.parse_args()

    result = evaluate(args.output_root, args.request)
    Path(args.summary_out).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
