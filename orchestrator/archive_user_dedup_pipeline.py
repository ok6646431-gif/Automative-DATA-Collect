"""User-facing archive dedup pipeline.

Order matters:
1. Canonicalize repeated ENV-INFO attachments and exact cross-folder copies.
2. Remove proven semantic duplicates between ENV-INFO attachments and official annual
   sustainability reports while raw/system evidence still exists.
3. Remove exact duplicates between the user layer and the system/raw layer.
4. Refresh metadata and rewrite the final ZIP once.

The archive stage normally still has the fully built ``Human_Archive/<root>`` tree
available when this pipeline runs. Reusing that tree avoids extracting a multi-GB ZIP
into ``/tmp`` and then extracting it a second time for generic deduplication. Standalone
invocations, where the live tree is absent, fall back to one temporary extraction and
run the same combined pipeline there.
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

import archive_user_dedup_v2 as envinfo_dedup
import archive_zip_dedup as zip_dedup
from archive_sustainability_crosslane import deduplicate_envinfo_annual_report_copies


def _validate_zip(zip_path: Path) -> None:
    """Validate the pre-dedup ZIP without materializing another archive tree."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity failure before user dedup: {bad}")


def _process_archive_tree(
    package_root: Path,
    zip_path: Path,
    archive_root: Path,
    original_zip_bytes: int,
    execution_mode: str,
) -> dict:
    """Run all semantic and exact dedup passes against one materialized tree."""
    stats = envinfo_dedup.canonicalize_user_envinfo(archive_root)
    stats = deduplicate_envinfo_annual_report_copies(archive_root, stats)

    # User-facing semantic removal changes paths and inventory rows. Persist those
    # audit statistics before the generic exact-content pass updates final metadata.
    zip_dedup.refresh_user_indexes(archive_root)
    envinfo_dedup._persist_pre_stats(package_root, archive_root, stats)

    # Run the generic exact-content pass on the same tree instead of rewriting and
    # re-extracting the ZIP. This preserves the existing dedup semantics while
    # avoiding a second full-size copy of the archive on the runner filesystem.
    core_stats = zip_dedup.deduplicate_tree(archive_root)
    zip_dedup._sync_metadata(package_root, archive_root, core_stats)
    zip_dedup._rewrite_zip(zip_path, archive_root)
    summary = zip_dedup._refresh_root_indexes(package_root, zip_path, core_stats)

    final_bytes = zip_path.stat().st_size
    core_result = {
        **core_stats,
        "zip_bytes_before": original_zip_bytes,
        "zip_bytes_after": final_bytes,
        "zip_bytes_saved": original_zip_bytes - final_bytes,
        "zip_sha256": summary["zip_sha256"],
    }
    result = {
        **core_result,
        **stats,
        "dedup_execution_mode": execution_mode,
        "zip_bytes_before_user_dedup": original_zip_bytes,
        "zip_bytes_after_all_dedup": final_bytes,
        "zip_bytes_saved_total": original_zip_bytes - final_bytes,
    }
    return result


def run(package_root: str | Path = "assembled") -> dict:
    package_root = Path(package_root).resolve()
    zip_path = package_root / "Human_Archive.zip"
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)
    original_zip_bytes = zip_path.stat().st_size
    _validate_zip(zip_path)

    # During the normal archive stage, build_archive/finalize_archive_manifest leave
    # the authoritative materialized tree in place until this function returns.
    # Prefer it so large archives never need a full duplicate extraction in /tmp.
    live_parent = package_root / "Human_Archive"
    if live_parent.exists():
        try:
            live_root = zip_dedup._find_archive_root(live_parent)
        except RuntimeError:
            live_root = None
        if live_root is not None:
            result = _process_archive_tree(
                package_root,
                zip_path,
                live_root,
                original_zip_bytes,
                "LIVE_ARCHIVE_TREE_SINGLE_REWRITE",
            )
            print(json.dumps(result, ensure_ascii=False))
            return result

    # Standalone compatibility path: extract exactly once, run both dedup layers on
    # that one tree, and rewrite the ZIP once. No nested core.run() extraction.
    with tempfile.TemporaryDirectory(prefix="human-archive-combined-dedup-") as td:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(td)
        archive_root = zip_dedup._find_archive_root(td)
        result = _process_archive_tree(
            package_root,
            zip_path,
            archive_root,
            original_zip_bytes,
            "SINGLE_TEMP_EXTRACTION_SINGLE_REWRITE",
        )

    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--package", default="assembled")
    args = ap.parse_args()
    run(args.package)
