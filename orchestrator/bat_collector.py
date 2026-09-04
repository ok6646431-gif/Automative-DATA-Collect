import csv, hashlib, json, re
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

try:
    from .bat_resolver import CATALOG_PATH, read_json, read_csv
except ImportError:
    from bat_resolver import CATALOG_PATH, read_json, read_csv

INDEX_FIELDS=[
    'document_id','catalog_id','catalog_family','revision_id','revision_generation','publication_year',
    'revision_status','preferred_for_matching','document_part','volume_no','document_type','title','report_year',
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
            spec=dict(entry); spec.update(doc or {})
            spec['document_part']=str((doc or {}).get('document_part') or idx)
            spec['volume_no']=str((doc or {}).get('volume_no') or (doc or {}).get('volume') or spec['document_part'])
            out.append(spec)
        return out
    spec=dict(entry)
    spec['document_part']=str(entry.get('document_part') or '1')
    spec['volume_no']=str(entry.get('volume_no') or entry.get('volume') or spec['document_part'])
    return [spec]


def _revision_id(entry):
    explicit=str(entry.get('revision_id') or '').strip()
    if explicit: return explicit
    family=str(entry.get('catalog_family') or entry.get('catalog_id') or 'BAT')
    year=str(entry.get('publication_year') or 'UNKNOWN')
    generation=str(entry.get('revision_generation') or entry.get('catalog_id') or 'REV')
    return f'{family}:{year}:{generation}'


def _revision_status(entry):
    explicit=str(entry.get('supersession_status') or '').strip().upper()
    if explicit: return explicit
    if entry.get('preferred',True) is False: return 'SUPERSEDED'
    if str(entry.get('publication_status') or '').upper()!='PUBLISHED': return 'FUTURE_OR_UNPUBLISHED'
    return 'CURRENT'


def _family_entries(catalog,family):
    entries=[e for e in (catalog.get('entries',[]) or []) if str(e.get('catalog_family') or e.get('catalog_id') or '')==family]
    return sorted(entries,key=lambda e:(int(e.get('publication_year') or 0),str(e.get('revision_generation') or ''),str(e.get('catalog_id') or '')))


def _candidate_context(group):
    return {
        'roles':sorted({r.get('candidate_role','') for r in group if r.get('candidate_role')}),
        'states':sorted({r.get('candidate_state','') for r in group if r.get('candidate_state')}),
        'apps':sorted({r.get('applicability_state','') for r in group if r.get('applicability_state')}),
        'site_ids':sorted({r.get('canonical_site_id','') for r in group if r.get('canonical_site_id')}),
        'site_names':sorted({r.get('site_name','') for r in group if r.get('site_name')}),
    }


def _has_official_locator(entry):
    if any(str(entry.get(k) or '').startswith(('https://','http://')) for k in ('official_pdf_url','official_document_page','official_source_locator')):
        return True
    return any(str(x or '').startswith(('https://','http://')) for x in (entry.get('official_fallback_pages',[]) or []))


def collect(package,catalog_path=CATALOG_PATH):
    package=Path(package); out=package/'output'/'BAT_REFERENCES'; out.mkdir(parents=True,exist_ok=True)
    catalog=read_json(catalog_path,{}) or {}
    candidates=read_csv(package/'BAT_Applicability_Candidates.csv')

    by_family={}
    for row in candidates:
        family=str(row.get('catalog_family') or row.get('catalog_id') or '')
        if family: by_family.setdefault(family,[]).append(row)

    rows=[]
    current_downloaded=current_failed=current_pending=current_locator_pending=0
    archive_downloaded=archive_failed=archive_locator_pending=0

    for family,group in sorted(by_family.items()):
        context=_candidate_context(group)
        preferred_candidate_ids={str(r.get('catalog_id') or '') for r in group}
        for entry in _family_entries(catalog,family):
            catalog_id=str(entry.get('catalog_id') or '')
            preferred=entry.get('preferred',True) is not False
            revision_status=_revision_status(entry)
            publication=str(entry.get('publication_status') or '')
            revision_id=_revision_id(entry)
            revision=str(entry.get('revision_generation') or '')
            publication_year=str(entry.get('publication_year') or entry.get('effective_from') or '')[:4]
            matching_group=[r for r in group if str(r.get('catalog_id') or '')==catalog_id]
            actions={r.get('collection_action') for r in matching_group}
            is_current_match=preferred and catalog_id in preferred_candidate_ids
            archive_only=not preferred

            # A family is selected by the preferred match. Older revisions are collected
            # for historical/archive comparison only and never become applicability candidates.
            if preferred and not is_current_match:
                continue

            specs=_document_specs(entry)
            for spec in specs:
                part=str(spec.get('document_part') or '1'); volume_no=str(spec.get('volume_no') or part)
                docid='BAT_'+re.sub(r'[^0-9A-Za-z_]+','_',catalog_id)+(f'_P{part}' if len(specs)>1 else '')
                title=str(spec.get('title') or entry.get('title') or '')
                base={
                    'document_id':docid,'catalog_id':catalog_id,'catalog_family':family,'revision_id':revision_id,
                    'revision_generation':revision,'publication_year':publication_year,
                    'revision_status':'SUPERSEDED_ARCHIVE_ONLY' if archive_only else revision_status,
                    'preferred_for_matching':'false' if archive_only else 'true',
                    'document_part':part,'volume_no':volume_no,'document_type':'BAT_REFERENCE','title':title,
                    'report_year':publication_year,'source_url':'','source_locator':entry.get('official_source_locator',''),
                    'stored_path':'','verification_status':'SOURCE_VERIFIED','importance':'SUPPORTING',
                    'candidate_roles':'|'.join(context['roles']),'candidate_states':'|'.join(context['states']),
                    'applicability_states':'|'.join(context['apps']),'canonical_site_ids':'|'.join(context['site_ids']),
                    'site_names':'|'.join(context['site_names']),'reference_domains':'|'.join(entry.get('domains',[]) or []),
                    'notes':entry.get('notes','')
                }

                if archive_only:
                    if publication!='PUBLISHED':
                        rows.append({**base,'collection_status':'SUPERSEDED_NOT_PUBLISHED'}); continue
                    if not _has_official_locator(spec):
                        rows.append({**base,'collection_status':'SUPERSEDED_LOCATOR_PENDING'})
                        archive_locator_pending+=1; continue
                    try:
                        final_url,data,basis=fetch_pdf_from_spec(spec)
                        folder=out/'documents'/safe(family)/safe(f'{publication_year}_{revision or catalog_id}')
                        folder.mkdir(parents=True,exist_ok=True)
                        filename=safe(title)+(f'_part{part}' if len(specs)>1 else '')+'.pdf'
                        path=folder/filename; path.write_bytes(data); rel=str(path.relative_to(package))
                        rows.append({**base,'source_url':final_url,'stored_path':rel,'collection_status':'DOWNLOADED',
                                     'notes':(base['notes']+f'; SUPERSEDED_ARCHIVE_ONLY; {basis}; sha256={sha256_bytes(data)}').strip('; ')})
                        archive_downloaded+=1
                    except Exception as exc:
                        rows.append({**base,'collection_status':'SUPERSEDED_DOWNLOAD_FAILED',
                                     'notes':(base['notes']+f'; SUPERSEDED_ARCHIVE_ONLY; {type(exc).__name__}: {exc}').strip('; ')})
                        archive_failed+=1
                    continue

                if publication!='PUBLISHED':
                    rows.append({**base,'collection_status':'NOT_YET_PUBLISHED'}); current_pending+=1; continue
                if 'WAIT_FOR_LATEST_LOCATOR' in actions:
                    rows.append({**base,'collection_status':'LATEST_LOCATOR_PENDING'}); current_locator_pending+=1; continue
                if 'COLLECT' not in actions:
                    rows.append({**base,'collection_status':'REVIEW_BEFORE_COLLECTION'}); continue
                try:
                    final_url,data,basis=fetch_pdf_from_spec(spec)
                    folder=out/'documents'/safe(family)/safe(f'{publication_year}_{revision or catalog_id}')
                    folder.mkdir(parents=True,exist_ok=True)
                    filename=safe(title)+(f'_part{part}' if len(specs)>1 else '')+'.pdf'
                    path=folder/filename; path.write_bytes(data); rel=str(path.relative_to(package))
                    rows.append({**base,'source_url':final_url,'stored_path':rel,'collection_status':'DOWNLOADED',
                                 'notes':(base['notes']+f'; CURRENT_MATCHED; {basis}; sha256={sha256_bytes(data)}').strip('; ')})
                    current_downloaded+=1
                except Exception as exc:
                    rows.append({**base,'collection_status':'DOWNLOAD_FAILED',
                                 'notes':(base['notes']+f'; CURRENT_MATCHED; {type(exc).__name__}: {exc}').strip('; ')})
                    current_failed+=1

    write_csv(out/'document_index.csv',rows,INDEX_FIELDS)

    if current_failed:
        state='PARTIAL'
    elif current_locator_pending:
        state='LATEST_LOCATOR_PENDING_WITH_ARCHIVE' if archive_downloaded else 'LATEST_LOCATOR_PENDING'
    elif current_downloaded and (archive_failed or archive_locator_pending):
        state='DATA_FOUND_WITH_ARCHIVE_GAPS'
    elif current_downloaded:
        state='DATA_FOUND'
    elif current_pending and archive_downloaded:
        state='CURRENT_UNPUBLISHED_ARCHIVE_FOUND'
    elif current_pending:
        state='NO_PUBLISHED_MATCH'
    elif archive_downloaded:
        state='ARCHIVE_ONLY_FOUND'
    else:
        state='NO_PUBLISHED_MATCH'

    status={
        'source_key':'BAT_REFERENCES','status':state,'candidate_documents':len(rows),
        'downloaded':current_downloaded+archive_downloaded,
        'current_downloaded':current_downloaded,'current_failed':current_failed,
        'pending_publication':current_pending,'latest_locator_pending':current_locator_pending,
        'superseded_downloaded':archive_downloaded,'superseded_failed':archive_failed,
        'superseded_locator_pending':archive_locator_pending,
        'policy':'Applicability matching uses only preferred/current revisions. Once a BAT family is matched, all published official superseded revisions with resolvable official locators are also collected for historical comparison. Superseded files are archive-only and never substitute for a missing or unpublished current revision.'
    }
    (out/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8'); return status


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--package',default='assembled'); ap.add_argument('--catalog',default=str(CATALOG_PATH)); a=ap.parse_args()
    print(json.dumps(collect(a.package,a.catalog),ensure_ascii=False,indent=2))
