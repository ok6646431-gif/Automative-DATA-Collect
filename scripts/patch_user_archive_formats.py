from pathlib import Path

p = Path('orchestrator/archive_builder.py')
s = p.read_text(encoding='utf-8')

old_review = """    for name,required in REVIEW_REPORT_FILES:\n        src=root/name\n        if not src.exists(): continue\n        created.append(unique_copy(src,folder,f'{safe(company_name)}_{name}'))\n        if name.endswith('.pdf'): found_pdf=True\n"""
new_review = """    for name,required in REVIEW_REPORT_FILES:\n        # HTML/JSON companions remain in 90_시스템원본. The user layer exposes only\n        # finished review artifacts (PDF/XLSX).\n        if not required: continue\n        src=root/name\n        if not src.exists(): continue\n        created.append(unique_copy(src,folder,f'{safe(company_name)}_{name}'))\n        if name.endswith('.pdf'): found_pdf=True\n"""
if old_review not in s:
    raise SystemExit('review block not found')
s = s.replace(old_review, new_review, 1)

anchor = """def build_envinfo_user(package_root,archive_root,scope,labels):\n"""
render_url = '''def render_url_pdf(url,pdf_path):\n    """Render a verified official web URL for the user layer.\n\n    Saved HTML remains in 90_시스템원본 for reproducibility, but many modern pages\n    require live CSS/JS/assets to be human-readable. A broken local-HTML render is\n    never promoted merely because it has a PDF extension.\n    """\n    browser=browser_binary()\n    if not browser: return False,'no chromium-compatible browser found'\n    pdf_path=Path(pdf_path).resolve(); pdf_path.parent.mkdir(parents=True,exist_ok=True)\n    cmd=[browser,'--headless=new','--disable-gpu','--no-sandbox','--no-pdf-header-footer','--virtual-time-budget=12000',f'--print-to-pdf={pdf_path}',str(url)]\n    try:\n        cp=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=75,check=False)\n        ok=valid_pdf(pdf_path)\n        err=''\n        if not ok:\n            err=cp.stderr.decode('utf-8',errors='replace')[-1000:]\n        elif cp.returncode!=0:\n            err=f'non-zero exit code {cp.returncode} but PDF is valid: '+cp.stderr.decode('utf-8',errors='replace')[-500:]\n        return ok,err\n    except Exception as exc: return False,f'{type(exc).__name__}: {exc}'\n\n\n'''
if 'def render_url_pdf(' not in s:
    if anchor not in s:
        raise SystemExit('ENVINFO anchor not found')
    s = s.replace(anchor, render_url + anchor, 1)

old_corp = """        suffix=src.suffix or Path(str(doc.get('original_filename') or '')).suffix\n        if dtype=='SUSTAINABILITY_REPORT' and year: name=f'{safe(company_name)}_지속가능경영보고서_{year}{suffix}'\n        elif year: name=f'{year}_{safe(title or doc.get(\"original_filename\") or src.name)}{suffix if suffix and not str(title).lower().endswith(suffix.lower()) else \"\"}'\n        else: name=doc.get('original_filename') or f'{safe(title)}{suffix}'\n        copied=unique_copy(src,folder,name); created.append(copied)\n        x=dict(doc); x['user_archive_path']=str(copied.relative_to(archive_root)); rows.append(x)\n"""
new_corp = """        suffix=src.suffix or Path(str(doc.get('original_filename') or '')).suffix\n        source_for_user=src; rendered_tmp=None\n        if str(suffix).lower() in {'.html','.htm'}:\n            rendered_tmp=root/f'.user_render_{sha256(src)[:16]}.pdf'\n            source_url=str(doc.get('source_url') or '').strip()\n            if source_url.startswith(('https://','http://')):\n                ok,err=render_url_pdf(source_url,rendered_tmp)\n            else:\n                ok,err=render_html_pdf(src,rendered_tmp)\n            if not ok:\n                x=dict(doc); x['user_archive_status']='PDF_RENDER_FAILED'; x['user_archive_error']=err; rows.append(x)\n                if rendered_tmp.exists(): rendered_tmp.unlink()\n                continue\n            source_for_user=rendered_tmp; suffix='.pdf'\n        if dtype=='SUSTAINABILITY_REPORT' and year:\n            name=f'{safe(company_name)}_지속가능경영보고서_{year}{suffix}'\n        elif year:\n            base_title=safe(title or doc.get('original_filename') or src.name)\n            name=f'{year}_{base_title}{suffix if suffix and not str(base_title).lower().endswith(suffix.lower()) else \"\"}'\n        else:\n            raw_name=str(doc.get('original_filename') or safe(title) or src.name)\n            name=f'{safe(Path(raw_name).stem)}{suffix}' if rendered_tmp is not None else raw_name\n        copied=unique_copy(source_for_user,folder,name); created.append(copied)\n        if rendered_tmp is not None and rendered_tmp.exists(): rendered_tmp.unlink()\n        x=dict(doc); x['user_archive_path']=str(copied.relative_to(archive_root)); rows.append(x)\n"""
if old_corp not in s:
    raise SystemExit('corporate block not found')
s = s.replace(old_corp, new_corp, 1)

old_checks = """    checks={'user_excel_exports':len(excels)>=4,'envinfo_pdf_complete':len([p for p in env_created if str(p).lower().endswith('.pdf')])>=expected_env if expected_env else True,'sustainability_minimum_5':distinct_file_count(sustainability)>=5,'public_policy_present':len(policy)>=1,'guideline_reference_present':len(guides)>=1,'review_report_present':review_pdf_present}\n"""
new_checks = """    forbidden_user_suffixes={'.html','.htm','.json','.jsonl'}\n    user_machine_formats_absent=not any(p.is_file() and p.suffix.lower() in forbidden_user_suffixes for p in (archive_root/USER_ROOT).rglob('*'))\n    checks={'user_excel_exports':len(excels)>=4,'envinfo_pdf_complete':len([p for p in env_created if str(p).lower().endswith('.pdf')])>=expected_env if expected_env else True,'sustainability_minimum_5':distinct_file_count(sustainability)>=5,'public_policy_present':len(policy)>=1,'guideline_reference_present':len(guides)>=1,'review_report_present':review_pdf_present,'user_machine_formats_absent':user_machine_formats_absent}\n"""
if old_checks not in s:
    raise SystemExit('checks block not found')
s = s.replace(old_checks, new_checks, 1)

p.write_text(s, encoding='utf-8')
print('patched', p)
