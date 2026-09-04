import csv, hashlib, json, re
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

try:
    from .bat_resolver import CATALOG_PATH, read_json, read_csv
except ImportError:
    from bat_resolver import CATALOG_PATH, read_json, read_csv

INDEX_FIELDS=[
    'document_id','catalog_id','catalog_family','revision_generation','document_part','document_type','title','report_year',
    'source_url','source_locator','stored_path','collection_status','verification_status','importance','candidate_roles',
    'candidate_states','applicability_states','canonical_site_ids','site_names','reference_domains','notes'
]

OFFICIAL_PDF_HOST_SUFFIXES=(
    'ieps.nier.go.kr','nier.go.kr','me.go.kr','mcee.go.kr','korea.kr'
)


def safe(value):
    text=re.sub(r'[\\/:*?"<>|\x00-\x1f]+','_',str(value or '')).strip(' ._')
    return text[:180] or 'BAT_reference'


def write_csv(path,rows,fields):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)


def sha256_bytes(data): return hashlib.sha256(data).hexdigest()


def _official_host(url):
    host=(urlparse(str(url or '')).hostname or '').lower()
    return bool(host and any(host==suffix or host.endswith('.'+suffix) for suffix in OFFICIAL_PDF_HOST_SUFFIXES))


def _assert_official_url(url):
    if not str(url or '').startswith(('https://','http://')) or not _official_host(url):
        raise RuntimeError(f'BAT document URL is outside approved official government/NIER hosts: {url}')


def _session():
    # Network dependencies are intentionally lazy-loaded. Importing package_run
    # must not require requests/bs4 unless BAT collection is actually executed.
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    retry=Retry(total=4,connect=4,read=3,status=3,backoff_factor=1.2,
                status_forcelist=(408,425,429,500,502,503,504),allowed_methods=frozenset({'GET'}),
                raise_on_status=False,respect_retry_after_header=True)
    s=requests.Session()
    s.headers.update({'User-Agent':'Mozilla/5.0 (compatible; EnvironmentalDataCollector/1.0; official-public-reference)'})
    s.mount('https://',HTTPAdapter(max_retries=retry)); s.mount('http://',HTTPAdapter(max_retries=retry)); return s


def _quoted_urls(text):
    out=[]
    for value in re.findall(r"['\"]([^'\"]+)['\"]",str(text or '')):
        low=value.lower()
        if '.pdf' in low or 'download' in low or 'file' in low: out.append(value)
    return out


def attachment_candidates(page_url,html):
    from bs4 import BeautifulSoup
    soup=BeautifulSoup(html,'html.parser'); candidates=[]
    for a in soup.find_all('a'):
        label=' '.join(a.stripped_strings); values=[]
        for attr in ['href','onclick','data-url','data-href','data-file','data-download']:
            raw=a.get(attr)
            if not raw: continue
            if attr=='onclick': values.extend(_quoted_urls(raw))
            else: values.append(raw)
        for raw in values:
            raw=str(raw).strip()
            if not raw or raw.lower().startswith('javascript:'): continue
            url=urljoin(page_url,raw)
            if not _official_host(url): continue
            score=0
            if '.pdf' in url.lower(): score+=4
            if '.pdf' in label.lower(): score+=4
            if 'download' in url.lower() or 'file' in url.lower(): score+=1
            if '최적가용기법' in label or '기준서' in label: score+=2
            if score: candidates.append((score,url,label))
    seen=set(); ranked=[]
    for score,url,label in sorted(candidates,key=lambda x:(-x[0],x[1])):
        if url in seen: continue
        seen.add(url); ranked.append((score,url,label))
    return ranked


def _page_variants(page_url):
    _assert_official_url(page_url)
    values=[page_url]; parsed=urlparse(page_url); query=dict(parse_qsl(parsed.query,keep_blank_values=True))
    if parsed.hostname=='ieps.nier.go.kr' and 'pMENUMST_ID' not in query:
        query['pMENUMST_ID']='95'; values.append(urlunparse(parsed._replace(query=urlencode(query))))
    return list(dict.fromkeys(values))


