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
import csv
import hashlib
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
# A successful process exit with NO_MATCH/RUNNING/unknown status is not accepted.
ACCEPTED_SOURCE_STATUSES = {"DATA_FOUND", "NO_DATA_CONFIRMED"}
ACCEPTED_TMS_STATUSES = ACCEPTED_SOURCE_STATUSES | {"NO_FACILITY_MATCH_CONFIRMED"}
REQUIRED_COLLECTION_SOURCES = (
    "ENVINFO", "PRTR", "CHEM_STATS", "CLEANSYS_AIR", "SOOSIRO_WATER", "CORP_DOCS",
)


def _has_errors(status: dict) -> bool:
    value = status.get("errors", 0)
    if isinstance(value, (list, dict, set, tuple)):
        return bool(value)
    try:
        return int(value or 0) > 0
    except (TypeError, ValueError):
        return bool(value)


def _verified_tms_identity(request: dict, source: str) -> bool:
    gate = ((request.get("sources") or {}).get(source) or {}).get("identity_gate")
    if not isinstance(gate, dict) or gate.get("enabled") is not True:
        return False
    if gate.get("mode") != "VERIFIED_CURRENT_ENTITY_OR_SITE":
        return False
    names = [x for x in gate.get("current_entity_names", []) if str(x).strip()]
    sites = [
        x for x in gate.get("verified_sites", [])
        if isinstance(x, dict) and (str(x.get("site_name") or "").strip() or str(x.get("address") or "").strip())
    ]
    return bool(names and sites)



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


