import csv, hashlib, json, re, shutil, subprocess
from datetime import datetime, timezone
from pathlib import Path

from requested_scope import company_terms as _company_terms

try:
    import xlsxwriter
except Exception:
    xlsxwriter = None

CONTRACT_PATH = Path(__file__).with_name("archive_contract.json")
ROOT_INDEX_FILES = [
    "Company_Profile.json", "Company_Discovery_Summary.json", "Master_Manifest.json", "Artifact_Index.csv",
    "Site_Master.csv", "Source_Identity.csv", "Coverage_Status.csv", "Coverage_Matrix.csv", "Validation_Queue.csv",
    "Event_Registry.csv", "Coverage_Event_Links.csv", "Analysis_Ready_Index.csv", "REVIEW_REQUIRED.json"
]
USER_ROOT = "01_사용자자료"
SYSTEM_ROOT = "90_시스템원본"


def safe(value):
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', str(value or '')).strip(' ._')
    return text[:160] or '자료'


def read_json(path, default=None):
    p = Path(path)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default


def read_jsonl(path):
    p = Path(path)
    if not p.exists(): return []
    rows=[]
    for line in p.read_text(encoding='utf-8', errors='replace').splitlines():
        if line.strip(): rows.append(json.loads(line))
    return rows


def read_csv(path):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0: return []
    with p.open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))


def write_csv(path, rows, fields=None):
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields=[]
        for row in rows:
            for key in row:
                if key not in fields: fields.append(key)
        if not fields: fields=['value']
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def copy_file(src,dst):
    src=Path(src); dst=Path(dst); dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst); return dst


def unique_copy(src,directory,name=None):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True); src=Path(src)
    target=directory/safe(name or src.name)
    if not target.exists(): return copy_file(src,target)
    if sha256(src)==sha256(target): return target
    suffix=target.suffix; stem=target.stem; n=2
    while True:
        candidate=directory/f"{stem}__{n}{suffix}"
        if not candidate.exists(): return copy_file(src,candidate)
        n+=1


def archive_file_index(archive_root):
    rows=[]
    for p in sorted(Path(archive_root).rglob('*')):
        if p.is_file() and p.name != 'Archive_File_Index.csv':
            rows.append({'path':str(p.relative_to(archive_root)),'bytes':p.stat().st_size,'sha256':sha256(p)})
    return rows


def normalize_site_name(value, profile=None):
    s=str(value or '')
    for pat in [r'주식회사',r'\(주\)',r'㈜',r'사업장',r'공장',r'캠퍼스',r'연구원']:
        s=re.sub(pat,'',s,flags=re.I)
    token=re.sub(r'[^0-9A-Za-z가-힣]','',s).lower()
    for company in _company_terms(profile or {}):
        token=token.replace(company,'')
    return token


def target_site_tokens(profile):
    rows=[]
    for site in profile.get('site_candidates',[]) or []:
        if not isinstance(site,dict): continue
        if site.get('verification_state') not in {'VERIFIED','SOURCE_VERIFIED'}: continue
        if site.get('identity_status') != 'CONFIRMED': continue
        name=str(site.get('site_name_raw') or '').strip(); tok=normalize_site_name(name,profile)
        if name and tok: rows.append((name,tok))
    return rows


def site_is_target(name,tokens,profile=None):
    if not tokens: return True
    raw=normalize_site_name(name,profile)
    return any(tok and (tok in raw or raw in tok) for _,tok in tokens)


