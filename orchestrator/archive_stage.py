"""Compatibility wrapper for the archive stage with BAT reference delivery.

The stable archive implementation is preserved in ``archive_stage_core``. This
wrapper adds the BAT human-delivery hook after the normal archive tree is built and
routes the final user-facing dedup through an ordered pipeline.

The dedup pipeline performs strict PDF render-structure comparison for same-year
sustainability-report copies, including ENV-INFO attachments. ``pypdf`` and
``openpyxl`` are therefore archive-stage runtime dependencies. Legacy collection
workflows did not install them explicitly, so this compatibility wrapper bootstraps
missing dependencies before importing the stable archive core. Installation failure
is fatal rather than silently disabling semantic deduplication or provenance updates.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _ensure_archive_semantic_runtime():
    required = {
        'pypdf': 'pypdf',
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

# The stable core imported the legacy dedup function at module import time. Replace
# that function object with the ordered pipeline before ``_core.run`` is invoked.
_core.deduplicate_archive_zip = _deduplicate_user_archive

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


def main():
    return _core.main()


if __name__ == '__main__':
    main()
