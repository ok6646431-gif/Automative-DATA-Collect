#!/usr/bin/env python3
"""Run only selected source collectors for an R2 regression checkpoint.

R2 is intentionally a lightweight identity/coverage probe. It does not assemble the
Master package, Human Archive, or Application Materials and, in probe mode, it skips
large ENV-INFO attachments and source detail payloads that are covered by R3.

External-host outages are reported as INFRA_RETRY_REQUIRED rather than code failures.
Successful source executions are additionally checked against conservative must-keep
source-native IDs from previously verified representative-company runs.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

try:
    from .regression_tier_policy import classify_execution_failure
except ImportError:
    from regression_tier_policy import classify_execution_failure

SOURCE_ORDER = ["ENVINFO", "PRTR", "CHEM_STATS", "CLEANSYS_AIR", "SOOSIRO_WATER", "CORP_DOCS"]
STATUS_PATH = {
    "ENVINFO": "output/ENVINFO/status.json",
    "PRTR": "output/PRTR/status.json",
    "CHEM_STATS": "output/CHEM_STATS/status.json",
    "CLEANSYS_AIR": "output/CLEANSYS_AIR/status.json",
    "SOOSIRO_WATER": "output/SOOSIRO_WATER/status.json",
    "CORP_DOCS": "output/CORP_DOCS/status.json",
}
COMMANDS = {
    "ENVINFO": [sys.executable, "collectors/envinfo_collect.py", "requests/current.generated.json"],
    "PRTR": [sys.executable, "collectors/prtr_collect.py", "requests/current.generated.json"],
    "CHEM_STATS": [sys.executable, "collectors/chem_stats_collect.py", "requests/current.generated.json"],
    "CLEANSYS_AIR": [sys.executable, "collectors/cleansys_collect.py", "requests/current.generated.json"],
    "SOOSIRO_WATER": [sys.executable, "collectors/soosiro_collect.py", "requests/current.generated.json"],
    "CORP_DOCS": [
        sys.executable,
        "collectors/corporate_docs_collect.py",
        "requests/document_evidence.json",
        "requests/runtime/company_profile.generated.json",
    ],
}
FATAL_SOURCE_STATUSES = {
    "REQUEST_OR_PARSE_FAILED",
    "PARTIAL_FAILURE",
    "REMOTE_HOST_UNREACHABLE",
    "CONFIG_ERROR",
    "INVALID_SCOPE",
    "NOT_RUN",
}
BASELINE_PATH = Path("tests/regression_cases/representative_source_baselines.json")


def parse_sources(value: str) -> list[str]:
    raw = str(value or "").replace(";", ",").split(",")
    requested = {x.strip().upper() for x in raw if x.strip()}
    if not requested or "ALL" in requested:
        return list(SOURCE_ORDER)
    unknown = sorted(requested.difference(SOURCE_ORDER))
    if unknown:
        raise ValueError(f"unknown source lanes: {unknown}")
    return [s for s in SOURCE_ORDER if s in requested]


def read_json(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def run_process(command: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(command, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def apply_probe_overrides(request_path: str | Path, sources: list[str]) -> dict:
    """Disable large/detail payloads that do not belong in the R2 identity probe."""
    path = Path(request_path)
    req = read_json(path)
    configs = req.setdefault("sources", {})
    changed = {}
    if "ENVINFO" in sources and isinstance(configs.get("ENVINFO"), dict):
        configs["ENVINFO"]["collect_details"] = False
        configs["ENVINFO"]["collect_attachments"] = False
        changed["ENVINFO"] = ["collect_details=false", "collect_attachments=false"]
    if "PRTR" in sources and isinstance(configs.get("PRTR"), dict):
        configs["PRTR"]["collect_details"] = False
        changed["PRTR"] = ["collect_details=false"]
    if "CHEM_STATS" in sources and isinstance(configs.get("CHEM_STATS"), dict):
        configs["CHEM_STATS"]["collect_details"] = False
        configs["CHEM_STATS"]["source_native_id_backfill"] = False
        changed["CHEM_STATS"] = ["collect_details=false", "source_native_id_backfill=false"]
    path.write_text(json.dumps(req, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def _csv_ids(path: Path, field: str) -> set[str]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8-sig") as f:
        return {str(row.get(field) or "").strip() for row in csv.DictReader(f) if str(row.get(field) or "").strip()}


def _json_list_ids(path: Path, field: str) -> set[str]:
    obj = read_json(path)
    if not isinstance(obj, list):
        return set()
    return {str(row.get(field) or "").strip() for row in obj if isinstance(row, dict) and str(row.get(field) or "").strip()}


def observed_source_ids(source: str, output_root: str | Path = "output") -> set[str]:
    root = Path(output_root)
    if source == "ENVINFO":
        return _csv_ids(root / "ENVINFO/discovery.csv", "compId")
    if source == "PRTR":
        return _csv_ids(root / "PRTR/discovery.csv", "entrps_id")
    if source == "CHEM_STATS":
        return _csv_ids(root / "CHEM_STATS/discovery.csv", "bplcId")
    if source == "CLEANSYS_AIR":
        return _json_list_ids(root / "CLEANSYS_AIR/candidates.json", "fact_code")
    if source == "SOOSIRO_WATER":
        return _json_list_ids(root / "SOOSIRO_WATER/fact_candidates.json", "FACT_CODE")
    return set()


def apply_source_baseline(company: str, classified: dict, *, baseline_path: str | Path = BASELINE_PATH, output_root: str | Path = "output") -> dict:
    """Fail a reachable source if a previously verified must-keep identity disappears."""
    source = classified["source"]
    baselines = read_json(baseline_path)
    source_baseline = (
        baselines.get("companies", {})
        .get(company, {})
        .get("sources", {})
        .get(source)
    )
    if not source_baseline:
        classified["baseline_check"] = "NOT_CONFIGURED"
        return classified
    expected = {str(x) for x in source_baseline.get("must_include_ids", []) if str(x)}
    if classified.get("result") != "PASS":
        classified["baseline_check"] = "SKIPPED_SOURCE_NOT_REACHABLE_OR_FAILED"
        classified["baseline_expected_ids"] = sorted(expected)
        return classified
    observed = observed_source_ids(source, output_root)
    missing = sorted(expected.difference(observed))
    classified["baseline_expected_ids"] = sorted(expected)
    classified["baseline_observed_ids"] = sorted(observed)
    classified["baseline_missing_ids"] = missing
    if missing:
        classified["baseline_check"] = "FAIL_MISSING_MUST_KEEP_IDS"
        classified["result"] = "REGRESSION_FAIL"
    else:
        classified["baseline_check"] = "PASS"
    return classified


def classify_source(source: str, returncode: int, status: dict, stdout: str, stderr: str) -> dict:
    source_status = str(status.get("status") or "MISSING_STATUS")
    diagnostic = "\n".join(
        str(x or "")
        for x in (
            stdout,
            stderr,
            status.get("fatal_error"),
            status.get("preflight_error"),
            status.get("error"),
            json.dumps(status.get("errors", ""), ensure_ascii=False),
        )
    )
    if returncode == 0 and source_status not in FATAL_SOURCE_STATUSES and source_status != "MISSING_STATUS":
        result = "PASS"
    else:
        result = classify_execution_failure(status=source_status, text=diagnostic)
    return {
        "source": source,
        "result": result,
        "returncode": returncode,
        "source_status": source_status,
        "rows": status.get("rows", status.get("annual_rows", "")),
        "errors": status.get("errors", ""),
        "status_path": STATUS_PATH[source],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True)
    ap.add_argument("--company", default="")
    ap.add_argument("--output", default="source-regression-result.json")
    ap.add_argument("--probe", action="store_true", help="Skip large/detail payloads and test source identity discovery only.")
    ap.add_argument("--baseline", default=str(BASELINE_PATH))
    args = ap.parse_args()

    sources = parse_sources(args.sources)
    probe_overrides = {}
    if args.probe:
        probe_overrides = apply_probe_overrides("requests/current.generated.json", sources)
        print(json.dumps({"r2_probe_overrides": probe_overrides}, ensure_ascii=False), flush=True)

    results = []
    for source in sources:
        print(f"\n=== R2 SOURCE {source} / {args.company or 'company'} ===", flush=True)
        returncode, stdout, stderr = run_process(COMMANDS[source])

        # Full source-local mode can validate ENV-INFO attachment recovery. R2 probe
        # deliberately skips it because attachment integrity is an R3 contract.
        if source == "ENVINFO" and returncode == 0 and not args.probe:
            recovery = [
                sys.executable,
                "collectors/envinfo_attachment_recovery.py",
                "--out",
                "output/ENVINFO",
                "--repo-root",
                ".",
            ]
            rr, rout, rerr = run_process(recovery)
            returncode = returncode or rr
            stdout += rout
            stderr += rerr

        status = read_json(STATUS_PATH[source])
        classified = classify_source(source, returncode, status, stdout, stderr)
        classified = apply_source_baseline(args.company, classified, baseline_path=args.baseline)
        results.append(classified)
        print(json.dumps(classified, ensure_ascii=False), flush=True)

    aggregate = "PASS"
    if any(r["result"] == "REGRESSION_FAIL" for r in results):
        aggregate = "REGRESSION_FAIL"
    elif any(r["result"] == "INFRA_RETRY_REQUIRED" for r in results):
        aggregate = "INFRA_RETRY_REQUIRED"

    payload = {
        "schema_version": "1.1",
        "company": args.company,
        "sources": sources,
        "probe_mode": bool(args.probe),
        "probe_overrides": probe_overrides,
        "aggregate_result": aggregate,
        "results": results,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if aggregate == "REGRESSION_FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
