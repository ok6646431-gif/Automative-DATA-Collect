import argparse, csv, hashlib, json, shutil, tempfile, zipfile
from pathlib import Path

from sustainability_coverage import evaluate as evaluate_sustainability_coverage


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def read_json(path,default=None):
    p=Path(path)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default


def read_csv(path):
    p=Path(path)
    if not p.exists() or p.stat().st_size==0: return []
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))


def write_csv(path,rows,fields):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)


def archive_index(root):
    rows=[]
    for p in sorted(Path(root).rglob('*')):
        if p.is_file() and p.name!='Archive_File_Index.csv':
            rows.append({'path':str(p.relative_to(root)),'bytes':p.stat().st_size,'sha256':sha256(p)})
    return rows


def _find_archive_root(extract_root):
    dirs=[p for p in Path(extract_root).iterdir() if p.is_dir()]
    if len(dirs)!=1:
        raise RuntimeError(f'expected one human-archive root directory, found {len(dirs)}')
    return dirs[0]


def _user_retention_rank(path):
    """Prefer canonical/user-friendly names when exact copies coexist in one folder.

    ENV-INFO promoted copies intentionally carry an ``ENVINFO공개연도_`` provenance
    prefix. When the exact same bytes are also present under a canonical corporate
    document filename in the same user folder, keep the canonical filename and record
    the removed promoted copy. Other ties are deterministic only; content identity is
    always established by SHA-256 before anything is removed.
    """
    p=Path(path)
    promoted=1 if p.name.startswith('ENVINFO공개연도_') else 0
    return (promoted, len(p.name), p.name)


def deduplicate_user_folders(archive_root):
    archive_root=Path(archive_root)
    user=archive_root/'01_사용자자료'
    if not user.exists():
        return {'user_deduplicated_files':0,'user_deduplicated_bytes':0,'user_reference_file':''}

    refs=[]
    for folder in sorted([p for p in user.rglob('*') if p.is_dir()] + [user]):
        files=[p for p in sorted(folder.iterdir()) if p.is_file()]
        if len(files)<2: continue
        by_hash={}
        for p in files:
            by_hash.setdefault(sha256(p),[]).append(p)
        for digest,group in sorted(by_hash.items()):
            if len(group)<2: continue
            retained=sorted(group,key=_user_retention_rank)[0]
            for p in sorted(group,key=_user_retention_rank)[1:]:
                refs.append({
                    'removed_user_path':str(p.relative_to(archive_root)),
                    'retained_user_path':str(retained.relative_to(archive_root)),
                    'bytes':p.stat().st_size,
                    'sha256':digest,
                    'resolution':'IDENTICAL_SHA256_SAME_USER_FOLDER'
                })
                p.unlink()

    ref_path=archive_root/'00_자료목록'/'Deduplicated_User_File_References.csv'
    if refs:
        write_csv(ref_path,refs,['removed_user_path','retained_user_path','bytes','sha256','resolution'])
    return {
        'user_deduplicated_files':len(refs),
        'user_deduplicated_bytes':sum(int(r['bytes']) for r in refs),
        'user_reference_file':str(ref_path.relative_to(archive_root)) if refs else ''
    }


def deduplicate_tree(archive_root):
    archive_root=Path(archive_root)
    user=archive_root/'01_사용자자료'; system=archive_root/'90_시스템원본'
    user_stats=deduplicate_user_folders(archive_root)
    if not user.exists() or not system.exists():
        return {
            'deduplicated_files':user_stats['user_deduplicated_files'],
            'deduplicated_bytes':user_stats['user_deduplicated_bytes'],
            'reference_file':'',
            **user_stats,
        }
    user_by_hash={}
    for p in sorted(user.rglob('*')):
        if not p.is_file(): continue
        digest=sha256(p)
        user_by_hash.setdefault(digest,p)
    refs=[]
    ref_path=system/'Deduplicated_File_References.csv'
    for p in sorted(system.rglob('*')):
        if not p.is_file() or p==ref_path: continue
        digest=sha256(p)
        retained=user_by_hash.get(digest)
        if not retained: continue
        refs.append({
            'removed_system_path':str(p.relative_to(archive_root)),
            'retained_user_path':str(retained.relative_to(archive_root)),
            'bytes':p.stat().st_size,
            'sha256':digest,
            'resolution':'IDENTICAL_SHA256_USER_COPY'
        })
        p.unlink()
    for d in sorted([p for p in system.rglob('*') if p.is_dir()],key=lambda x:len(x.parts),reverse=True):
        try: d.rmdir()
        except OSError: pass
    if refs:
        write_csv(ref_path,refs,['removed_system_path','retained_user_path','bytes','sha256','resolution'])
    system_files=len(refs)
    system_bytes=sum(int(r['bytes']) for r in refs)
    return {
        'deduplicated_files':system_files+user_stats['user_deduplicated_files'],
        'deduplicated_bytes':system_bytes+user_stats['user_deduplicated_bytes'],
        'reference_file':str(ref_path.relative_to(archive_root)) if refs else '',
        **user_stats,
    }


