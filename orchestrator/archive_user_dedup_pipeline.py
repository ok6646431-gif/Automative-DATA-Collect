"""User-facing archive dedup pipeline.

Order matters:
1. Canonicalize repeated ENV-INFO attachments and exact cross-folder copies.
2. Remove proven semantic duplicates between ENV-INFO attachments and official annual
   sustainability reports while raw/system evidence still exists.
3. Run the generic final ZIP dedup against the resulting user layer.
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

import archive_user_dedup_v2 as envinfo_dedup
import archive_zip_dedup as zip_dedup
from archive_sustainability_crosslane import deduplicate_envinfo_annual_report_copies


def run(package_root: str | Path = "assembled") -> dict:
    package_root = Path(package_root).resolve()
    zip_path = package_root / "Human_Archive.zip"
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)
    original_zip_bytes = zip_path.stat().st_size

    with tempfile.TemporaryDirectory(prefix="human-archive-user-dedup-") as td:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad:
                raise RuntimeError(f"ZIP integrity failure before user dedup: {bad}")
            zf.extractall(td)
        archive_root = zip_dedup._find_archive_root(td)

        stats = envinfo_dedup.canonicalize_user_envinfo(archive_root)
        stats = deduplicate_envinfo_annual_report_copies(archive_root, stats)

        # Semantic removal can redirect or remove user files after the first inventory
        # refresh, so rebuild the indexes before rewriting the ZIP.
        zip_dedup.refresh_user_indexes(archive_root)
        envinfo_dedup._persist_pre_stats(package_root, archive_root, stats)
        zip_dedup._rewrite_zip(zip_path, archive_root)

    # System/raw dedup must happen only after the user-facing cross-lane decision.
    core_result = zip_dedup.run(package_root)
    final_bytes = zip_path.stat().st_size
    result = {
        **core_result,
        **stats,
        "zip_bytes_before_user_dedup": original_zip_bytes,
        "zip_bytes_after_all_dedup": final_bytes,
        "zip_bytes_saved_total": original_zip_bytes - final_bytes,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--package", default="assembled")
    args = ap.parse_args()
    run(args.package)
