"""Byte-verify every document exposed by the current BREFOS standard-document feed.

The registry is deliberately metadata-only: PDFs are streamed, hashed, and discarded.
It separates source reachability from integrity failures and never mutates the BAT master
catalog. A later promotion step may use only VERIFIED_PDF rows.

Verification uses a small bounded worker pool. If live BREFOS *discovery* is temporarily
SOURCE_UNREACHABLE, a recent repository-persisted last-known-good discovery snapshot may
supply document identities/URLs. A contradictory live response is never overridden by the
snapshot, and stale snapshots fail closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

try:
    from .brefos_catalog_discovery import discover
except ImportError:
    from brefos_catalog_discovery import discover

_THREAD_LOCAL=threading.local()
DEFAULT_SNAPSHOT=Path(__file__).with_name('brefos_catalog_last_verified.json')


def _session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    retry=Retry(total=1,connect=1,read=1,status=1,backoff_factor=0.8,
                status_forcelist=(408,425,429,500,502,503,504),
                allowed_methods=frozenset({'GET'}),raise_on_status=False,
                respect_retry_after_header=True)
    s=requests.Session()
    s.headers.update({'User-Agent':'Mozilla/5.0 (BREFOSByteRegistry/1.2; official-public-reference)'})
    s.mount('https://',HTTPAdapter(max_retries=retry,pool_connections=2,pool_maxsize=2))
    return s


def _thread_session():
    s=getattr(_THREAD_LOCAL,'session',None)
    if s is None:
        s=_session(); _THREAD_LOCAL.session=s
    return s


def verify_url(session, url: str, timeout=(8, 45)) -> Dict[str, Any]:
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


def _verify_document(index: int, doc: Dict[str,Any], timeout) -> tuple[int,Dict[str,Any]]:
    row={k:doc.get(k) for k in ('atch_file_id','stdrdoc_origin_id','ntt_id','title','row_text','viewer_pdf_url')}
    row.update(verify_url(_thread_session(),str(doc.get('viewer_pdf_url') or ''),timeout=timeout))
    return index,row


def _snapshot_age_days(snapshot: Dict[str,Any]) -> float | None:
    raw=str(snapshot.get('checked_at') or '').strip()
    if not raw: return None
    try:
        dt=datetime.fromisoformat(raw.replace('Z','+00:00'))
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return max(0.0,(datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()/86400.0)
    except Exception:
        return None


def _choose_discovery(live: Dict[str,Any], snapshot_path: Path, max_snapshot_age_days: int) -> tuple[Dict[str,Any],Dict[str,Any]]:
    if live.get('status')=='PASS':
        return live,{
            'basis':'LIVE_BREFOS_DISCOVERY',
            'live_status':'PASS',
            'snapshot_used':False,
        }
    # Fail closed for parse/content contradictions. Snapshot fallback is allowed only for
    # transport-level unreachability, never because live content disagrees with expectations.
    if live.get('status')!='SOURCE_UNREACHABLE':
        return live,{
            'basis':'LIVE_BREFOS_DISCOVERY_FAILED_CLOSED',
            'live_status':live.get('status'),
            'snapshot_used':False,
        }
    try:
        snapshot=json.loads(Path(snapshot_path).read_text(encoding='utf-8'))
    except Exception as exc:
        return live,{
            'basis':'SNAPSHOT_UNAVAILABLE',
            'live_status':live.get('status'),
            'snapshot_used':False,
            'snapshot_error':f'{type(exc).__name__}: {exc}',
        }
    age=_snapshot_age_days(snapshot)
    if snapshot.get('status')!='PASS' or not snapshot.get('documents') or age is None or age>max_snapshot_age_days:
        return live,{
            'basis':'SNAPSHOT_REJECTED',
            'live_status':live.get('status'),
            'snapshot_used':False,
            'snapshot_status':snapshot.get('status'),
            'snapshot_checked_at':snapshot.get('checked_at'),
            'snapshot_age_days':age,
            'max_snapshot_age_days':max_snapshot_age_days,
        }
    return snapshot,{
        'basis':'LAST_VERIFIED_SNAPSHOT_FALLBACK',
        'live_status':live.get('status'),
        'snapshot_used':True,
        'snapshot_checked_at':snapshot.get('checked_at'),
        'snapshot_age_days':age,
        'max_snapshot_age_days':max_snapshot_age_days,
    }


def build_registry(max_pages: int=20, timeout=(8,45), max_workers: int=4,
                   snapshot_path: Path=DEFAULT_SNAPSHOT, max_snapshot_age_days: int=14) -> Dict[str, Any]:
    live=discover(max_pages=max_pages)
    snapshot,basis=_choose_discovery(live,Path(snapshot_path),max_snapshot_age_days)
    payload={
        'schema_version':'1.2',
        'checked_at':datetime.now(timezone.utc).isoformat(),
        'source_url':snapshot.get('source_url') or live.get('source_url'),
        'discovery_status':snapshot.get('status'),
        'discovery_basis':basis,
        'advertised_total_records':snapshot.get('advertised_total_records'),
        'discovered_document_count':snapshot.get('discovered_document_count',0),
        'max_workers':max(1,min(int(max_workers),6)),
        'documents':[],
    }
    if snapshot.get('status')!='PASS':
        payload['status']='DISCOVERY_NOT_COMPLETE'
        payload['live_discovery_attempts']=live.get('attempts',[])
        return payload

    docs=list(snapshot.get('documents',[]) or [])
    ordered=[None]*len(docs)
    counts={}
    workers=max(1,min(int(max_workers),6))
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='brefos-byte') as executor:
        futures={executor.submit(_verify_document,i,doc,timeout):i for i,doc in enumerate(docs)}
        completed=0
        for future in as_completed(futures):
            i=futures[future]
            try:
                _,row=future.result()
            except Exception as exc:
                doc=docs[i]
                row={k:doc.get(k) for k in ('atch_file_id','stdrdoc_origin_id','ntt_id','title','row_text','viewer_pdf_url')}
                row.update({'url':str(doc.get('viewer_pdf_url') or ''),'status':'VERIFY_ERROR','bytes':0,'sha256':'','content_type':'','http_status':None,'error':f'{type(exc).__name__}: {exc}'})
            ordered[i]=row
            counts[row['status']]=counts.get(row['status'],0)+1
            completed+=1
            print(json.dumps({'completed':completed,'total':len(docs),'atch_file_id':row.get('atch_file_id'),'status':row.get('status'),'bytes':row.get('bytes',0)},ensure_ascii=False),flush=True)

    payload['documents']=[r for r in ordered if r is not None]
    payload['status_counts']=counts
    payload['verified_pdf_count']=counts.get('VERIFIED_PDF',0)
    payload['status']='PASS' if payload['verified_pdf_count']==payload['discovered_document_count'] else 'PARTIAL'
    payload['principle']='Only VERIFIED_PDF rows are eligible for BAT catalog URL/SHA promotion. SOURCE_UNREACHABLE is not treated as a content failure. Snapshot fallback can supply identities only when live discovery is unreachable.'
    return payload


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',default='BREFOS_Byte_Registry.json')
    ap.add_argument('--max-pages',type=int,default=20)
    ap.add_argument('--connect-timeout',type=int,default=8)
    ap.add_argument('--read-timeout',type=int,default=45)
    ap.add_argument('--workers',type=int,default=4)
    ap.add_argument('--snapshot',default=str(DEFAULT_SNAPSHOT))
    ap.add_argument('--max-snapshot-age-days',type=int,default=14)
    args=ap.parse_args()
    payload=build_registry(args.max_pages,(args.connect_timeout,args.read_timeout),args.workers,Path(args.snapshot),args.max_snapshot_age_days)
    Path(args.out).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':payload.get('status'),'discovery_status':payload.get('discovery_status'),'discovery_basis':payload.get('discovery_basis'),'discovered':payload.get('discovered_document_count'),'verified':payload.get('verified_pdf_count',0),'status_counts':payload.get('status_counts',{})},ensure_ascii=False,indent=2))
    if payload.get('status')=='DISCOVERY_NOT_COMPLETE': raise SystemExit(1)
    if any(k in (payload.get('status_counts') or {}) for k in ('RESPONDED_NOT_PDF','EMPTY_PDF_RESPONSE')): raise SystemExit(2)


if __name__=='__main__': main()