def _user_inventory_rows(archive_root):
    archive_root=Path(archive_root); user=archive_root/'01_사용자자료'; rows=[]
    if not user.exists(): return rows
    for p in sorted(user.rglob('*')):
        if not p.is_file(): continue
        rel=p.relative_to(archive_root)
        rows.append({
            '구분': rel.parts[1] if len(rel.parts)>1 else '',
            '파일명': p.name,
            '상대경로': str(rel),
            '용량_MB': round(p.stat().st_size/1024/1024,3),
        })
    return rows


def _write_user_inventory_xlsx(path,rows):
    try:
        import xlsxwriter
    except Exception as exc:
        raise RuntimeError('xlsxwriter is required to refresh user archive indexes after deduplication') from exc
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    wb=xlsxwriter.Workbook(str(path),{'constant_memory':True})
    ws=wb.add_worksheet('사용자자료')
    header=wb.add_format({'bold':True,'bg_color':'#E7E6E6','border':1,'align':'center','valign':'vcenter'})
    textfmt=wb.add_format({'valign':'top'}); wrap=wb.add_format({'valign':'top','text_wrap':True})
    fields=['구분','파일명','상대경로','용량_MB']
    for c,k in enumerate(fields): ws.write(0,c,k,header)
    for r_idx,row in enumerate(rows,1):
        for c,k in enumerate(fields):
            value=row.get(k,'')
            ws.write(r_idx,c,value,wrap if isinstance(value,str) and len(value)>50 else textfmt)
    ws.freeze_panes(1,0)
    ws.autofilter(0,0,max(1,len(rows)),len(fields)-1)
    widths={'구분':24,'파일명':45,'상대경로':80,'용량_MB':14}
    for c,k in enumerate(fields): ws.set_column(c,c,widths[k])
    wb.close()


def refresh_user_indexes(archive_root):
    """Rebuild user-facing inventory files after post-build duplicate removal.

    Deduplication happens after the initial archive indexes are generated. Without this
    refresh, ``전체자료목록.xlsx`` and ``사용자자료_목록.csv`` can refer to files that
    were correctly removed as exact duplicates. Rebuilding from the actual remaining
    tree keeps the delivered inventory aligned with the ZIP contents.
    """
    archive_root=Path(archive_root); idx=archive_root/'00_자료목록'; idx.mkdir(parents=True,exist_ok=True)
    rows=_user_inventory_rows(archive_root)
    write_csv(idx/'사용자자료_목록.csv',rows,['구분','파일명','상대경로','용량_MB'])
    _write_user_inventory_xlsx(idx/'전체자료목록.xlsx',rows)
    return len(rows)


def _apply_sustainability_coverage(package_root,archive_root,summary):
    package_root=Path(package_root); archive_root=Path(archive_root)
    profile=read_json(package_root/'Company_Profile.json',{}) or {}
    docs=read_csv(package_root/'output'/'CORP_DOCS'/'document_index.csv')
    folder=archive_root/'01_사용자자료'/'04_지속가능경영보고서'
    paths=[p for p in sorted(folder.rglob('*')) if p.is_file()] if folder.exists() else []
    coverage=evaluate_sustainability_coverage(profile,docs,paths)
    checks=dict(summary.get('acceptance_checks') or {})
    checks['sustainability_minimum_5']=bool(coverage['coverage_sufficient'])
    checks['sustainability_coverage_sufficient']=bool(coverage['coverage_sufficient'])
    summary['acceptance_checks']=checks
    blocking=dict(summary.get('blocking_acceptance_checks') or {})
    if blocking:
        blocking['sustainability_minimum_5']=bool(coverage['coverage_sufficient'])
        blocking['sustainability_coverage_sufficient']=bool(coverage['coverage_sufficient'])
    else:
        blocking={k:bool(v) for k,v in checks.items() if k not in {'guideline_reference_present'}}
    summary['blocking_acceptance_checks']=blocking
    summary['sustainability_coverage']=coverage
    summary['archive_completeness']='COMPLETE' if blocking and all(bool(v) for v in blocking.values()) else 'INCOMPLETE'
    return summary