def _validate_corporate_document_files(output_root: Path, status: dict) -> list[dict]:
    """Reconcile declared downloads against actual indexed files and digests.

    Counts in status.json are not sufficient: a file can be absent, truncated,
    duplicated in the index, or replaced after the downloader wrote its status.
    """
    source = "CORP_DOCS"
    root = output_root / source
    index_path = root / "document_index.csv"
    if not index_path.is_file():
        return [issue(source, "DOCUMENT_INDEX_MISSING", str(index_path))]
    with index_path.open(encoding="utf-8-sig", newline="") as stream:
        records = list(csv.DictReader(stream))
    declared = int(status.get("documents_declared") or 0)
    downloaded = int(status.get("downloaded") or 0)
    skipped = int(status.get("skipped") or 0)
    found = [r for r in records if r.get("collection_status") == "DOWNLOADED"]
    issues = []
    if len(records) != declared or len(found) != downloaded:
        issues.append(issue(source, "DOCUMENT_INDEX_COUNT_MISMATCH",
                            f"index_rows={len(records)}/{declared}; downloads={len(found)}/{downloaded}"))
    ids = [str(r.get("document_id") or "") for r in records]
    if not all(ids) or len(set(ids)) != len(ids):
        issues.append(issue(source, "DOCUMENT_INDEX_DUPLICATE_OR_MISSING_ID",
                            "document_index contains missing or repeated document_id"))
    if skipped:
        issues.append(issue(source, "DOCUMENTS_SKIPPED_REQUIRE_REVIEW",
                            f"skipped={skipped}; declared documents were not fully downloaded"))
    for record in found:
        doc_id = str(record.get("document_id") or "UNKNOWN")
        raw = str(record.get("stored_path") or "").strip()
        if not raw:
            issues.append(issue(source, "DOCUMENT_FILE_MISSING", f"{doc_id}: no stored_path"))
            continue
        target = Path(raw)
        if not target.is_absolute():
            target = output_root.parent / target
        target = target.resolve()
        # Source payloads may not point outside the requested collection directory.
        try:
            target.relative_to(root.resolve())
        except ValueError:
            issues.append(issue(source, "DOCUMENT_PATH_OUTSIDE_SOURCE_ROOT",
                                f"{doc_id}: {raw}"))
            continue
        if not target.is_file() or target.stat().st_size <= 0:
            issues.append(issue(source, "DOCUMENT_FILE_MISSING",
                                f"{doc_id}: missing/empty file {raw}"))
            continue
        byte_size = str(record.get("bytes") or "").strip()
        if not byte_size.isdigit() or target.stat().st_size != int(byte_size):
            issues.append(issue(source, "DOCUMENT_SIZE_MISMATCH",
                                f"{doc_id}: indexed={byte_size}; actual={target.stat().st_size}"))
        expected_digest = str(record.get("sha256") or "").lower().strip()
        digest = hashlib.sha256()
        with target.open("rb") as contents:
            for block in iter(lambda: contents.read(1024 * 1024), b""):
                digest.update(block)
        actual_digest = digest.hexdigest()
        if len(expected_digest) != 64 or actual_digest != expected_digest:
            issues.append(issue(source, "DOCUMENT_DIGEST_MISMATCH",
                                f"{doc_id}: indexed={expected_digest}; actual={actual_digest}"))
    return issues


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
    registry_seeded = [str(x) for x in status.get("registry_seeded_fact_codes") or [] if str(x)]
    seeded = sorted(set(address_seeded) | set(registry_seeded))
    fact_list_ok = status.get("fact_list_query_success") is True
    years = [x for x in status.get("annual_years") or []]
    expected_fact_queries = fact_codes * len(years)
    fact_success = int(status.get("annual_fact_requests_success") or 0)
    if fact_codes <= 0 or not seeded or not fact_list_ok or fact_success != expected_fact_queries:
        return [issue(
            "SOOSIRO_WATER",
            "UNSUPPORTED_NO_DATA_CONFIRMATION",
            f"fact_codes={fact_codes}; seeded_fact_codes={len(seeded)}; fact_list_query_success={fact_list_ok}; annual_fact_requests_success={fact_success}/{expected_fact_queries}",
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


def evaluate(output_root: str | Path, request_path: str | Path, *, require_all_sources: bool = False) -> dict:
    output = Path(output_root)
    request = read_json(request_path, {}) or {}
    configured = list((request.get("sources") or {}).keys())
    if (output / "CORP_DOCS" / "status.json").exists() and "CORP_DOCS" not in configured:
        configured.append("CORP_DOCS")
    if require_all_sources:
        configured = list(dict.fromkeys([*configured, *REQUIRED_COLLECTION_SOURCES]))
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

        allowed = ACCEPTED_TMS_STATUSES if source in TMS_SOURCES else ACCEPTED_SOURCE_STATUSES
        if source_status == "DISCOVERY_UNRESOLVED":
            issues.append(issue(
                source,
                "SOURCE_ID_DISCOVERY_UNRESOLVED",
                "source was reachable but no source-native facility identity was established; do not convert this to no-data",
            ))
        elif source_status not in allowed:
            issues.append(issue(source, "UNACCEPTED_SOURCE_STATUS",
                                f"status={source_status}; execution success is not collection success"))

        if _has_errors(status):
            issues.append(issue(source, "COLLECTOR_ERRORS_REPORTED", f"errors={str(status.get('errors'))[:500]}"))
        for failure_field in ("detail_fail", "attachment_fail", "source_id_backfill_failed"):
            if int(status.get(failure_field) or 0) > 0:
                issues.append(issue(source, "INCOMPLETE_SOURCE_ARTIFACT",
                                    f"{failure_field}={status[failure_field]}"))
        if str(status.get("source_key") or "") != source:
            issues.append(issue(source, "SOURCE_KEY_MISMATCH",
                                f"expected={source}; reported={status.get('source_key')}"))
        if source in TMS_SOURCES and source_status == "NO_FACILITY_MATCH_CONFIRMED":
            if not _verified_tms_identity(request, source):
                issues.append(issue(source, "UNVERIFIED_REGISTRY_MISS_IDENTITY",
                                    "verified current-entity names and sites are required for a registry no-match"))
            if source == "CLEANSYS_AIR":
                if int(status.get("candidate_count") or 0) != 0 or int(status.get("candidate_query_attempts") or 0) != 0:
                    issues.append(issue(source, "CONTRADICTORY_REGISTRY_MISS",
                                        "registry no-match reported despite candidate IDs or attempted ID-bound queries"))
            else:
                if int(status.get("fact_codes") or 0) != 0 or status.get("fact_code_list"):
                    issues.append(issue(source, "CONTRADICTORY_REGISTRY_MISS",
                                        "registry no-match reported despite discovered FACT_CODE candidates"))

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
            issues.extend(_validate_corporate_document_files(output, status))
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
    parser.add_argument("--require-all-sources", action="store_true",
                        help="Require all six collection lanes, including corporate documents.")
    args = parser.parse_args()

    result = evaluate(args.output_root, args.request, require_all_sources=args.require_all_sources)
    Path(args.summary_out).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
