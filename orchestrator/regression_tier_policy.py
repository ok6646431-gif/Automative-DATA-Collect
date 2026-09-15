#!/usr/bin/env python3
"""Impact-based regression routing for shared pipeline changes.

R1 = fast deterministic tests/fixtures.
R2 = live regression only for affected source lanes.
R3 = full Collection -> Human Archive -> Application Materials E2E.

A higher tier does not erase lower-tier information: a change may require R3 and also
identify affected R2 sources.  Callers can decide whether a release run needs both.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable

PUBLIC_SOURCES = (
    "ENVINFO",
    "PRTR",
    "CHEM_STATS",
    "CLEANSYS_AIR",
    "SOOSIRO_WATER",
)
ALL_SOURCE_LANES = PUBLIC_SOURCES + ("CORP_DOCS",)

SOURCE_PATH_RULES = {
    "ENVINFO": (
        "collectors/envinfo_",
    ),
    "PRTR": (
        "collectors/prtr_",
    ),
    "CHEM_STATS": (
        "collectors/chem_stats_",
        "collectors/icis_",
        "orchestrator/icis_",
    ),
    "CLEANSYS_AIR": (
        "collectors/cleansys_",
    ),
    "SOOSIRO_WATER": (
        "collectors/soosiro_",
    ),
    "CORP_DOCS": (
        "collectors/corporate_docs_",
        "orchestrator/corporate_document_",
    ),
}

# Identity/scope/request compilation can change which candidate reaches every public
# collector, so all public source lanes are invalidated, but archive/package E2E is not.
ALL_PUBLIC_R2_PREFIXES = (
    "collectors/entity_scope_gate.py",
    "collectors/name_filter.py",
    "orchestrator/request_builder.py",
    "orchestrator/bootstrap_inputs.py",
    "orchestrator/company_profile_builder.py",
    "orchestrator/requested_scope.py",
)

# Structural output changes need the full user-facing E2E contract.  They do not, by
# themselves, require re-downloading public sources; R3 should reuse verified inputs
# where the workflow supports it.
R3_PREFIXES = (
    "orchestrator/archive",
    "orchestrator/package",
    "orchestrator/collection_completeness.py",
    "tools/build_application_material",
    "tools/validate_application_material",
    "tools/build_human_archive",
)

NO_RUNTIME_PREFIXES = (
    "docs/",
)
NO_RUNTIME_FILES = {
    "PROJECT_STATE.md",
    "README.md",
}

INFRA_PATTERNS = (
    r"REMOTE_HOST_UNREACHABLE",
    r"ConnectTimeout",
    r"ReadTimeout",
    r"ConnectionError",
    r"Temporary failure in name resolution",
    r"timed out",
    r"HTTP\s*(?:429|500|502|503|504)\b",
)


def _norm(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").lstrip("./")


def _starts(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def classify_paths(paths: Iterable[str]) -> dict:
    changed = sorted({_norm(p) for p in paths if _norm(p)})
    sources: set[str] = set()
    reasons: list[dict] = []
    r1 = False
    r3 = False

    for path in changed:
        if path in NO_RUNTIME_FILES or _starts(path, NO_RUNTIME_PREFIXES):
            reasons.append({"path": path, "impact": "NO_RUNTIME"})
            continue

        # Tests/workflows/policy files are deterministic-regression changes only unless
        # another runtime path in the same commit raises the tier.
        if path.startswith("tests/") or path.startswith(".github/workflows/"):
            r1 = True
            reasons.append({"path": path, "impact": "R1"})
            continue

        r1 = True

        if _starts(path, R3_PREFIXES):
            r3 = True
            reasons.append({"path": path, "impact": "R3"})
            continue

        if _starts(path, ALL_PUBLIC_R2_PREFIXES):
            sources.update(PUBLIC_SOURCES)
            reasons.append({"path": path, "impact": "R2", "sources": list(PUBLIC_SOURCES)})
            continue

        matched = []
        for source, prefixes in SOURCE_PATH_RULES.items():
            if _starts(path, prefixes):
                sources.add(source)
                matched.append(source)
        if matched:
            reasons.append({"path": path, "impact": "R2", "sources": matched})
        else:
            reasons.append({"path": path, "impact": "R1"})

    required_tier = "R3" if r3 else ("R2" if sources else ("R1" if r1 else "NONE"))
    return {
        "schema_version": "1.0",
        "required_tier": required_tier,
        "r1_required": r1,
        "r2_required": bool(sources),
        "r2_sources": [s for s in ALL_SOURCE_LANES if s in sources],
        "r3_required": r3,
        "changed_paths": changed,
        "reasons": reasons,
        "policy": {
            "network_failure": "INFRA_RETRY_REQUIRED",
            "shared_change_resets_full_e2e": False,
            "r3_release_rule": "archive/package structural change or explicit release milestone",
        },
    }


def classify_execution_failure(*, status: str = "", text: str = "") -> str:
    blob = f"{status}\n{text}"
    if any(re.search(pattern, blob, flags=re.I) for pattern in INFRA_PATTERNS):
        return "INFRA_RETRY_REQUIRED"
    return "REGRESSION_FAIL"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--paths-file")
    parser.add_argument("--output")
    args = parser.parse_args()

    paths = list(args.paths)
    if args.paths_file:
        paths.extend(Path(args.paths_file).read_text(encoding="utf-8").splitlines())
    plan = classify_paths(paths)
    payload = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