def source_id_scope(package_root, profile):
    root=Path(package_root)/'output'; tokens=target_site_tokens(profile)
    scope={k:set() for k in ['ENVINFO','PRTR','CHEM_STATS','CLEANSYS_AIR','SOOSIRO_WATER']}; labels={}
    for r in read_csv(root/'ENVINFO'/'discovery.csv'):
        if site_is_target(r.get('compNm',''),tokens,profile):
            sid=str(r.get('compId') or ''); scope['ENVINFO'].add(sid); labels[('ENVINFO',sid)]=r.get('compNm','')
    for r in read_csv(root/'PRTR'/'discovery.csv'):
        if site_is_target(r.get('company_name_raw',''),tokens,profile):
            sid=str(r.get('entrps_id') or ''); scope['PRTR'].add(sid); labels[('PRTR',sid)]=r.get('company_name_raw','')
    for r in read_csv(root/'CHEM_STATS'/'discovery.csv'):
        if site_is_target(r.get('bplcNm',''),tokens,profile):
            sid=str(r.get('bplcId') or ''); scope['CHEM_STATS'].add(sid); labels[('CHEM_STATS',sid)]=r.get('bplcNm','')
    for r in read_json(root/'CLEANSYS_AIR'/'candidates.json',[]) or []:
        if site_is_target(r.get('company_name_raw',''),tokens,profile):
            sid=str(r.get('fact_code') or ''); scope['CLEANSYS_AIR'].add(sid); labels[('CLEANSYS_AIR',sid)]=r.get('company_name_raw','')
    for r in read_json(root/'SOOSIRO_WATER'/'fact_candidates.json',[]) or []:
        name=r.get('FACT_FNAME') or r.get('FACT_NAME','')
        if site_is_target(name,tokens,profile):
            sid=str(r.get('FACT_CODE') or ''); scope['SOOSIRO_WATER'].add(sid); labels[('SOOSIRO_WATER',sid)]=name
    return scope,labels,tokens


def dict_rows_to_xlsx(path, sheets):
    if xlsxwriter is None: raise RuntimeError('xlsxwriter is required for Archive v2 user-facing Excel exports')
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    wb=xlsxwriter.Workbook(str(path), {'constant_memory': True})
    header=wb.add_format({'bold':True,'bg_color':'#E7E6E6','border':1,'align':'center','valign':'vcenter'})
    textfmt=wb.add_format({'valign':'top'}); wrap=wb.add_format({'valign':'top','text_wrap':True})
    for sheet_name, rows in sheets:
        ws=wb.add_worksheet(safe(sheet_name)[:31]); fields=[]
        for row in rows:
            for k in row:
                if k not in fields: fields.append(k)
        if not fields: fields=['데이터없음']; rows=[{'데이터없음':'해당 조건에서 수집된 행이 없습니다.'}]
        for c,k in enumerate(fields): ws.write(0,c,k,header)
        for r_idx,row in enumerate(rows,1):
            for c,k in enumerate(fields):
                v=row.get(k,'')
                if isinstance(v,(dict,list)): v=json.dumps(v,ensure_ascii=False)
                ws.write(r_idx,c,v,wrap if isinstance(v,str) and len(v)>50 else textfmt)
        ws.freeze_panes(1,0); ws.autofilter(0,0,max(1,len(rows)),len(fields)-1)
        for c,k in enumerate(fields):
            maxlen=max([len(str(k))]+[len(str(row.get(k,''))) for row in rows[:300]])
            ws.set_column(c,c,min(max(maxlen+2,10),42))
    wb.close()


def flatten_cells(rows, id_field):
    out=[]
    for r in rows:
        row={'검색연도':r.get('search_year',''),id_field:r.get('entrps_id') or r.get('bplcId') or '', '테이블번호':r.get('table_index',''),'행번호':r.get('row_index','')}
        for i,v in enumerate(r.get('cells') or [],1): row[f'값{i}']=v
        out.append(row)
    return out


