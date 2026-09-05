import csv, json, shutil
from collections import defaultdict
from pathlib import Path

try:
    from .archive_builder import dict_rows_to_xlsx, safe
except ImportError:
    from archive_builder import dict_rows_to_xlsx, safe


BAT_ROOT_NAME = '02_BAT_참고자료'
BAT_INDEX_NAME = '00_BAT_적용후보_및_수집현황.xlsx'
BAT_DOCUMENTS_DIR = '01_BAT_원문'
BAT_SITE_MAPS_DIR = '02_사업장별_적용맵'
CURRENT_DIR = '01_현행_우선판'
SUPERSEDED_DIR = '02_구판_아카이브'


def read_csv(path):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def _truthy(value):
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'y'}


def _revision_folder(row):
    status = str(row.get('revision_status') or '').upper()
    if status == 'SUPERSEDED_ARCHIVE_ONLY' or not _truthy(row.get('preferred_for_matching')):
        return SUPERSEDED_DIR
    return CURRENT_DIR


def _dest_name(row, src):
    year = str(row.get('publication_year') or row.get('report_year') or '').strip()
    revision = str(row.get('revision_generation') or '').strip()
    part = str(row.get('document_part') or '').strip()
    title = str(row.get('title') or row.get('catalog_id') or src.stem)
    prefix = '_'.join(x for x in [year, revision] if x)
    suffix = f'_part{part}' if part and part != '1' else ''
    stem = (prefix + '_' if prefix else '') + title + suffix
    return safe(stem) + '.pdf'


def _family_folder_names(candidates, docs):
    titles = defaultdict(list)
    for row in docs:
        family = str(row.get('catalog_family') or '').strip()
        title = str(row.get('title') or '').strip()
        if family and title:
            preferred = _truthy(row.get('preferred_for_matching'))
            titles[family].append((0 if preferred else 1, title))
    families = {
        str(row.get('catalog_family') or '').strip()
        for row in [*candidates, *docs]
        if str(row.get('catalog_family') or '').strip()
    }
    result = {}
    for family in sorted(families):
        display = ''
        if titles.get(family):
            display = sorted(titles[family], key=lambda x: (x[0], x[1]))[0][1]
        label = safe(f'{family}_{display}' if display else family)
        result[family] = label or safe(family) or 'BAT_FAMILY'
    return result


def _candidate_row(row, family_folder=''):
    return {
        '사업장': row.get('site_name', ''),
        'BAT_Family': row.get('catalog_family', ''),
        '현행기준서ID': row.get('catalog_id', ''),
        '현행판본': row.get('revision_generation', ''),
        '역할': row.get('candidate_role', ''),
        '후보상태': row.get('candidate_state', ''),
        '적용성근거상태': row.get('applicability_state', ''),
        '발간상태': row.get('publication_status', ''),
        '법적상태': row.get('legal_status', ''),
        '예정일': row.get('effective_from', ''),
        '업종근거': row.get('matched_industry_terms', ''),
        'KSIC근거': row.get('matched_ksic_prefixes', ''),
        '공정근거': row.get('matched_process_terms', ''),
        '공통설비근거': row.get('matched_utility_terms', ''),
        '근거채널': row.get('evidence_channels', ''),
        '근거요약': row.get('evidence_basis', ''),
        '수집조치': row.get('collection_action', ''),
        '공식출처': row.get('official_source_locator', ''),
        'BAT원문폴더': f'{BAT_DOCUMENTS_DIR}/{family_folder}' if family_folder else '',
        '해석경계': '사업장 후보는 preferred/current 판본에 대해서만 생성. 구판 보유는 현행 적용 또는 기업의 BAT 채택을 의미하지 않음',
    }


def _document_row(row, family_folder=''):
    archive_bucket = _revision_folder(row) if row.get('collection_status') == 'DOWNLOADED' else ''
    archive_path = ''
    if archive_bucket and family_folder:
        archive_path = f'{BAT_DOCUMENTS_DIR}/{family_folder}/{archive_bucket}'
    return {
        'BAT_Family': row.get('catalog_family', ''),
        '기준서ID': row.get('catalog_id', ''),
        'Revision_ID': row.get('revision_id', ''),
        '판본': row.get('revision_generation', ''),
        '발간연도': row.get('publication_year', ''),
        '판본상태': row.get('revision_status', ''),
        '기본매칭판': row.get('preferred_for_matching', ''),
        '문서Part': row.get('document_part', ''),
        'Volume': row.get('volume_no', ''),
        '문서명': row.get('title', ''),
        '수집상태': row.get('collection_status', ''),
        '검증상태': row.get('verification_status', ''),
        '공식페이지': row.get('source_locator', ''),
        '최종URL': row.get('source_url', ''),
        '사업장': row.get('site_names', ''),
        '역할': row.get('candidate_roles', ''),
        '적용성근거상태': row.get('applicability_states', ''),
        'Archive구분': archive_bucket,
        'Archive원문폴더': archive_path,
        '비고': row.get('notes', ''),
    }