def _get(session,url,timeout=(15,90)):
    _assert_official_url(url)
    r=session.get(url,timeout=timeout,allow_redirects=True); r.raise_for_status()
    _assert_official_url(r.url)
    return r


def _verified_pdf_response(response,expected_sha=''):
    data=response.content
    if not data.lstrip().startswith(b'%PDF-'): raise RuntimeError(f'Official response is not a PDF: {response.url}')
    digest=sha256_bytes(data); expected=str(expected_sha or '').strip().lower()
    if expected and digest.lower()!=expected:
        raise RuntimeError(f'Official PDF SHA-256 changed: expected={expected} actual={digest} url={response.url}')
    return response.url,data,digest


def fetch_pdf_from_official_page(page_url,expected_sha=''):
    import requests
    session=_session(); errors=[]
    for page in _page_variants(page_url):
        try: r=_get(session,page)
        except requests.RequestException as exc:
            errors.append(f'page:{page}:{type(exc).__name__}:{exc}'); continue
        if r.content.lstrip().startswith(b'%PDF-'):
            final,data,_=_verified_pdf_response(r,expected_sha); return final,data,'DIRECT_PDF_PAGE'
        for _,url,label in attachment_candidates(r.url,r.text):
            try: rr=_get(session,url)
            except requests.RequestException as exc:
                errors.append(f'attachment:{url}:{type(exc).__name__}:{exc}'); continue
            if rr.content.lstrip().startswith(b'%PDF-'):
                final,data,_=_verified_pdf_response(rr,expected_sha); return final,data,f'OFFICIAL_PAGE_ATTACHMENT:{label[:100]}'
            errors.append(f'attachment_not_pdf:{rr.url}')
    detail=' | '.join(errors[-8:]) if errors else 'no attachment candidates'
    raise RuntimeError('No PDF attachment could be resolved and byte-verified from the official document page; '+detail)


def fetch_pdf_from_spec(spec):
    direct=str(spec.get('official_pdf_url') or '').strip(); expected=str(spec.get('official_pdf_sha256') or '').strip().lower(); errors=[]
    if direct:
        try:
            rr=_get(_session(),direct); final,data,digest=_verified_pdf_response(rr,expected)
            return final,data,f'VERIFIED_OFFICIAL_DIRECT_PDF:sha256={digest}'
        except Exception as exc: errors.append(f'direct:{direct}:{type(exc).__name__}:{exc}')
    pages=[]
    for key in ('official_document_page','official_source_locator'):
        value=str(spec.get(key) or '').strip()
        if value and value not in pages: pages.append(value)
    for value in spec.get('official_fallback_pages',[]) or []:
        value=str(value or '').strip()
        if value and value not in pages: pages.append(value)
    for page in pages:
        if not _official_host(page):
            errors.append(f'non_pdf_evidence_locator:{page}'); continue
        try: return fetch_pdf_from_official_page(page,expected)
        except Exception as exc: errors.append(f'page_fallback:{page}:{type(exc).__name__}:{exc}')
    detail=' | '.join(errors[-8:]) if errors else 'no verified official direct PDF or document page'
    raise RuntimeError('Official BAT PDF collection failed; '+detail)


def _document_specs(entry):
    docs=entry.get('official_documents')
    if isinstance(docs,list) and docs:
        out=[]
        for idx,doc in enumerate(docs,1):
            spec=dict(entry); spec.update(doc or {}); spec['document_part']=str((doc or {}).get('document_part') or idx); out.append(spec)
        return out
    spec=dict(entry); spec['document_part']=str(entry.get('document_part') or '1'); return [spec]


