#!/usr/bin/env python3
"""Shared zero-touch collection-only workflow runner.

Collection is accepted independently of analysis, package generation, Human Archive,
or application materials. Full raw source outputs remain on disk; GitHub Actions
uploads compact inspection evidence separately.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from orchestrator.collection_acceptance import (
    ACCEPTED_SOURCE_STATUSES, ACCEPTED_TMS_STATUSES, ACCEPTED_CORPORATE_STATUSES,
    ACCEPTED_ENVINFO_STATUSES,
    TMS_SOURCES, evaluate,
)
from orchestrator.source_regression_runner import (
    BASELINE_PATH, SOURCE_ORDER, apply_source_baseline, read_json,
)


def write(path: str | Path, obj: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(label: str, *command: str) -> int:
    print(f"\\n=== {label} ===", flush=True)
    print(" ".join(command), flush=True)
    try:
        rc = subprocess.run(list(command), check=False).returncode
    except Exception as exc:
        print(f"COLLECTION_PROCESS_FAILED {label}: {type(exc).__name__}: {exc}", flush=True)
        return 98
    print(f"{label}: exit={rc}", flush=True)
    return rc


def baseline_check(label: str, output_root: Path, baseline_path: Path) -> dict:
    if not label:
        return {"status": "NOT_REQUESTED", "label": "", "results": []}
    baselines = read_json(baseline_path).get("companies", {})
    if label not in baselines:
        return {"status": "REVIEW_REQUIRED", "label": label,
                "error": "UNKNOWN_BASELINE_LABEL", "results": []}
    results = []
    for source in SOURCE_ORDER:
        status = read_json(output_root / source / "status.json")
        status_value = str(status.get("status") or "MISSING_STATUS")
        allowed = (ACCEPTED_TMS_STATUSES if source in TMS_SOURCES
                   else ACCEPTED_CORPORATE_STATUSES if source == "CORP_DOCS"
                   else ACCEPTED_ENVINFO_STATUSES if source == "ENVINFO"
                   else ACCEPTED_SOURCE_STATUSES)
        if status_value not in allowed or status.get("errors") or not status:
            results.append({"source": source, "result": "SKIPPED_UNACCEPTED",
                            "source_status": status_value,
                            "baseline_check": "SKIPPED_SOURCE_NOT_REACHABLE_OR_FAILED"})
            continue
        classified = apply_source_baseline(
            label, {"source": source, "result": "PASS", "source_status": status_value},
            baseline_path=baseline_path, output_root=output_root,
        )
        results.append(classified)
    blockers = [x for x in results if x.get("result") == "REGRESSION_FAIL"]
    incomplete = [x for x in results if x.get("result") == "SKIPPED_UNACCEPTED"]
    return {
        "status": "REVIEW_REQUIRED" if blockers or incomplete else "PASS",
        "label": label,
        "blocking_regressions": blockers,
        "unaccepted_sources": incomplete,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-label", default="", help="Optional known representative company key")
    parser.add_argument("--baseline-file", default=str(BASELINE_PATH))
    parser.add_argument("--output-root", default="output")
    parser.add_argument("--summary-out", default="Collection_Acceptance.json")
    parser.add_argument("--baseline-out", default="Collection_Baseline.json")
    parser.add_argument("--execution-out", default="Collection_Execution.json")
    args = parser.parse_args()

    root = Path(args.output_root)
    root.mkdir(parents=True, exist_ok=True)
    profile = "requests/runtime/company_profile.generated.json"
    request = "requests/current.generated.json"
    codes: dict[str, object] = {}

    codes["bootstrap"] = run("Bootstrap verified current company inputs", sys.executable,
                              "orchestrator/bootstrap_inputs.py",
                              "--profile-out", profile, "--request-out", request,
                              "--summary-out", "requests/runtime/Company_Discovery_Summary.json")
    if codes["bootstrap"] != 0 or not Path(request).exists():
        write(args.execution_out, {"status": "REVIEW_REQUIRED", "process_exit_codes": codes,
                                   "error": "BOOTSTRAP_FAILED"})
        write(args.summary_out, {"status": "REVIEW_REQUIRED", "blocking_issue_count": 1,
                                 "blocking_issues": [{"source": "BOOTSTRAP", "issue_type": "BOOTSTRAP_FAILED"}]})
        write(args.baseline_out, {"status": "NOT_RUN", "label": args.baseline_label})
        return 2

    collectors = {
        "ENVINFO": ["collectors/envinfo_collect.py", request],
        "CLEANSYS_AIR": ["collectors/cleansys_collect.py", request],
        "SOOSIRO_WATER": ["collectors/soosiro_collect.py", request],
        "CORP_DOCS": ["collectors/corporate_docs_collect.py",
                      "requests/document_evidence.json", profile],
    }
    for source, command in collectors.items():
        codes[source] = run(source, sys.executable, *command)
        if source == "ENVINFO":
            codes["ENVINFO_ATTACHMENT_RECOVERY"] = run(
                "ENVINFO attachment recovery", sys.executable,
                "collectors/envinfo_attachment_recovery.py", "--out", str(root / "ENVINFO"),
                "--repo-root", ".",
            )

    icis_attempts = []
    for attempt in range(1, 4):
        for source in ("PRTR", "CHEM_STATS"):
            shutil.rmtree(root / source, ignore_errors=True)
        attempt_result = {"attempt": attempt}
        attempt_result["PRTR"] = run("PRTR", sys.executable, "collectors/prtr_collect.py", request)
        attempt_result["CHEM_STATS"] = run("CHEM_STATS", sys.executable,
                                            "collectors/chem_stats_collect.py", request)
        attempt_result["icis_gate"] = run("ICIS source pair gate", sys.executable, "collectors/icis_gate.py")
        icis_attempts.append(attempt_result)
        if all(attempt_result.get(key) == 0 for key in ("PRTR", "CHEM_STATS", "icis_gate")):
            break
    codes["icis_attempts"] = icis_attempts

    try:
        acceptance = evaluate(root, request, require_all_sources=True)
    except Exception as exc:
        acceptance = {"status": "REVIEW_REQUIRED", "blocking_issue_count": 1,
                      "blocking_issues": [{"source": "ACCEPTANCE", "issue_type": "EVALUATION_EXCEPTION",
                                            "detail": f"{type(exc).__name__}: {exc}"}]}
    # A collector can return nonzero even if it wrote a plausible status. Never
    # let that exit failure disappear behind the status-based acceptance summary.
    for key, rc in codes.items():
        if key in {"icis_attempts", "bootstrap"}:
            continue
        if rc != 0:
            item = {"source": key, "issue_type": "NONZERO_PROCESS_EXIT",
                    "severity": "BLOCKING", "detail": f"exit={rc}"}
            acceptance.setdefault("blocking_issues", []).append(item)
    if not icis_attempts or not all(
        icis_attempts[-1].get(key) == 0 for key in ("PRTR", "CHEM_STATS", "icis_gate")
    ):
        acceptance.setdefault("blocking_issues", []).append({
            "source": "ICIS", "issue_type": "RETRY_EXHAUSTED",
            "severity": "BLOCKING", "detail": "No complete ICIS pair after three bounded attempts",
        })
    if acceptance.get("blocking_issues"):
        acceptance["status"] = "REVIEW_REQUIRED"
        acceptance["blocking_issue_count"] = len(acceptance["blocking_issues"])

    baseline = baseline_check(args.baseline_label, root, Path(args.baseline_file))
    execution_status = (
        acceptance["status"]
        if acceptance["status"] in {"PASS", "PASS_WITH_LIMITATION"}
        and baseline["status"] in {"PASS", "NOT_REQUESTED"}
        else "REVIEW_REQUIRED"
    )
    execution = {"status": execution_status,
                 "process_exit_codes": codes,
                 "acceptance_status": acceptance["status"],
                 "baseline_status": baseline["status"]}
    write(args.summary_out, acceptance)
    write(args.baseline_out, baseline)
    write(args.execution_out, execution)
    print(json.dumps({"collection": acceptance["status"], "issues": acceptance.get("blocking_issue_count"),
                      "baseline": baseline["status"], "overall": execution["status"]}, ensure_ascii=False),
          flush=True)
    return 0 if execution["status"] in {"PASS", "PASS_WITH_LIMITATION"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