def build_user_excels(package_root, archive_root, scope):
    root=Path(package_root)/'output'; user=Path(archive_root)/USER_ROOT; created=[]
    clean_rows=[r for r in read_jsonl(root/'CLEANSYS_AIR'/'annual_rows.jsonl') if str(r.get('source_fact_code') or r.get('fact_code') or '') in scope['CLEANSYS_AIR']]
    clean_candidates=[r for r in (read_json(root/'CLEANSYS_AIR'/'candidates.json',[]) or []) if str(r.get('fact_code') or '') in scope['CLEANSYS_AIR']]
    p=user/'01_TMS'/'대기_CleanSYS'/'CleanSYS_대기TMS_정리.xlsx'; dict_rows_to_xlsx(p,[('연간데이터',clean_rows),('사업장목록',clean_candidates)]); created.append(p)
    water_annual=[r for r in read_jsonl(root/'SOOSIRO_WATER'/'annual_rows.jsonl') if str(r.get('FACT_CODE') or r.get('source_fact_code') or '') in scope['SOOSIRO_WATER']]
    water_daily=[r for r in read_jsonl(root/'SOOSIRO_WATER'/'daily_rows.jsonl') if str(r.get('FACT_CODE') or r.get('source_fact_code') or '') in scope['SOOSIRO_WATER']]
    water_candidates=[r for r in (read_json(root/'SOOSIRO_WATER'/'fact_candidates.json',[]) or []) if str(r.get('FACT_CODE') or '') in scope['SOOSIRO_WATER']]
    p=user/'01_TMS'/'수질_SOOSIRO'/'SOOSIRO_수질TMS_정리.xlsx'; dict_rows_to_xlsx(p,[('연간데이터',water_annual),('일자료',water_daily),('사업장목록',water_candidates)]); created.append(p)
    prtr_disc=[r for r in read_csv(root/'PRTR'/'discovery.csv') if str(r.get('entrps_id') or '') in scope['PRTR']]
    prtr_detail=[r for r in read_jsonl(root/'PRTR'/'detail_table_rows.jsonl') if str(r.get('entrps_id') or '') in scope['PRTR']]
    p=user/'02_화학물질'/'PRTR_배출이동량'/'PRTR_화학물질배출이동량_정리.xlsx'; dict_rows_to_xlsx(p,[('사업장연도',prtr_disc),('상세데이터',flatten_cells(prtr_detail,'사업장ID'))]); created.append(p)
    chem_disc=[r for r in read_csv(root/'CHEM_STATS'/'discovery.csv') if str(r.get('bplcId') or '') in scope['CHEM_STATS']]
    chem_detail=[r for r in read_jsonl(root/'CHEM_STATS'/'detail_table_rows.jsonl') if str(r.get('bplcId') or '') in scope['CHEM_STATS']]
    p=user/'02_화학물질'/'화학물질통계'/'화학물질통계_정리.xlsx'; dict_rows_to_xlsx(p,[('사업장연도',chem_disc),('상세데이터',flatten_cells(chem_detail,'사업장ID'))]); created.append(p)
    return created


def browser_binary():
    for name in ['google-chrome','google-chrome-stable','chromium','chromium-browser']:
        p=shutil.which(name)
        if p: return p
    return None


def valid_pdf(pdf_path,min_bytes=1000):
    """Judge PDF health from the file itself, not from a subprocess exit code.

    Headless Chrome can exit non-zero (GPU/logging warnings, sandbox quirks in CI)
    even after writing a fully valid PDF, so the exit code alone is not trustworthy.
    A file is treated as a valid PDF when it exists, is large enough, starts with the
    '%PDF-' magic header and ends with an '%%EOF' marker (both required by the PDF
    file-structure spec for a non-truncated file).
    """
    p=Path(pdf_path)
    if not p.exists() or p.stat().st_size<min_bytes: return False
    try:
        with p.open('rb') as f:
            head=f.read(8)
            if not head.startswith(b'%PDF-'): return False
            f.seek(max(0,p.stat().st_size-2048))
            tail=f.read()
    except OSError:
        return False
    return b'%%EOF' in tail


def render_html_pdf(html_path,pdf_path):
    browser=browser_binary()
    if not browser: return False,'no chromium-compatible browser found'
    html_path=Path(html_path).resolve(); pdf_path=Path(pdf_path).resolve(); pdf_path.parent.mkdir(parents=True,exist_ok=True)
    # '--headless=new' (not the legacy '--headless' content-shell mode) is required for
    # correct CJK/complex-script text shaping and font embedding in --print-to-pdf output.
    cmd=[browser,'--headless=new','--disable-gpu','--no-sandbox','--allow-file-access-from-files','--no-pdf-header-footer',f'--print-to-pdf={pdf_path}',html_path.as_uri()]
    try:
        cp=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45,check=False)
        ok=valid_pdf(pdf_path)
        err=''
        if not ok:
            err=cp.stderr.decode('utf-8',errors='replace')[-1000:]
        elif cp.returncode!=0:
            # File is a valid PDF despite a non-zero exit code; keep the warning for visibility.
            err=f'non-zero exit code {cp.returncode} but PDF is valid: '+cp.stderr.decode('utf-8',errors='replace')[-500:]
        return ok,err
    except Exception as exc: return False,f'{type(exc).__name__}: {exc}'


