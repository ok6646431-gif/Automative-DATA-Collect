"""Inspect the current BREFOS standard-document UI without mutating the BAT catalog."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

BREFOS_LIST='https://ieps.nier.go.kr/brefos/home/board/standardDoc/list.do'


def probe(out_dir: Path) -> dict:
    import requests
    from bs4 import BeautifulSoup

    out_dir=Path(out_dir); out_dir.mkdir(parents=True,exist_ok=True)
    payload={
        'schema_version':'1.0',
        'checked_at':datetime.now(timezone.utc).isoformat(),
        'requested_url':BREFOS_LIST,
        'status':'SOURCE_UNREACHABLE',
        'forms':[], 'links':[], 'script_endpoints':[],
    }
    s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0 (BREFOSDiscoveryProbe/1.0; official-public-reference)'})
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

    seen=set()
    for a in soup.find_all('a'):
        href=str(a.get('href') or '').strip()
        onclick=str(a.get('onclick') or '').strip()
        text=' '.join(a.stripped_strings).strip()
        raw=' '.join((href,onclick,text))
        if not any(k in raw.lower() for k in ('standarddoc','download','file','view','detail','bref','최적','기준서')):
            continue
        key=(href,onclick,text)
        if key in seen: continue
        seen.add(key)
        payload['links'].append({
            'text':text[:300],
            'href':urljoin(r.url,href) if href and not href.lower().startswith('javascript:') else href,
            'onclick':onclick[:1000],
        })

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
    return payload


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out-dir',default='brefos-probe'); args=ap.parse_args()
    out=Path(args.out_dir); payload=probe(out)
    out.mkdir(parents=True,exist_ok=True)
    (out/'BREFOS_Probe.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:payload.get(k) for k in ('status','final_url','http_status','bytes','title','form_count','link_count')},ensure_ascii=False,indent=2))
    if payload.get('error'): print(payload['error'])


if __name__=='__main__': main()
