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


def evaluate(output_root: str | Path, request_path: str | Path) -> dict:
    output = Path(output_root)
    request = read_json(request_path, {}) or {}
    configured = list((request.get("sources") or {}).keys())
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
            if status.get("tls_verification") is False:
                warnings.append(issue(
                    source,
                    "TLS_VERIFICATION_FALLBACK_USED",
                    str(status.get("tls_verification_exception") or ""),
                    severity="WARNING",
                ))
        elif source == "SOOSIRO_WATER":
            issues.extend(_validate_soosiro_no_data(status))

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
            "A name/address discovery miss remains DISCOVERY_UNRESOLVED and blocks a COMPLETE collection claim.",
            "Any failed selected-period query blocks collection acceptance even if other periods returned data.",
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