def build_envinfo_user(package_root,archive_root,scope,labels):
    root=Path(package_root); env=root/'output'/'ENVINFO'; user=Path(archive_root)/USER_ROOT/'03_환경정보공개시스템'; created=[]; failures=[]
    profile=read_json(root/'Company_Profile.json',{}) or {}; tokens=target_site_tokens(profile)
    for d in read_csv(env/'discovery.csv'):
        comp=str(d.get('compId') or '')
        if comp not in scope['ENVINFO']: continue
        year=str(d.get('year') or '연도미상'); raw_name=d.get('compNm') or labels.get(('ENVINFO',comp),comp)
        display=next((name for name,tok in tokens if tok and tok in normalize_site_name(raw_name,profile)), raw_name)
        matches=sorted((env/'raw_detail').glob(f'{year}_{safe(comp)}_*.html'))
        if not matches:
            failures.append({'site':display,'year':year,'reason':'raw detail HTML missing'}); continue
        pdf=user/safe(display)/f'환경정보공개_{safe(display)}_{year}.pdf'
        ok,err=render_html_pdf(matches[0],pdf)
        if ok: created.append(pdf)
        else: failures.append({'site':display,'year':year,'reason':err})
    for att in read_csv(env/'attachment_index.csv'):
        comp=str(att.get('compId') or '')
        if comp not in scope['ENVINFO'] or att.get('collection_status')!='DOWNLOADED': continue
        src=root/str(att.get('stored_path') or '')
        if not src.exists(): continue
        raw_name=att.get('compNm') or labels.get(('ENVINFO',comp),comp); display=next((name for name,tok in tokens if tok and tok in normalize_site_name(raw_name,profile)),raw_name)
        year=str(att.get('year') or '연도미상')
        created.append(unique_copy(src,user/safe(display)/'첨부자료',f'{year}_{att.get("original_filename") or src.name}'))
    return created,failures


REVIEW_REPORT_FILES=[
    ('Environmental_Review_Brief.pdf', True),
    ('Environmental_Review_Evidence.xlsx', True),
    ('Environmental_Review_Brief.html', False),
    ('Environmental_Review_Summary.json', False),
]


def build_review_report_user(package_root,archive_root,company_name):
    """Copy the automated human review report into the front of the user-facing archive.

    The report is generated at the package root (see orchestrator/review_report.py) but
    build_archive() never copied it into Human_Archive.zip, so users opening the archive
    never saw it. This puts the PDF/XLSX (and HTML/JSON for traceability) at
    01_사용자자료/00_환경관리검토/, ahead of raw source folders, without removing the
    root-level originals (90_시스템원본 stays company-wide/raw).
    """
    root=Path(package_root); folder=Path(archive_root)/USER_ROOT/'00_환경관리검토'; created=[]; found_pdf=False
    for name,required in REVIEW_REPORT_FILES:
        src=root/name
        if not src.exists(): continue
        created.append(unique_copy(src,folder,f'{safe(company_name)}_{name}'))
        if name.endswith('.pdf'): found_pdf=True
    return created,found_pdf


def doc_user_folder(dtype,title=''):
    if dtype=='SUSTAINABILITY_REPORT': return '04_지속가능경영보고서'
    if dtype in {'ANNUAL_REPORT','BUSINESS_REPORT','ENVIRONMENTAL_DISCLOSURE','CORPORATE_EVENT'}: return '05_사업보고서_공시'
    if dtype in {'ENVIRONMENTAL_POLICY','ENVIRONMENT_POLICY'}: return '06_회사환경정책/환경경영'
    if dtype in {'CHEMICAL_POLICY'} or '화학' in title or '유해물질' in title or '관리물질' in title: return '06_회사환경정책/화학물질관리'
    if dtype in {'CLIMATE_ENERGY_POLICY','ENVIRONMENT_STRATEGY'}: return '06_회사환경정책/기후에너지'
    if dtype in {'SHE_POLICY'} or '안전보건' in title: return '06_회사환경정책/환경안전보건'
    if dtype in {'GUIDELINE'}: return '07_가이드라인_참고자료/업종별_가이드라인'
    if dtype in {'BAT_REFERENCE'}: return '07_가이드라인_참고자료/BAT_기준서'
    if dtype in {'REGULATION_REFERENCE'}: return '07_가이드라인_참고자료/법령_제도'
    if 'ISO' in title or '인증' in title: return '06_회사환경정책/인증_ISO'
    return '06_회사환경정책/기타_공식자료'


