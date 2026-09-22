"""Production archive wrapper with BAT references, raw/user separation and fidelity gates."""
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
from envinfo_content_qa import evaluate as _evaluate_envinfo_content_qa
from envinfo_zero_qa_gate import reconcile as _reconcile_envinfo_zero_qa
from envinfo_reference_lane import (
    keep_envinfo_out_of_official_annual_lane,
    provenance_specific_user_guide,
)
from human_archive_site_scope_guard import guard_build_human_excels as _guard_site_scope_excels
from sustainability_korean_delivery_guard import evaluate as _evaluate_korean_annual_delivery
from human_archive_raw_policy import (
    assert_human_archive_raw_separated as _assert_human_archive_raw_separated,
    raw_preservation_stats as _raw_preservation_stats,
    rewrite_human_archive_raw_references as _rewrite_human_archive_raw_references,
    suppress_system_raw_copy as _suppress_system_raw_copy,
)
from requested_scope_candidate_guard import (
    audit_collection_for_requested_scope as _strict_scope_audit,
)

_core.deduplicate_archive_zip = _deduplicate_user_archive
_core.audit_collection_for_requested_scope = _strict_scope_audit
_core.archive_builder.copy_system_raw = _suppress_system_raw_copy
# Apply at source materialization: indexes, coverage and final ZIP agree that
# ENV-INFO attachments are not corporate annual originals.
_core.archive_builder.promote_envinfo_references = keep_envinfo_out_of_official_annual_lane(
    _core.archive_builder.promote_envinfo_references
)
_core.archive_builder.write_user_indexes = provenance_specific_user_guide(
    _core.archive_builder.write_user_indexes
)
# Source collectors preserve company-wide evidence; SITE_SET human review sheets
# must only admit source-native IDs authorized for the requested site. Without
# this guard, an unresolved sibling factory enters user-facing PRTR workbooks.
_core.archive_builder.build_human_excels = _guard_site_scope_excels(
    _core.archive_builder.build_human_excels
)

_BASE_BUILD_ARCHIVE = _core.build_archive


def _build_archive_with_bat(package_root, contract_path=_core.archive_builder.CONTRACT_PATH):
    summary = _BASE_BUILD_ARCHIVE(package_root, contract_path)
    root = Path(package_root).resolve()
    archive_root = root / 'Human_Archive' / summary['archive_root']

    # Inspect delivered, materialized official PDFs, never only the discovery label.
    korean_annual_qa = _evaluate_korean_annual_delivery(root, archive_root)
    summary['sustainability_korean_delivery_qa'] = korean_annual_qa
    checks = dict(summary.get('acceptance_checks') or {})
    checks['sustainability_korean_pdf_fidelity'] = bool(korean_annual_qa.get('pass'))
    summary['acceptance_checks'] = checks
    if not korean_annual_qa.get('pass'):
        (root / 'Archive_Summary.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        raise RuntimeError(
            'Human Archive Korean annual-report acceptance FAILED: '
            + json.dumps(korean_annual_qa.get('failures') or [], ensure_ascii=False)
        )

    profile = json.loads((root / 'Company_Profile.json').read_text(encoding='utf-8')) if (root / 'Company_Profile.json').exists() else {}
    resolved_scope, labels, site_tokens = _core.archive_builder.source_id_scope(root, profile)
    envinfo_ids = (resolved_scope or {}).get('ENVINFO', set())
    envinfo_qa = _evaluate_envinfo_content_qa(
        root,
        archive_root,
        envinfo_ids,
        labels,
        site_tokens,
    )
    envinfo_qa = _reconcile_envinfo_zero_qa(root, envinfo_ids, envinfo_qa)
    summary['envinfo_content_qa'] = envinfo_qa
    checks = dict(summary.get('acceptance_checks') or {})
    checks['envinfo_content_fidelity'] = bool(envinfo_qa.get('pass'))
    summary['acceptance_checks'] = checks
    if not envinfo_qa.get('pass'):
        (root / 'Archive_Summary.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        raise RuntimeError('ENVINFO scoped content QA failed or empty without verified no-data evidence: '
                           + json.dumps(envinfo_qa, ensure_ascii=False))

    _rewrite_human_archive_raw_references(archive_root)
    _assert_human_archive_raw_separated(archive_root)
    raw_preservation = _raw_preservation_stats(root)
    bat = _expose_bat_references(root, archive_root)
    summary['bat_archive'] = bat
    summary['raw_preservation'] = raw_preservation
    summary['system_files'] = 0
    checks = dict(summary.get('acceptance_checks') or {})
    checks['system_raw_absent_from_human_archive'] = True
    if bat.get('guideline_reference_present'):
        checks['guideline_reference_present'] = True
    summary['acceptance_checks'] = checks
    summary['principle'] = (
        '요청범위 사용자 자료와 회사 전체 raw 보존을 분리한다. Human Archive에는 '
        '요청범위의 사람용 자료만 포함하고, collector raw는 최종 전체 패키지 output에 별도 보존한다.'
    )
    (root / 'Archive_Summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    return summary


_core.build_archive = _build_archive_with_bat


def _finalize_archive_manifest_pre_zip(package_root, manifest, archive_summary):
    """Finalize the live archive tree while enforcing raw/user separation."""
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
    _assert_human_archive_raw_separated(archive)
    idx = archive / '00_자료목록'
    shutil.copy2(root / 'Master_Manifest.json', idx / 'Master_Manifest.json')
    for extra in [root / 'Requested_Scope.json', root / 'Analysis_Scope.csv']:
        if extra.exists():
            shutil.copy2(extra, idx / extra.name)

    file_rows = _core.archive_file_index(archive)
    _core.write_csv(
        idx / 'Archive_File_Index.csv',
        file_rows,
        ['path', 'bytes', 'sha256'],
    )
    zip_path = root / 'Human_Archive.zip'
    if zip_path.exists():
        zip_path.unlink()

    final = {
        **archive_summary,
        'archive_files': len(file_rows),
        'zip_path': 'Human_Archive.zip',
        'system_files': 0,
    }
    root.joinpath('Archive_Summary.json').write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    return final


_core.finalize_archive_manifest = _finalize_archive_manifest_pre_zip


def main():
    return _core.main()


if __name__ == '__main__':
    main()
