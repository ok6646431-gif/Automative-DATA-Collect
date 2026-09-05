import json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

try:
    from .bat_resolver import CATALOG_PATH, read_json
except ImportError:
    from bat_resolver import CATALOG_PATH, read_json

IEPS_LIST_URL='https://ieps.nier.go.kr/web/board/5/'
IEPS_PARAMS={'CERT_TYP':'6','pMENUMST_ID':'95','tab':'seven'}


def _session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    retry=Retry(total=3,connect=3,read=2,status=2,backoff_factor=1.0,status_forcelist=(408,425,429,500,502,503,504),allowed_methods=frozenset({'GET'}),raise_on_status=False)
    s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0 (BATCatalogDiscovery/1.0; official-public-reference)'})
    s.mount('https://',HTTPAdapter(max_retries=retry)); return s


def _ieps_board_id(value):
    text=str(value or '')
    m=re.search(r'/web/board/5/(\d+)/?',text)
    return m.group(1) if m else ''


def discover_ieps(max_pages=20,timeout=(15,60)):
    from bs4 import BeautifulSoup
    s=_session(); items={}; attempts=[]
    for page in range(1,max_pages+1):
        params={**IEPS_PARAMS,'page':page}
        try:
            r=s.get(IEPS_LIST_URL,params=params,timeout=timeout); r.raise_for_status()
        except Exception as exc:
            attempts.append({'page':page,'state':'SOURCE_UNREACHABLE','error':f'{type(exc).__name__}: {exc}'})
            if page==1: break
            continue
        soup=BeautifulSoup(r.text,'html.parser'); found=0
        for a in soup.find_all('a'):
            href=str(a.get('href') or ''); bid=_ieps_board_id(href)
            if not bid: continue
            label=' '.join(a.stripped_strings).strip()
            if not label: continue
            found+=1
            items[bid]={'board_id':bid,'title':label,'official_document_page':urljoin(r.url,href),'discovery_page':page}
        attempts.append({'page':page,'state':'OK','result_links':found,'url':r.url})
        if page>1 and found==0: break
    return list(sorted(items.values(),key=lambda x:int(x['board_id']),reverse=True)),attempts


def validate_against_master(catalog_path=CATALOG_PATH):
    catalog=read_json(catalog_path,{}) or {}; entries=catalog.get('entries',[]) or []
    items,attempts=discover_ieps(); by_id={str(x['board_id']):x for x in items}
    rows=[]
    known_ids=set()
    for e in entries:
        page=str(e.get('official_document_page') or '').strip()
        source=str(e.get('official_source_locator') or '').strip()
        bid=_ieps_board_id(page) or _ieps_board_id(source)
        if bid:
            known_ids.add(bid)
        hit=by_id.get(bid) if bid else None
        if not bid:
            if page or source:
                state='NON_IEPS_OFFICIAL_LOCATOR'
            else:
                state='NO_IEPS_LOCATOR_EXPECTED' if e.get('publication_status')!='PUBLISHED' else 'LATEST_LOCATOR_PENDING'
        elif hit:
            state='IEPS_LIST_CONFIRMED'
        else:
            state='IEPS_LIST_NOT_FOUND'
        rows.append({'catalog_id':e.get('catalog_id',''),'catalog_family':e.get('catalog_family',e.get('catalog_id','')),'title':e.get('title',''),'publication_status':e.get('publication_status',''),'locator_state':state,'ieps_board_id':bid,'official_document_page':page,'official_source_locator':source,'listed_title':hit.get('title','') if hit else ''})
    unmatched=[x for x in items if str(x.get('board_id') or '') not in known_ids]
    first_unreachable=bool(attempts and attempts[0].get('state')=='SOURCE_UNREACHABLE')
    status='SOURCE_UNREACHABLE' if first_unreachable else ('CATALOG_DRIFT' if unmatched else 'PASS')
    return {'schema_version':'1.1','checked_at':datetime.now(timezone.utc).isoformat(),'status':status,'official_ieps_count':len(items),'catalog_entry_count':len(entries),'attempts':attempts,'catalog_validation':rows,'unmatched_official_items':unmatched,'principle':'IEPS BAT board_id is the stable discovery key. Query strings and navigation parameters are ignored. IEPS BAT listing is authoritative for document discovery but not assumed to expose every newly published bibliographic revision. Existing verified locators are never erased on transient source failure.'}


def main(out='BAT_Catalog_Refresh.json',catalog=str(CATALOG_PATH)):
    payload=validate_against_master(catalog); Path(out).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({'status':payload['status'],'official_ieps_count':payload['official_ieps_count'],'catalog_entry_count':payload['catalog_entry_count'],'unmatched':len(payload['unmatched_official_items'])},ensure_ascii=False)); return payload

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--out',default='BAT_Catalog_Refresh.json'); ap.add_argument('--catalog',default=str(CATALOG_PATH)); a=ap.parse_args(); main(a.out,a.catalog)