def build_corporate_user(package_root,archive_root,company_name):
    root=Path(package_root); user=Path(archive_root)/USER_ROOT; docs=root/'output'/'CORP_DOCS'; created=[]; rows=[]
    for doc in read_csv(docs/'document_index.csv'):
        if doc.get('collection_status')!='DOWNLOADED': rows.append(doc); continue
        src=root/str(doc.get('stored_path') or '')
        if not src.exists(): rows.append(doc); continue
        dtype=str(doc.get('document_type') or 'OTHER_OFFICIAL_DOCUMENT'); title=str(doc.get('title') or '')
        folder=user/doc_user_folder(dtype,title); year=str(doc.get('report_year') or '')
        suffix=src.suffix or Path(str(doc.get('original_filename') or '')).suffix
        if dtype=='SUSTAINABILITY_REPORT' and year: name=f'{safe(company_name)}_지속가능경영보고서_{year}{suffix}'
        elif year: name=f'{year}_{safe(title or doc.get("original_filename") or src.name)}{suffix if suffix and not str(title).lower().endswith(suffix.lower()) else ""}'
        else: name=doc.get('original_filename') or f'{safe(title)}{suffix}'
        copied=unique_copy(src,folder,name); created.append(copied)
        x=dict(doc); x['user_archive_path']=str(copied.relative_to(archive_root)); rows.append(x)
    return created,rows


def copy_system_raw(package_root,archive_root):
    root=Path(package_root); system=Path(archive_root)/SYSTEM_ROOT; out=root/'output'
    if out.exists():
        for src in out.iterdir():
            if src.is_dir(): shutil.copytree(src,system/src.name,dirs_exist_ok=True)
    cp=system/'control_plane'; cp.mkdir(parents=True,exist_ok=True)
    for name in ROOT_INDEX_FILES+['Integration_Summary.json','Archive_Summary.json']+[n for n,_ in REVIEW_REPORT_FILES]:
        p=root/name
        if p.exists(): copy_file(p,cp/name)


def write_user_indexes(package_root,archive_root,documents,env_failures):
    archive_root=Path(archive_root); user=archive_root/USER_ROOT; idx=archive_root/'00_자료목록'; idx.mkdir(parents=True,exist_ok=True)
    file_rows=[]
    for p in sorted(user.rglob('*')):
        if p.is_file(): file_rows.append({'구분':p.parts[len(archive_root.parts)+1] if len(p.parts)>len(archive_root.parts)+1 else '', '파일명':p.name, '상대경로':str(p.relative_to(archive_root)), '용량_MB':round(p.stat().st_size/1024/1024,3)})
    dict_rows_to_xlsx(idx/'전체자료목록.xlsx',[('사용자자료',file_rows)])
    review_rows=read_csv(Path(package_root)/'Validation_Queue.csv'); rr=read_json(Path(package_root)/'REVIEW_REQUIRED.json',[]) or []
    if rr:
        review_rows += [{k:(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v) for k,v in r.items()} for r in rr if isinstance(r,dict)]
    if env_failures:
        review_rows += [{'issue_type':'ENVINFO_PDF_RENDER_FAILED','object_key':f"{x['site']} {x['year']}",'severity':'MEDIUM','status':'REVIEW_REQUIRED','evidence':x['reason']} for x in env_failures]
    dict_rows_to_xlsx(idx/'확인필요_REVIEW_REQUIRED.xlsx',[('검토필요',review_rows)])
    write_csv(idx/'사용자자료_목록.csv',file_rows,['구분','파일명','상대경로','용량_MB'])
    (idx/'README_먼저읽기.txt').write_text(
        'Archive v2 사용 안내\n\n1) 평소에는 01_사용자자료만 확인하면 됩니다.\n2) HTML/JSON/JSONL/실행로그 등 재현·개발용 원본은 90_시스템원본에 분리했습니다.\n3) 지속가능경영보고서처럼 연도별 1개인 문서는 연도 폴더 없이 한 폴더에 파일명으로 연도를 표시합니다.\n4) 00_자료목록의 전체자료목록.xlsx와 확인필요_REVIEW_REQUIRED.xlsx를 먼저 확인하십시오.\n',encoding='utf-8')
    return file_rows


