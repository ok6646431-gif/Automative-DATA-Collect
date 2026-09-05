"""Inspect the current BREFOS standard-document UI without mutating the BAT catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

BREFOS_LIST='https://ieps.nier.go.kr/brefos/home/board/standardDoc/list.do'
BREFOS_PDF='https://ieps.nier.go.kr/brefos/common/file/pdfDocPdf.do?atchFileId={atch_file_id}'
DOC_VIEW_RE=re.compile(r"fn_docView\(\s*(\d+)\s*,\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]?(\d+)['\"]?\s*\)",re.I)
ZIP_RE=re.compile(r"fn_zipDown\(\s*['\"]?(\d+)['\"]?\s*,\s*['\"]([^'\"]+)['\"]\s*\)",re.I)


def probe(out_dir: Path, verify_ids=None) -> dict:
    import requests
    from bs4 import BeautifulSoup

    verify_ids={str(x) for x in (verify_ids or []) if str(x).strip()}
    out_dir=Path(out_dir); out_dir.mkdir(parents=True,exist_ok=True)
    payload={
        'schema_version':'1.1',
        'checked_at':datetime.now(timezone.utc).isoformat(),
        'requested_url':BREFOS_LIST,
        'status':'SOURCE_UNREACHABLE',
        'forms':[], 'links':[], 'script_endpoints':[], 'documents':[],
    }
    s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0 (BREFOSDiscoveryProbe/1.1; official-public-reference)'})
    try:
        r=s.get(BREFOS_LIST,timeout=(10,30),allow_redirects=True)
        r.raise_for_status()
    except Exception as exc:
        payload['error']=f'{type(exc).__name__}: {exc}'
        return payload

    payload.update({
        'status':'RESPONDED',
        'final_url':r.url,
        'http_status':r.status_code,
        'content_type':r.headers.get('content-type',''),
        'bytes':len(r.content),
    })
    html_path=out_dir/'BREFOS_standardDoc_list.html'
    html_path.write_bytes(r.content)
    payload['html_path']=str(html_path)

    soup=BeautifulSoup(r.text,'html.parser')
    for form in soup.find_all('form'):
        inputs=[]
        for el in form.find_all(['input','select','textarea']):
            inputs.append({
                'tag':el.name,
                'name':str(el.get('name') or ''),
                'type':str(el.get('type') or ''),
                'value':str(el.get('value') or ''),
            })
        payload['forms'].append({
            'id':str(form.get('id') or ''),
            'name':str(form.get('name') or ''),
            'method':str(form.get('method') or 'GET').upper(),
            'action':urljoin(r.url,str(form.get('action') or '')),
            'inputs':inputs,
        })

    seen=set(); title_by_attachment={}; view_by_attachment={}
    for a in soup.find_all('a'):
        href=str(a.get('href') or '').strip()
        onclick=str(a.get('onclick') or '').strip()
        text=' '.join(a.stripped_strings).strip()
        raw=' '.join((href,onclick,text))
        vm=DOC_VIEW_RE.search(onclick)
        if vm:
            atch,origin,ntt=vm.groups()
            view_by_attachment[atch]={'atch_file_id':atch,'stdrdoc_origin_id':origin,'ntt_id':ntt}
        zm=ZIP_RE.search(onclick)
        if zm:
            atch,title=zm.groups(); title_by_attachment[atch]=title.strip()
        if not any(k in raw.lower() for k in ('standarddoc','download','file','view','detail','bref','최적','기준서','fn_docview','fn_zipdown')):
            continue
        key=(href,onclick,text)
        if key in seen: continue
        seen.add(key)
        payload['links'].append({
            'text':text[:300],
            'href':urljoin(r.url,href) if href and not href.lower().startswith('javascript:') else href,
            'onclick':onclick[:1000],
        })

    for atch in sorted(set(view_by_attachment)|set(title_by_attachment),key=lambda x:int(x),reverse=True):
        doc={**view_by_attachment.get(atch,{'atch_file_id':atch,'stdrdoc_origin_id':'','ntt_id':''})}
        doc['title']=title_by_attachment.get(atch,'')
        doc['viewer_pdf_url']=BREFOS_PDF.format(atch_file_id=atch)
        doc['byte_verification']={'status':'NOT_REQUESTED'}
        if atch in verify_ids:
            try:
                rr=s.get(doc['viewer_pdf_url'],timeout=(10,180),allow_redirects=True)
                rr.raise_for_status()
                body=rr.content
                is_pdf=body.lstrip().startswith(b'%PDF-')
                doc['byte_verification']={
                    'status':'VERIFIED_PDF' if is_pdf else 'RESPONDED_NOT_PDF',
                    'final_url':rr.url,
                    'http_status':rr.status_code,
                    'content_type':rr.headers.get('content-type',''),
                    'bytes':len(body),
                    'is_pdf':is_pdf,
                    'sha256':hashlib.sha256(body).hexdigest(),
                }
            except Exception as exc:
                doc['byte_verification']={'status':'SOURCE_UNREACHABLE','error':f'{type(exc).__name__}: {exc}'}
        payload['documents'].append(doc)

    scripts='\n'.join(x.get_text('\n') for x in soup.find_all('script'))
    endpoint_pattern=re.compile(r"[\"']([^\"']*(?:standardDoc|download|file|view|detail)[^\"']*\.do(?:\?[^\"']*)?)[\"']",re.I)
    endpoints=[]
    for m in endpoint_pattern.finditer(scripts):
        value=m.group(1).strip()
        if value not in endpoints:
            endpoints.append(value)
    payload['script_endpoints']=endpoints
    payload['title']=soup.title.get_text(' ',strip=True) if soup.title else ''
    payload['link_count']=len(payload['links'])
    payload['form_count']=len(payload['forms'])
    payload['document_count']=len(payload['documents'])
    payload['verified_document_count']=sum(d.get('byte_verification',{}).get('status')=='VERIFIED_PDF' for d in payload['documents'])
    return payload


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out-dir',default='brefos-probe')
    ap.add_argument('--verify-ids',nargs='*',default=[])
    args=ap.parse_args()
    out=Path(args.out_dir); payload=probe(out,args.verify_ids)
    out.mkdir(parents=True,exist_ok=True)
    (out/'BREFOS_Probe.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:payload.get(k) for k in ('status','final_url','http_status','bytes','title','form_count','link_count','document_count','verified_document_count')},ensure_ascii=False,indent=2))
    for d in payload.get('documents',[]):
        if d.get('atch_file_id') in set(args.verify_ids):
            print(json.dumps(d,ensure_ascii=False,indent=2))
    if payload.get('error'): print(payload['error'])


if __name__=='__main__': main()
