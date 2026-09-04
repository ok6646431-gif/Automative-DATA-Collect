import csv, hashlib, json, re
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

try:
    from .bat_resolver import CATALOG_PATH, read_json, read_csv
except ImportError:
    from bat_resolver import CATALOG_PATH, read_json, read_csv

INDEX_FIELDS=[
    'document_id','catalog_id','document_type','title','report_year','source_url','source_locator','stored_path',
    'collection_status','verification_status','importance','candidate_roles','candidate_states','applicability_states',
    'canonical_site_ids','site_names','reference_domains','notes'
]


def safe(value):
    text=re.sub(r'[\\/:*?"<>|\x00-\x1f]+','_',str(value or '')).strip(' ._')
    return text[:180] or 'BAT_reference'


def write_csv(path,rows,fields):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)


def sha256_bytes(data): return hashlib.sha256(data).hexdigest()


def _session():
    # BAT network dependencies are intentionally lazy-loaded. Importing package_run
    # must not require requests/bs4 unless the BAT collector is actually executed.
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    retry=Retry(
        total=4, connect=4, read=3, status=3,
        backoff_factor=1.2,
        status_forcelist=(408,425,429,500,502,503,504),
        allowed_methods=frozenset({'GET'}),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    s=requests.Session()
    s.headers.update({'User-Agent':'Mozilla/5.0 (compatible; EnvironmentalDataCollector/1.0; official-public-reference)'})
    s.mount('https://',HTTPAdapter(max_retries=retry))
    s.mount('http://',HTTPAdapter(max_retries=retry))
    return s


def _quoted_urls(text):
    out=[]
    for value in re.findall(r"['\"]([^'\"]+)['\"]",str(text or '')):
        low=value.lower()
        if '.pdf' in low or 'download' in low or 'file' in low:
            out.append(value)
    return out


def attachment_candidates(page_url,html):
    from bs4 import BeautifulSoup

    soup=BeautifulSoup(html,'html.parser'); candidates=[]
    for a in soup.find_all('a'):
        label=' '.join(a.stripped_strings)
        values=[]
        for attr in ['href','onclick','data-url','data-href','data-file','data-download']:
            raw=a.get(attr)
            if not raw: continue
            if attr=='onclick': values.extend(_quoted_urls(raw))
            else: values.append(raw)
        for raw in values:
            raw=str(raw).strip()
            if not raw or raw.lower().startswith('javascript:'): continue
            url=urljoin(page_url,raw)
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
    """Return official URL variants only; never leave the verified authority host."""
    values=[page_url]
    parsed=urlparse(page_url)
    query=dict(parse_qsl(parsed.query,keep_blank_values=True))
    if parsed.hostname=='ieps.nier.go.kr' and 'pMENUMST_ID' not in query:
        query['pMENUMST_ID']='95'
        values.append(urlunparse(parsed._replace(query=urlencode(query))))
    return list(dict.fromkeys(values))


def _get(session,url,timeout=(15,90)):
    r=session.get(url,timeout=timeout,allow_redirects=True)
    r.raise_for_status()
    return r


def _verified_pdf_response(response,expected_sha=''):
    data=response.content
    if not data.lstrip().startswith(b'%PDF-'):
        raise RuntimeError(f'Official response is not a PDF: {response.url}')
    digest=sha256_bytes(data)
    expected=str(expected_sha or '').strip().lower()
    if expected and digest.lower()!=expected:
        raise RuntimeError(f'Official PDF SHA-256 changed: expected={expected} actual={digest} url={response.url}')
    return response.url,data,digest


def fetch_pdf_from_official_page(page_url,expected_sha=''):
    import requests

    session=_session(); errors=[]
    for page in _page_variants(page_url):
        try:
            r=_get(session,page)
        except requests.RequestException as exc:
            errors.append(f'page:{page}:{type(exc).__name__}:{exc}')
            continue
        if r.content.lstrip().startswith(b'%PDF-'):
            final,data,_=_verified_pdf_response(r,expected_sha)
            return final,data,'DIRECT_PDF_PAGE'
        candidates=attachment_candidates(r.url,r.text)
        for _,url,label in candidates:
            try:
                rr=_get(session,url)
            except requests.RequestException as exc:
                errors.append(f'attachment:{url}:{type(exc).__name__}:{exc}')
                continue
            if rr.content.lstrip().startswith(b'%PDF-'):
                final,data,_=_verified_pdf_response(rr,expected_sha)
                return final,data,f'OFFICIAL_PAGE_ATTACHMENT:{label[:100]}'
            errors.append(f'attachment_not_pdf:{rr.url}')
    detail=' | '.join(errors[-8:]) if errors else 'no attachment candidates'
    raise RuntimeError('No PDF attachment could be resolved and byte-verified from the official document page; '+detail)


def fetch_pdf_from_entry(entry):
    """Prefer a previously byte-verified official direct PDF endpoint.

    The board/catalog page remains the discovery fallback. This avoids making every
    company run depend on a slow IEPS HTML page while still failing closed if the
    direct official bytes change unexpectedly.
    """
    import requests

    direct=str(entry.get('official_pdf_url') or '').strip()
    expected=str(entry.get('official_pdf_sha256') or '').strip().lower()
    errors=[]
    if direct.startswith(('https://','http://')):
        try:
            rr=_get(_session(),direct)
            final,data,digest=_verified_pdf_response(rr,expected)
            return final,data,f'VERIFIED_OFFICIAL_DIRECT_PDF:sha256={digest}'
        except Exception as exc:
            errors.append(f'direct:{direct}:{type(exc).__name__}:{exc}')

    page=str(entry.get('official_document_page') or entry.get('official_source_locator') or '').strip()
    if page.startswith(('https://','http://')):
        try:
            return fetch_pdf_from_official_page(page,expected)
        except Exception as exc:
            errors.append(f'page_fallback:{type(exc).__name__}:{exc}')

    detail=' | '.join(errors[-6:]) if errors else 'no official direct PDF or document page'
    raise RuntimeError('Official BAT PDF collection failed; '+detail)


def collect(package,catalog_path=CATALOG_PATH):
    package=Path(package); out=package/'output'/'BAT_REFERENCES'
    out.mkdir(parents=True,exist_ok=True)
    catalog=read_json(catalog_path,{}) or {}; entries={e.get('catalog_id'):e for e in catalog.get('entries',[]) or []}
    candidates=read_csv(package/'BAT_Applicability_Candidates.csv')
    by_catalog={}
    for row in candidates: by_catalog.setdefault(row.get('catalog_id',''),[]).append(row)
    rows=[]; downloaded=failed=pending=0

    for catalog_id,group in sorted(by_catalog.items()):
        entry=entries.get(catalog_id)
        if not entry: continue
        publication=str(entry.get('publication_status') or '')
        actions={r.get('collection_action') for r in group}
        roles=sorted({r.get('candidate_role','') for r in group if r.get('candidate_role')})
        states=sorted({r.get('candidate_state','') for r in group if r.get('candidate_state')})
        apps=sorted({r.get('applicability_state','') for r in group if r.get('applicability_state')})
        site_ids=sorted({r.get('canonical_site_id','') for r in group if r.get('canonical_site_id')})
        site_names=sorted({r.get('site_name','') for r in group if r.get('site_name')})
        docid='BAT_'+re.sub(r'[^0-9A-Za-z_]+','_',catalog_id)
        base={
            'document_id':docid,'catalog_id':catalog_id,'document_type':'BAT_REFERENCE','title':entry.get('title',''),
            'report_year':str(entry.get('effective_from') or '')[:4] if entry.get('effective_from') else '',
            'source_url':'','source_locator':entry.get('official_source_locator',''),'stored_path':'',
            'verification_status':'SOURCE_VERIFIED','importance':'SUPPORTING','candidate_roles':'|'.join(roles),
            'candidate_states':'|'.join(states),'applicability_states':'|'.join(apps),'canonical_site_ids':'|'.join(site_ids),
            'site_names':'|'.join(site_names),'reference_domains':'|'.join(entry.get('domains',[]) or []),'notes':entry.get('notes','')
        }
        if publication!='PUBLISHED':
            rows.append({**base,'collection_status':'NOT_YET_PUBLISHED'}); pending+=1; continue
        if 'COLLECT' not in actions:
            rows.append({**base,'collection_status':'REVIEW_BEFORE_COLLECTION'}); continue
        if not any(str(entry.get(k) or '').startswith(('https://','http://')) for k in ('official_pdf_url','official_document_page','official_source_locator')):
            rows.append({**base,'collection_status':'DOWNLOAD_FAILED','notes':(base['notes']+'; missing official document locator').strip('; ')}); failed+=1; continue
        try:
            final_url,data,basis=fetch_pdf_from_entry(entry)
            folder=out/'documents'; folder.mkdir(parents=True,exist_ok=True)
            filename=safe(entry.get('title'))+'.pdf'; path=folder/filename
            path.write_bytes(data)
            rel=str(path.relative_to(package))
            rows.append({**base,'source_url':final_url,'stored_path':rel,'collection_status':'DOWNLOADED',
                         'notes':(base['notes']+f'; {basis}; sha256={sha256_bytes(data)}').strip('; ')})
            downloaded+=1
        except Exception as exc:
            rows.append({**base,'collection_status':'DOWNLOAD_FAILED','notes':(base['notes']+f'; {type(exc).__name__}: {exc}').strip('; ')})
            failed+=1

    write_csv(out/'document_index.csv',rows,INDEX_FIELDS)
    if downloaded and failed: state='PARTIAL'
    elif downloaded: state='DATA_FOUND'
    elif failed: state='PARTIAL'
    else: state='NO_PUBLISHED_MATCH'
    status={
        'source_key':'BAT_REFERENCES','status':state,
        'candidate_documents':len(rows),'downloaded':downloaded,'failed':failed,'pending_publication':pending,
        'policy':'Only official government/NIER sources are accepted. Verified direct official PDFs are preferred; catalog-page discovery is fallback; byte/SHA mismatch and transient failure remain explicit.'
    }
    (out/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    return status


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--package',default='assembled'); ap.add_argument('--catalog',default=str(CATALOG_PATH)); a=ap.parse_args()
    print(json.dumps(collect(a.package,a.catalog),ensure_ascii=False,indent=2))