def build_archive(package_root,contract_path=CONTRACT_PATH):
    package_root=Path(package_root).resolve(); profile=read_json(package_root/'Company_Profile.json',{}) or {}
    company_name=str(profile.get('company_display_name') or profile.get('company_input') or '기업')
    company_id=str(profile.get('company_id') or (read_json(package_root/'Integration_Summary.json',{}) or {}).get('company_id') or '')
    base=package_root/'Human_Archive'; archive_root=base/(safe(company_name)+'_환경자료')
    if base.exists(): shutil.rmtree(base)
    archive_root.mkdir(parents=True,exist_ok=True)
    scope,labels,tokens=source_id_scope(package_root,profile)
    excels=build_user_excels(package_root,archive_root,scope)
    review_created,review_pdf_present=build_review_report_user(package_root,archive_root,company_name)
    env_created,env_failures=build_envinfo_user(package_root,archive_root,scope,labels)
    docs_created,document_rows=build_corporate_user(package_root,archive_root,company_name)
    copy_system_raw(package_root,archive_root)
    user_files=write_user_indexes(package_root,archive_root,document_rows,env_failures)
    sustainability=[p for p in docs_created if '04_지속가능경영보고서' in str(p)]; policy=[p for p in docs_created if '06_회사환경정책' in str(p)]; guides=[p for p in docs_created if '07_가이드라인_참고자료' in str(p)]
    expected_env=sum(1 for r in read_csv(package_root/'output'/'ENVINFO'/'discovery.csv') if str(r.get('compId') or '') in scope['ENVINFO'])
    checks={'user_excel_exports':len(excels)>=4,'envinfo_pdf_complete':len([p for p in env_created if str(p).lower().endswith('.pdf')])>=expected_env if expected_env else True,'sustainability_minimum_5':len(sustainability)>=5,'public_policy_present':len(policy)>=1,'guideline_reference_present':len(guides)>=1,'review_report_present':review_pdf_present}
    completeness='COMPLETE' if all(checks.values()) else 'INCOMPLETE'; idx=archive_root/'00_자료목록'
    manifest={'schema_version':'2.0','company_id':company_id,'company_display_name':company_name,'created_at':datetime.now(timezone.utc).isoformat(),'archive_root':archive_root.name,'archive_completeness':completeness,'acceptance_checks':checks,'target_site_tokens':[x[0] for x in tokens],'target_source_ids':{k:sorted(v) for k,v in scope.items()},'user_files':len(user_files),'system_files':sum(1 for p in (archive_root/SYSTEM_ROOT).rglob('*') if p.is_file()),'xlsx_exports':len(excels),'envinfo_pdf_failures':env_failures,'principle':'01_사용자자료만으로 조사·비교가 가능해야 하며, 재현용 raw 자료는 90_시스템원본에 격리한다.'}
    (idx/'Archive_Manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    file_rows=archive_file_index(archive_root); write_csv(idx/'Archive_File_Index.csv',file_rows,['path','bytes','sha256'])
    zip_path=Path(shutil.make_archive(str(package_root/'Human_Archive'),'zip',root_dir=base,base_dir=archive_root.name)).resolve()
    summary={**manifest,'archive_files':len(file_rows),'zip_path':str(zip_path.relative_to(package_root)),'zip_bytes':zip_path.stat().st_size,'zip_sha256':sha256(zip_path),'downloaded_documents':sum(1 for d in document_rows if d.get('collection_status')=='DOWNLOADED'),'core_documents':sum(1 for d in document_rows if d.get('collection_status')=='DOWNLOADED' and d.get('importance')=='CORE'),'coverage_rows':0}
    (package_root/'Archive_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8'); return summary


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('package_root',nargs='?',default='assembled'); args=ap.parse_args()
    print(json.dumps(build_archive(args.package_root),ensure_ascii=False,indent=2))
