"""Compatibility wrapper for the archive stage with BAT reference delivery.

The stable archive implementation is preserved in ``archive_stage_core``. This
wrapper adds only the BAT human-delivery hook after the normal archive tree is built
and before normalization/final acceptance. A downloaded BAT remains a technical
reference; candidate mapping never proves company adoption.

The user-archive dedup stage performs strict PDF render-structure comparison for
same-year sustainability-report copies. ``pypdf`` is therefore an archive-stage
runtime dependency. Legacy collection workflows did not install it explicitly, so
this compatibility wrapper bootstraps the dependency before importing the stable
archive core. Installation failure is fatal rather than silently disabling semantic
deduplication.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _ensure_pdf_semantic_runtime():
    if importlib.util.find_spec('pypdf') is not None:
        return
    subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', 'pypdf'],
        check=True,
    )
    if importlib.util.find_spec('pypdf') is None:
        raise RuntimeError('pypdf installation completed but module is still unavailable')


_ensure_pdf_semantic_runtime()

import archive_stage_core as _core
from archive_stage_core import *  # preserve public helper contract
from bat_archive import expose as _expose_bat_references

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
