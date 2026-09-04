"""Compatibility layer for final package validation semantics.

The previous packager is preserved in ``package_run_core``. This layer adds bounded
rules for declared empty audit streams, requested-scope identity demotion, and the
site-level BAT reference stage. BAT candidates are evidence-backed references only;
they never become claims that a company applies a BAT automatically.
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
from bat_stage import run as _run_bat_stage

# An empty audit stream is valid only when the collector status explicitly declares
# the corresponding attempt count as zero. Both historical/current audit filenames
# are supported because the semantic counter, not the filename spelling, is decisive.
for _audit_name in ("source_id_backfill_attempts.jsonl", "source_id_backfill_audit.jsonl"):
    _core.DECLARED_ROW_STREAM_COUNTS.setdefault("CHEM_STATS", {})[_audit_name] = "source_id_backfill_attempts"

_BASE_APPLY_REQUESTED_SCOPE = _core.apply_requested_scope
_BASE_RUN_CROSS_LAYER_REVIEW = _core.run_cross_layer_review


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


def _cross_layer_review_with_bat(package_root, semantic_path=None, applicability_path=None):
    bat_summary = _run_bat_stage(package_root)
    result = _BASE_RUN_CROSS_LAYER_REVIEW(package_root, semantic_path, applicability_path)
    if isinstance(result, dict):
        result['bat_reference_stage'] = bat_summary
    return result


_core.apply_requested_scope = apply_requested_scope
_core.run_cross_layer_review = _cross_layer_review_with_bat


def main():
    return _core.main()


if __name__ == "__main__":
    main()
