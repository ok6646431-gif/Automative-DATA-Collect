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


def expose(package_root,archive_root):
    """Expose BAT references without conflating candidates with adopted techniques.

    Downloaded, byte-verified official BAT PDFs are copied once to the human BAT
    reference folder. All site/BAT candidates, including future or unpublished ones,
    are represented in an XLSX index so missing publications are never replaced by
    placeholder PDFs.
    """
    package=Path(package_root); archive=Path(archive_root)
    folder=archive/'01_사용자자료'/'07_가이드라인_참고자료'/'BAT_기준서'
    folder.mkdir(parents=True,exist_ok=True)
    candidates=read_csv(package/'BAT_Applicability_Candidates.csv')
    docs=read_csv(package/'output'/'BAT_REFERENCES'/'document_index.csv')
    copied=[]; failures=[]

    for row in docs:
        if row.get('collection_status')!='DOWNLOADED': continue
        raw=str(row.get('stored_path') or '')
        src=Path(raw)
        if not src.is_absolute(): src=package/src
        if not src.exists() or not src.is_file():
            failures.append({'catalog_id':row.get('catalog_id',''),'reason':'DOWNLOADED_INDEX_FILE_MISSING','stored_path':raw})
            continue
        if src.suffix.lower()!='.pdf':
            failures.append({'catalog_id':row.get('catalog_id',''),'reason':'DOWNLOADED_BAT_NOT_PDF','stored_path':raw})
            continue
        dest=folder/(safe(row.get('title') or row.get('catalog_id') or src.stem)+'.pdf')
        if not dest.exists(): shutil.copy2(src,dest)
        copied.append(dest)

    candidate_rows=[]
    for row in candidates:
        candidate_rows.append({
            '사업장':row.get('site_name',''),
            '기준서ID':row.get('catalog_id',''),
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
            '해석경계':'후보/기준서 확보는 해당 기업이 해당 BAT 기술을 실제 적용한다는 증거가 아님',
        })
    doc_rows=[]
    for row in docs:
        doc_rows.append({
            '기준서ID':row.get('catalog_id',''),'문서명':row.get('title',''),'수집상태':row.get('collection_status',''),
            '검증상태':row.get('verification_status',''),'공식페이지':row.get('source_locator',''),
            '최종URL':row.get('source_url',''),'사업장':row.get('site_names',''),'역할':row.get('candidate_roles',''),
            '적용성근거상태':row.get('applicability_states',''),'비고':row.get('notes','')
        })
    index=folder/'BAT_적용후보_및_수집현황.xlsx'
    dict_rows_to_xlsx(index,[('사업장별 후보',candidate_rows),('기준서 수집현황',doc_rows)])

    return {
        'bat_archive_pdf_count':len(copied),
        'bat_archive_candidate_count':len(candidate_rows),
        'bat_archive_index':str(index.relative_to(archive)),
        'bat_archive_failures':failures,
        'guideline_reference_present':bool(copied),
        'principle':'Downloaded official BAT PDFs are references. Candidate mapping and document possession do not prove company BAT adoption.'
    }


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--package',default='assembled'); ap.add_argument('--archive-root',required=True); a=ap.parse_args()
    print(json.dumps(expose(a.package,a.archive_root),ensure_ascii=False,indent=2))