def expose(package_root, archive_root):
    """Expose BAT as a dedicated reference archive, separate from company evidence.

    BAT PDFs are stored once per BAT family/revision. Site folders contain only XLSX
    applicability maps that point to the shared BAT source folders, preventing duplicate
    document bytes across sites. Applicability remains current/preferred-only; older
    revisions are historical reference material and never substitute for a missing current
    revision or prove company adoption.
    """
    package = Path(package_root)
    archive = Path(archive_root)

    # Remove the legacy location if an archive tree is rebuilt in place. New BAT output is
    # a sibling of 01_사용자자료, not a subsection of company/public evidence.
    legacy = archive / '01_사용자자료' / '07_가이드라인_참고자료' / 'BAT_기준서'
    if legacy.exists():
        shutil.rmtree(legacy)

    folder = archive / BAT_ROOT_NAME
    docs_root = folder / BAT_DOCUMENTS_DIR
    maps_root = folder / BAT_SITE_MAPS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    docs_root.mkdir(parents=True, exist_ok=True)
    maps_root.mkdir(parents=True, exist_ok=True)

    candidates = read_csv(package / 'BAT_Applicability_Candidates.csv')
    docs = read_csv(package / 'output' / 'BAT_REFERENCES' / 'document_index.csv')
    family_folders = _family_folder_names(candidates, docs)

    copied = []
    current_copied = []
    superseded_copied = []
    failures = []
    copied_by_family = defaultdict(list)

    for row in docs:
        if row.get('collection_status') != 'DOWNLOADED':
            continue
        raw = str(row.get('stored_path') or '')
        src = Path(raw)
        if not src.is_absolute():
            src = package / src
        if not src.exists() or not src.is_file():
            failures.append({
                'catalog_id': row.get('catalog_id', ''),
                'revision_id': row.get('revision_id', ''),
                'reason': 'DOWNLOADED_INDEX_FILE_MISSING',
                'stored_path': raw,
            })
            continue
        if src.suffix.lower() != '.pdf':
            failures.append({
                'catalog_id': row.get('catalog_id', ''),
                'revision_id': row.get('revision_id', ''),
                'reason': 'DOWNLOADED_BAT_NOT_PDF',
                'stored_path': raw,
            })
            continue

        family = str(row.get('catalog_family') or '').strip() or 'BAT_FAMILY'
        family_folder = family_folders.get(family, safe(family))
        revision_folder = _revision_folder(row)
        target_root = docs_root / family_folder / revision_folder
        target_root.mkdir(parents=True, exist_ok=True)
        dest = target_root / _dest_name(row, src)
        if not dest.exists():
            shutil.copy2(src, dest)
        copied.append(dest)
        copied_by_family[family].append(dest)
        if revision_folder == SUPERSEDED_DIR:
            superseded_copied.append(dest)
        else:
            current_copied.append(dest)

    candidate_rows = [
        _candidate_row(row, family_folders.get(str(row.get('catalog_family') or '').strip(), ''))
        for row in candidates
    ]
    doc_rows = [
        _document_row(row, family_folders.get(str(row.get('catalog_family') or '').strip(), ''))
        for row in docs
    ]

    index = folder / BAT_INDEX_NAME
    dict_rows_to_xlsx(index, [
        ('사업장별 현행후보', candidate_rows),
        ('기준서 판본별 수집현황', doc_rows),
    ])

    site_maps = []
    candidates_by_site = defaultdict(list)
    for raw, human in zip(candidates, candidate_rows):
        site = str(raw.get('site_name') or '').strip() or '사업장미확인'
        candidates_by_site[site].append((raw, human))

    for site in sorted(candidates_by_site):
        pairs = candidates_by_site[site]
        site_candidate_rows = [human for _, human in pairs]
        site_families = {
            str(raw.get('catalog_family') or '').strip()
            for raw, _ in pairs
            if str(raw.get('catalog_family') or '').strip()
        }
        site_doc_rows = [
            _document_row(row, family_folders.get(str(row.get('catalog_family') or '').strip(), ''))
            for row in docs
            if str(row.get('catalog_family') or '').strip() in site_families
        ]
        target = maps_root / f'{safe(site)}_BAT_적용맵.xlsx'
        dict_rows_to_xlsx(target, [
            ('BAT 후보', site_candidate_rows),
            ('관련 기준서 판본', site_doc_rows),
        ])
        site_maps.append(target)

    return {
        'bat_archive_root': BAT_ROOT_NAME,
        'bat_archive_pdf_count': len(copied),
        'bat_archive_current_pdf_count': len(current_copied),
        'bat_archive_superseded_pdf_count': len(superseded_copied),
        'bat_archive_candidate_count': len(candidate_rows),
        'bat_archive_site_map_count': len(site_maps),
        'bat_archive_family_count': len({str(r.get('catalog_family') or '').strip() for r in candidates if str(r.get('catalog_family') or '').strip()}),
        'bat_archive_index': str(index.relative_to(archive)),
        'bat_archive_site_maps': [str(p.relative_to(archive)) for p in site_maps],
        'bat_archive_failures': failures,
        'guideline_reference_present': bool(copied),
        'principle': 'BAT is delivered as a separate reference area. PDFs are stored once per family/revision and site maps reference shared originals. Applicability uses preferred/current revisions only; older revisions are historical reference and never prove company BAT adoption.',
    }


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--package', default='assembled')
    ap.add_argument('--archive-root', required=True)
    a = ap.parse_args()
    print(json.dumps(expose(a.package, a.archive_root), ensure_ascii=False, indent=2))
