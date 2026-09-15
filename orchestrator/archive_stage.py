"""Compatibility wrapper for the archive stage with BAT reference delivery.

The stable archive implementation is preserved in ``archive_stage_core``. This
wrapper adds the BAT human-delivery hook after the normal archive tree is built and
routes the final user-facing dedup through an ordered pipeline.

The production wrapper deliberately finalizes the materialized archive tree before
creating any full-size ZIP. The dedup pipeline then reduces duplicate-heavy user/raw
copies in that live tree and writes the final ZIP exactly once. This avoids the large
peak-disk penalty of keeping an undeduplicated tree and an undeduplicated ZIP at the
same time.

The dedup pipeline performs strict PDF render-structure comparison for same-year
sustainability-report copies, including ENV-INFO attachments. ``pypdf``,
``cryptography`` and ``openpyxl`` are therefore archive-stage runtime dependencies.
``cryptography`` is required by pypdf when an attachment uses AES PDF encryption.
Legacy collection workflows did not install these dependencies explicitly, so this
compatibility wrapper bootstraps missing dependencies before importing the stable
archive core. Installation failure is fatal rather than silently disabling semantic
deduplication or provenance updates.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _ensure_archive_semantic_runtime():
    required = {
        'pypdf': 'pypdf',
        'cryptography': 'cryptography>=3.1',
        'openpyxl': 'openpyxl',
    }
    missing = [package for module, package in required.items() if importlib.util.find_spec(module) is None]
    if missing:
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', *missing],
            check=True,
        )
    unresolved = [module for module in required if importlib.util.find_spec(module) is None]
    if unresolved:
        raise RuntimeError(f'archive semantic runtime unavailable after installation: {unresolved}')


_ensure_archive_semantic_runtime()

import archive_stage_core as _core
from archive_stage_core import *  # preserve public helper contract
from archive_user_dedup_pipeline import run as _deduplicate_user_archive
from bat_archive import expose as _expose_bat_references
from requested_scope_candidate_guard import (
    audit_collection_for_requested_scope as _strict_scope_audit,
)

# The stable core imported the legacy dedup and requested-scope audit functions at
# module import time. Replace those function objects before ``_core.run`` is invoked.
# The strict scope audit prevents one verified requested site from silently dropping
# out merely because sibling sites were successfully mapped.
_core.deduplicate_archive_zip = _deduplicate_user_archive
_core.audit_collection_for_requested_scope = _strict_scope_audit

_BASE_BUILD_ARCHIVE = _core.build_archive


def _build_archive_with_bat(package_root, contract_path=_core.archive_builder.CONTRACT_PATH):
    summary = _BASE_BUILD_ARCHIVE(package_root, contract_path)
    root = Path(package_root).resolve()
    archive_root = root / 'Human_Archive' / summary['archive_root']
    bat = _expose_bat_references(root, archive_root)

    summary['bat_archive'] = bat
    checks = dict(summary.get('acceptance_checks') or {})
    if bat.get('guideline_reference_present'):
        checks['guideline_reference_present'] = True
    summary['acceptance_checks'] = checks

    # Keep the package-level summary synchronized before the core stage performs
    # classification, normalization and final ZIP acceptance.
    (root / 'Archive_Summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    return summary


_core.build_archive = _build_archive_with_bat


def _finalize_archive_manifest_pre_zip(package_root, manifest, archive_summary):
    """Finalize the live archive tree without materializing an undeduplicated ZIP.

    ``archive_stage_core.run`` immediately invokes the injected dedup pipeline after
    this function returns. That pipeline supports a live-tree/pre-ZIP execution mode
    and creates ``Human_Archive.zip`` only after all semantic and exact dedup passes.
    """
    root = Path(package_root).resolve()
    stable = {
        k: v for k, v in archive_summary.items()
        if k not in {'zip_sha256', 'zip_bytes'}
    }
    stable['status'] = 'PASS'
    stable['summary_file'] = 'Archive_Summary.json'
    stable['zip_file'] = 'Human_Archive.zip'
    manifest['human_archive'] = stable
    root.joinpath('Master_Manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    archive = root / 'Human_Archive' / archive_summary['archive_root']
    idx = archive / '00_자료목록'
    shutil.copy2(root / 'Master_Manifest.json', idx / 'Master_Manifest.json')
    system_manifest = archive / '90_시스템원본' / 'control_plane' / 'Master_Manifest.json'
    if system_manifest.parent.exists():
        shutil.copy2(root / 'Master_Manifest.json', system_manifest)
    for extra in [root / 'Requested_Scope.json', root / 'Analysis_Scope.csv']:
        if extra.exists():
            shutil.copy2(extra, idx / extra.name)

    file_rows = _core.archive_file_index(archive)
    _core.write_csv(
        idx / 'Archive_File_Index.csv',
        file_rows,
        ['path', 'bytes', 'sha256'],
    )

    # A stale ZIP must never cause the dedup pipeline to take the legacy rewrite mode.
    # The normal production path should enter LIVE_ARCHIVE_TREE_PREZIP_SINGLE_WRITE.
    zip_path = root / 'Human_Archive.zip'
    if zip_path.exists():
        zip_path.unlink()

    final = {
        **archive_summary,
        'archive_files': len(file_rows),
        'zip_path': 'Human_Archive.zip',
    }
    root.joinpath('Archive_Summary.json').write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    return final


# Production archive construction now performs metadata/tree finalization first and
# delegates the only complete ZIP write to the live-tree dedup pipeline.
_core.finalize_archive_manifest = _finalize_archive_manifest_pre_zip


def main():
    return _core.main()


if __name__ == '__main__':
    main()
