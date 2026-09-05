"""Byte-verify every document exposed by the current BREFOS standard-document feed.

The registry is deliberately metadata-only: PDFs are streamed, hashed, and discarded.
It separates source reachability from integrity failures and never mutates the BAT master
catalog. A later promotion step may use only VERIFIED_PDF rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

try:
    from .brefos_catalog_discovery import discover
except ImportError:
    from brefos_catalog_discovery import discover


def _session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    retry=Retry(total=2,connect=2,read=1,status=1,backoff_factor=0.8,
                status_forcelist=(408,425,429,500,502,503,504),
                allowed_methods=frozenset({'GET'}),raise_on_status=False,
                respect_retry_after_header=True)
    s=requests.Session()
    s.headers.update({'User-Agent':'Mozilla/5.0 (BREFOSByteRegistry/1.0; official-public-reference)'})
    s.mount('https://',HTTPAdapter(max_retries=retry))
    return s


def verify_url(session, url: str, timeout=(10, 75)) -> Dict[str, Any]:
    import requests
    result={'url':url,'status':'SOURCE_UNREACHABLE','bytes':0,'sha256':'','content_type':'','http_status':None}
    try:
        with session.get(url,timeout=timeout,allow_redirects=True,stream=True) as r:
            result['http_status']=r.status_code
            result['final_url']=r.url
            result['content_type']=r.headers.get('content-type','')
            r.raise_for_status()
            h=hashlib.sha256(); total=0; head=b''
            for chunk in r.iter_content(chunk_size=1024*1024):
                if not chunk: continue
                if len(head)<8: head=(head+chunk)[:8]
                total+=len(chunk); h.update(chunk)
            result['bytes']=total
            result['sha256']=h.hexdigest()
            if not head.lstrip().startswith(b'%PDF-'):
                result['status']='RESPONDED_NOT_PDF'
                result['header_hex']=head.hex()
            elif total<=0:
                result['status']='EMPTY_PDF_RESPONSE'
            else:
                result['status']='VERIFIED_PDF'
    except requests.RequestException as exc:
        result['error']=f'{type(exc).__name__}: {exc}'
    except Exception as exc:
        result['status']='VERIFY_ERROR'
        result['error']=f'{type(exc).__name__}: {exc}'
    return result


def build_registry(max_pages: int=20, timeout=(10,75)) -> Dict[str, Any]:
    snapshot=discover(max_pages=max_pages)
    payload={
        'schema_version':'1.0',
        'checked_at':datetime.now(timezone.utc).isoformat(),
        'source_url':snapshot.get('source_url'),
        'discovery_status':snapshot.get('status'),
        'advertised_total_records':snapshot.get('advertised_total_records'),
        'discovered_document_count':snapshot.get('discovered_document_count',0),
        'documents':[],
    }
    if snapshot.get('status')!='PASS':
        payload['status']='DISCOVERY_NOT_COMPLETE'
        payload['discovery_attempts']=snapshot.get('attempts',[])
        return payload

    s=_session()
    counts={}
    for doc in snapshot.get('documents',[]):
        row={k:doc.get(k) for k in ('atch_file_id','stdrdoc_origin_id','ntt_id','title','row_text','viewer_pdf_url')}
        row.update(verify_url(s,str(doc.get('viewer_pdf_url') or ''),timeout=timeout))
        payload['documents'].append(row)
        counts[row['status']]=counts.get(row['status'],0)+1
    payload['status_counts']=counts
    payload['verified_pdf_count']=counts.get('VERIFIED_PDF',0)
    payload['status']='PASS' if payload['verified_pdf_count']==payload['discovered_document_count'] else 'PARTIAL'
    payload['principle']='Only VERIFIED_PDF rows are eligible for BAT catalog URL/SHA promotion. SOURCE_UNREACHABLE is not treated as a content failure.'
    return payload


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',default='BREFOS_Byte_Registry.json')
    ap.add_argument('--max-pages',type=int,default=20)
    ap.add_argument('--connect-timeout',type=int,default=10)
    ap.add_argument('--read-timeout',type=int,default=75)
    args=ap.parse_args()
    payload=build_registry(args.max_pages,(args.connect_timeout,args.read_timeout))
    Path(args.out).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':payload.get('status'),'discovery_status':payload.get('discovery_status'),'discovered':payload.get('discovered_document_count'),'verified':payload.get('verified_pdf_count',0),'status_counts':payload.get('status_counts',{})},ensure_ascii=False,indent=2))
    if payload.get('status')=='DISCOVERY_NOT_COMPLETE': raise SystemExit(1)
    if any(k in (payload.get('status_counts') or {}) for k in ('RESPONDED_NOT_PDF','EMPTY_PDF_RESPONSE')): raise SystemExit(2)


if __name__=='__main__': main()