def _sync_metadata(package_root,archive_root,stats):
    package_root=Path(package_root); archive_root=Path(archive_root)
    actual_user_files=refresh_user_indexes(archive_root)
    actual_system_files=sum(1 for p in (archive_root/'90_시스템원본').rglob('*') if p.is_file())

    summary=read_json(package_root/'Archive_Summary.json',{}) or {}
    summary.update(stats)
    summary['user_files']=actual_user_files
    summary['system_files']=actual_system_files
    summary=_apply_sustainability_coverage(package_root,archive_root,summary)
    package_root.joinpath('Archive_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')

    manifest=read_json(package_root/'Master_Manifest.json',{}) or {}
    human=manifest.setdefault('human_archive',{})
    human.update(stats)
    human['user_files']=actual_user_files
    human['system_files']=actual_system_files
    human['archive_completeness']=summary.get('archive_completeness')
    human['acceptance_checks']=summary.get('acceptance_checks') or {}
    human['sustainability_coverage']=summary.get('sustainability_coverage') or {}
    package_root.joinpath('Master_Manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')

    idx=archive_root/'00_자료목록'; idx.mkdir(parents=True,exist_ok=True)
    archive_manifest=read_json(idx/'Archive_Manifest.json',{}) or {}
    archive_manifest.update(stats)
    archive_manifest['user_files']=actual_user_files
    archive_manifest['system_files']=actual_system_files
    archive_manifest['archive_completeness']=summary.get('archive_completeness')
    archive_manifest['acceptance_checks']=summary.get('acceptance_checks') or {}
    archive_manifest['sustainability_coverage']=summary.get('sustainability_coverage') or {}
    (idx/'Archive_Manifest.json').write_text(json.dumps(archive_manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copy2(package_root/'Master_Manifest.json',idx/'Master_Manifest.json')
    system_manifest=archive_root/'90_시스템원본'/'control_plane'/'Master_Manifest.json'
    if system_manifest.parent.exists(): shutil.copy2(package_root/'Master_Manifest.json',system_manifest)

    rows=archive_index(archive_root)
    write_csv(idx/'Archive_File_Index.csv',rows,['path','bytes','sha256'])
    return summary,manifest


def _rewrite_zip(zip_path,archive_root):
    zip_path=Path(zip_path); archive_root=Path(archive_root)
    tmp=zip_path.with_suffix('.dedup.zip')
    if tmp.exists(): tmp.unlink()
    with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(archive_root.rglob('*')):
            if p.is_file(): z.write(p,arcname=str(Path(archive_root.name)/p.relative_to(archive_root)))
    tmp.replace(zip_path)


def _refresh_root_indexes(package_root,zip_path,stats):
    package_root=Path(package_root); zip_path=Path(zip_path)
    summary=read_json(package_root/'Archive_Summary.json',{}) or {}; summary.update(stats)
    summary['zip_bytes']=zip_path.stat().st_size; summary['zip_sha256']=sha256(zip_path)
    package_root.joinpath('Archive_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=read_csv(package_root/'Artifact_Index.csv')
    rel=str(zip_path.relative_to(package_root))
    found=False
    for r in rows:
        if r.get('path')==rel:
            r.update({'source':'HUMAN_ARCHIVE','bytes':zip_path.stat().st_size,'sha256':summary['zip_sha256']}); found=True
    if not found: rows.append({'source':'HUMAN_ARCHIVE','path':rel,'bytes':zip_path.stat().st_size,'sha256':summary['zip_sha256']})
    write_csv(package_root/'Artifact_Index.csv',rows,['source','path','bytes','sha256'])
    return summary


def run(package_root='assembled'):
    package_root=Path(package_root).resolve(); zip_path=package_root/'Human_Archive.zip'
    if not zip_path.exists(): raise FileNotFoundError(zip_path)
    before=zip_path.stat().st_size
    with tempfile.TemporaryDirectory(prefix='human-archive-dedup-') as td:
        with zipfile.ZipFile(zip_path,'r') as z: z.extractall(td)
        archive_root=_find_archive_root(td)
        stats=deduplicate_tree(archive_root)
        _sync_metadata(package_root,archive_root,stats)
        _rewrite_zip(zip_path,archive_root)
    summary=_refresh_root_indexes(package_root,zip_path,stats)
    result={**stats,'zip_bytes_before':before,'zip_bytes_after':zip_path.stat().st_size,'zip_bytes_saved':before-zip_path.stat().st_size,'zip_sha256':summary['zip_sha256']}
    print(json.dumps(result,ensure_ascii=False))
    return result


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--package',default='assembled'); a=ap.parse_args(); run(a.package)


if __name__=='__main__': main()