def collect(package,catalog_path=CATALOG_PATH):
    package=Path(package); out=package/'output'/'BAT_REFERENCES'; out.mkdir(parents=True,exist_ok=True)
    catalog=read_json(catalog_path,{}) or {}; entries={e.get('catalog_id'):e for e in catalog.get('entries',[]) or []}
    candidates=read_csv(package/'BAT_Applicability_Candidates.csv'); by_catalog={}
    for row in candidates: by_catalog.setdefault(row.get('catalog_id',''),[]).append(row)
    rows=[]; downloaded=failed=pending=locator_pending=0

    for catalog_id,group in sorted(by_catalog.items()):
        entry=entries.get(catalog_id)
        if not entry: continue
        publication=str(entry.get('publication_status') or ''); actions={r.get('collection_action') for r in group}
        roles=sorted({r.get('candidate_role','') for r in group if r.get('candidate_role')}); states=sorted({r.get('candidate_state','') for r in group if r.get('candidate_state')})
        apps=sorted({r.get('applicability_state','') for r in group if r.get('applicability_state')}); site_ids=sorted({r.get('canonical_site_id','') for r in group if r.get('canonical_site_id')})
        site_names=sorted({r.get('site_name','') for r in group if r.get('site_name')}); family=str(entry.get('catalog_family') or catalog_id); revision=str(entry.get('revision_generation') or '')
        specs=_document_specs(entry)
        for spec in specs:
            part=str(spec.get('document_part') or '1'); docid='BAT_'+re.sub(r'[^0-9A-Za-z_]+','_',catalog_id)+(f'_P{part}' if len(specs)>1 else '')
            title=str(spec.get('title') or entry.get('title') or '')
            base={'document_id':docid,'catalog_id':catalog_id,'catalog_family':family,'revision_generation':revision,'document_part':part,
                  'document_type':'BAT_REFERENCE','title':title,'report_year':str(entry.get('publication_year') or entry.get('effective_from') or '')[:4],
                  'source_url':'','source_locator':entry.get('official_source_locator',''),'stored_path':'','verification_status':'SOURCE_VERIFIED','importance':'SUPPORTING',
                  'candidate_roles':'|'.join(roles),'candidate_states':'|'.join(states),'applicability_states':'|'.join(apps),'canonical_site_ids':'|'.join(site_ids),
                  'site_names':'|'.join(site_names),'reference_domains':'|'.join(entry.get('domains',[]) or []),'notes':entry.get('notes','')}
            if publication!='PUBLISHED':
                rows.append({**base,'collection_status':'NOT_YET_PUBLISHED'}); pending+=1; continue
            if 'WAIT_FOR_LATEST_LOCATOR' in actions:
                rows.append({**base,'collection_status':'LATEST_LOCATOR_PENDING'}); locator_pending+=1; continue
            if 'COLLECT' not in actions:
                rows.append({**base,'collection_status':'REVIEW_BEFORE_COLLECTION'}); continue
            try:
                final_url,data,basis=fetch_pdf_from_spec(spec); folder=out/'documents'; folder.mkdir(parents=True,exist_ok=True)
                filename=safe(title)+(f'_part{part}' if len(specs)>1 else '')+'.pdf'; path=folder/filename; path.write_bytes(data); rel=str(path.relative_to(package))
                rows.append({**base,'source_url':final_url,'stored_path':rel,'collection_status':'DOWNLOADED','notes':(base['notes']+f'; {basis}; sha256={sha256_bytes(data)}').strip('; ')})
                downloaded+=1
            except Exception as exc:
                rows.append({**base,'collection_status':'DOWNLOAD_FAILED','notes':(base['notes']+f'; {type(exc).__name__}: {exc}').strip('; ')}); failed+=1

    write_csv(out/'document_index.csv',rows,INDEX_FIELDS)
    if failed: state='PARTIAL'
    elif downloaded: state='DATA_FOUND'
    elif locator_pending: state='LATEST_LOCATOR_PENDING'
    else: state='NO_PUBLISHED_MATCH'
    status={'source_key':'BAT_REFERENCES','status':state,'candidate_documents':len(rows),'downloaded':downloaded,'failed':failed,
            'pending_publication':pending,'latest_locator_pending':locator_pending,
            'policy':'Only approved official Korean government/NIER hosts may supply BAT PDF bytes. Preferred/current revisions only are collected; pending latest locators and unpublished references remain explicit and superseded editions are never silently substituted.'}
    (out/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8'); return status

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--package',default='assembled'); ap.add_argument('--catalog',default=str(CATALOG_PATH)); a=ap.parse_args()
    print(json.dumps(collect(a.package,a.catalog),ensure_ascii=False,indent=2))
