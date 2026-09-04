import csv, json, shutil
from pathlib import Path

try:
    from .archive_builder import dict_rows_to_xlsx, safe
except ImportError:
    from archive_builder import dict_rows_to_xlsx, safe


def read_csv(path):
    p=Path(path)
    if not p.exists() or p.stat().st_size==0: return []
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))


def _truthy(value):
    return str(value or '').strip().lower() in {'1','true','yes','y'}


def _revision_folder(row):
    status=str(row.get('revision_status') or '').upper()
    if status=='SUPERSEDED_ARCHIVE_ONLY' or not _truthy(row.get('preferred_for_matching')):
        return '02_구판_아카이브'
    return '01_현행_우선판'


def _dest_name(row,src):
    year=str(row.get('publication_year') or row.get('report_year') or '').strip()
    revision=str(row.get('revision_generation') or '').strip()
    part=str(row.get('document_part') or '').strip()
    title=str(row.get('title') or row.get('catalog_id') or src.stem)
    prefix='_'.join(x for x in [year,revision] if x)
    suffix=f'_part{part}' if part and part!='1' else ''
    stem=(prefix+'_' if prefix else '')+title+suffix
    return safe(stem)+'.pdf'


def expose(package_root,archive_root):
    """Expose current and superseded BAT references without conflating them with adoption.

    Resolver applicability remains current/preferred-only. The human archive may retain
    older official revisions for historical comparison, clearly segregated as archive-only.
    """
    package=Path(package_root); archive=Path(archive_root)
    folder=archive/'01_사용자자료'/'07_가이드라인_참고자료'/'BAT_기준서'
    current_folder=folder/'01_현행_우선판'
    superseded_folder=folder/'02_구판_아카이브'
    current_folder.mkdir(parents=True,exist_ok=True)
    superseded_folder.mkdir(parents=True,exist_ok=True)

    candidates=read_csv(package/'BAT_Applicability_Candidates.csv')
    docs=read_csv(package/'output'/'BAT_REFERENCES'/'document_index.csv')
    copied=[]; current_copied=[]; superseded_copied=[]; failures=[]

    for row in docs:
        if row.get('collection_status')!='DOWNLOADED': continue
        raw=str(row.get('stored_path') or '')
        src=Path(raw)
        if not src.is_absolute(): src=package/src
        if not src.exists() or not src.is_file():
            failures.append({'catalog_id':row.get('catalog_id',''),'revision_id':row.get('revision_id',''),
                             'reason':'DOWNLOADED_INDEX_FILE_MISSING','stored_path':raw})
            continue
        if src.suffix.lower()!='.pdf':
            failures.append({'catalog_id':row.get('catalog_id',''),'revision_id':row.get('revision_id',''),
                             'reason':'DOWNLOADED_BAT_NOT_PDF','stored_path':raw})
            continue
        target_root=folder/_revision_folder(row)
        dest=target_root/_dest_name(row,src)
        if not dest.exists(): shutil.copy2(src,dest)
        copied.append(dest)
        if target_root==superseded_folder: superseded_copied.append(dest)
        else: current_copied.append(dest)

    candidate_rows=[]
    for row in candidates:
        candidate_rows.append({
            '사업장':row.get('site_name',''),
            'BAT_Family':row.get('catalog_family',''),
            '현행기준서ID':row.get('catalog_id',''),
            '현행판본':row.get('revision_generation',''),
            '역할':row.get('candidate_role',''),
            '후보상태':row.get('candidate_state',''),
            '적용성근거상태':row.get('applicability_state',''),
            '발간상태':row.get('publication_status',''),
            '법적상태':row.get('legal_status',''),
            '예정일':row.get('effective_from',''),
            '업종근거':row.get('matched_industry_terms',''),
            'KSIC근거':row.get('matched_ksic_prefixes',''),
            '공정근거':row.get('matched_process_terms',''),
            '공통설비근거':row.get('matched_utility_terms',''),
            '근거채널':row.get('evidence_channels',''),
            '근거요약':row.get('evidence_basis',''),
            '수집조치':row.get('collection_action',''),
            '공식출처':row.get('official_source_locator',''),
            '해석경계':'사업장 후보는 preferred/current 판본에 대해서만 생성. 구판 보유는 현행 적용 또는 기업의 BAT 채택을 의미하지 않음',
        })

    doc_rows=[]
    for row in docs:
        doc_rows.append({
            'BAT_Family':row.get('catalog_family',''),
            '기준서ID':row.get('catalog_id',''),
            'Revision_ID':row.get('revision_id',''),
            '판본':row.get('revision_generation',''),
            '발간연도':row.get('publication_year',''),
            '판본상태':row.get('revision_status',''),
            '기본매칭판':row.get('preferred_for_matching',''),
            '문서Part':row.get('document_part',''),
            'Volume':row.get('volume_no',''),
            '문서명':row.get('title',''),
            '수집상태':row.get('collection_status',''),
            '검증상태':row.get('verification_status',''),
            '공식페이지':row.get('source_locator',''),
            '최종URL':row.get('source_url',''),
            '사업장':row.get('site_names',''),
            '역할':row.get('candidate_roles',''),
            '적용성근거상태':row.get('applicability_states',''),
            'Archive구분':_revision_folder(row) if row.get('collection_status')=='DOWNLOADED' else '',
            '비고':row.get('notes','')
        })

    index=folder/'BAT_적용후보_및_수집현황.xlsx'
    dict_rows_to_xlsx(index,[('사업장별 현행후보',candidate_rows),('기준서 판본별 수집현황',doc_rows)])

    return {
        'bat_archive_pdf_count':len(copied),
        'bat_archive_current_pdf_count':len(current_copied),
        'bat_archive_superseded_pdf_count':len(superseded_copied),
        'bat_archive_candidate_count':len(candidate_rows),
        'bat_archive_index':str(index.relative_to(archive)),
        'bat_archive_failures':failures,
        'guideline_reference_present':bool(copied),
        'principle':'Applicability uses preferred/current revisions only. Verified older revisions may be retained in 02_구판_아카이브 for historical comparison and never substitute for a missing current revision or prove company BAT adoption.'
    }


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--package',default='assembled'); ap.add_argument('--archive-root',required=True); a=ap.parse_args()
    print(json.dumps(expose(a.package,a.archive_root),ensure_ascii=False,indent=2))
