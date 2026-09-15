#!/usr/bin/env python3
"""Run only selected source collectors for an R2 regression checkpoint.

This intentionally does not assemble the Master package, Human Archive, or Application
Materials. External-host outages are reported as INFRA_RETRY_REQUIRED rather than as
code regressions.
"""
from __future__ import annotations

import argparse
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
    "REMOTE_HOST_UNREACHABLE",
    "CONFIG_ERROR",
    "INVALID_SCOPE",
    "NOT_RUN",
}


def parse_sources(value: str) -> list[str]:
    raw = str(value or "").replace(";", ",").split(",")
    requested = {x.strip().upper() for x in raw if x.strip()}
    if not requested or "ALL" in requested:
        return list(SOURCE_ORDER)
    unknown = sorted(requested.difference(SOURCE_ORDER))
    if unknown:
        raise ValueError(f"unknown source lanes: {unknown}")
    return [s for s in SOURCE_ORDER if s in requested]


def read_json(path: str) -> dict:
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
    args = ap.parse_args()

    sources = parse_sources(args.sources)
    results = []
    for source in sources:
        print(f"\n=== R2 SOURCE {source} / {args.company or 'company'} ===", flush=True)
        returncode, stdout, stderr = run_process(COMMANDS[source])

        # ENV-INFO's attachment recovery/dedup is part of its source contract, but is
        # still source-local and does not invoke package/archive stages.
        if source == "ENVINFO" and returncode == 0:
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
        results.append(classified)
        print(json.dumps(classified, ensure_ascii=False), flush=True)

    aggregate = "PASS"
    if any(r["result"] == "REGRESSION_FAIL" for r in results):
        aggregate = "REGRESSION_FAIL"
    elif any(r["result"] == "INFRA_RETRY_REQUIRED" for r in results):
        aggregate = "INFRA_RETRY_REQUIRED"

    payload = {
        "schema_version": "1.0",
        "company": args.company,
        "sources": sources,
        "aggregate_result": aggregate,
        "results": results,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if aggregate == "REGRESSION_FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
