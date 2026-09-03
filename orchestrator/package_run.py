"""Compatibility layer for final package validation semantics.

The previous packager is preserved in ``package_run_core``.  This layer adds two
strictly bounded rules: collector-declared empty audit streams are not corruption,
and identity reviews that demonstrably do not belong to a requested SITE_SET remain
in the audit queue but do not block delivery.
"""

import csv
import json
import sys
from pathlib import Path

_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import package_run_core as _core
from package_run_core import *  # preserve public helper contract
import requested_scope as _scope

# An empty audit stream is valid only when the collector status explicitly declares
# the corresponding attempt count as zero.
_core.DECLARED_ROW_STREAM_COUNTS.setdefault("CHEM_STATS", {})[
    "source_id_backfill_attempts.jsonl"
] = "source_id_backfill_attempts"

_BASE_APPLY_REQUESTED_SCOPE = _core.apply_requested_scope


def _read_csv(path):
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path, rows, fields):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _demote_out_of_scope_identity_reviews(package_root, scope_summary):
    root = Path(package_root)
    if str(scope_summary.get("mode") or "").upper() != "SITE_SET":
        return 0

    profile = json.loads((root / "Company_Profile.json").read_text(encoding="utf-8"))
    selected, _ = _scope.selected_candidates(profile)
    address_counts = _scope._selected_address_counts(selected)
    target_ids = {
        source: {str(v) for v in values}
        for source, values in (scope_summary.get("target_source_ids") or {}).items()
    }

    identities = _read_csv(root / "Source_Identity.csv")
    out_of_scope = set()
    for row in identities:
        source = row.get("source_key", "")
        sid = str(row.get("source_site_id") or "")
        if not source or not sid or sid in target_ids.get(source, set()):
            continue
        # Keep a weak identity blocking if it could still be one of the explicitly
        # requested sites. Only demonstrably non-matching company-wide raw evidence is
        # demoted.
        could_be_requested = any(
            _scope._candidate_matches(
                candidate,
                row.get("source_site_name_raw"),
                row.get("source_address_raw"),
                profile,
                address_counts,
            )
            for candidate in selected
        )
        if not could_be_requested:
            out_of_scope.add(f"{source}:{sid}")

    if not out_of_scope:
        return 0

    queue_path = root / "Validation_Queue.csv"
    queue = _read_csv(queue_path)
    changed = set()
    for row in queue:
        if row.get("object_type") != "SOURCE_IDENTITY" or row.get("object_key") not in out_of_scope:
            continue
        if row.get("status") != "REVIEW_REQUIRED":
            continue
        row["status"] = "OUT_OF_SCOPE_RETAINED"
        row["severity"] = "INFO"
        row["notes"] = (
            (row.get("notes") or "").strip()
            + "; retained in company-wide raw identity evidence but outside requested SITE_SET"
        ).strip("; ")
        changed.add(row.get("validation_id"))
    if queue:
        _write_csv(queue_path, queue, list(queue[0].keys()))

    review_path = root / "REVIEW_REQUIRED.json"
    review = json.loads(review_path.read_text(encoding="utf-8")) if review_path.exists() else []
    review = [
        item for item in review
        if not (
            isinstance(item, dict)
            and item.get("object_type") == "SOURCE_IDENTITY"
            and item.get("object_key") in out_of_scope
            and item.get("validation_id") in changed
        )
    ]
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(changed)


def apply_requested_scope(package_root):
    summary = _BASE_APPLY_REQUESTED_SCOPE(package_root)
    _demote_out_of_scope_identity_reviews(package_root, summary)
    return summary


_core.apply_requested_scope = apply_requested_scope


def main():
    return _core.main()


if __name__ == "__main__":
    main()
