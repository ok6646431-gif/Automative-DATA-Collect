"""Reconcile byte-verified BREFOS documents with preferred BAT master-catalog entries.

This is an audit/suggestion layer only. It does not mutate bat_master_catalog.json.
Only strong title-family matches with aligned revision generation are AUTO_MATCH.
"""
from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List

try:
    from .bat_catalog_effective import CATALOG_PATH, build_effective_catalog
except ImportError:
    from bat_catalog_effective import CATALOG_PATH, build_effective_catalog

COMMON_PATTERNS=[
    r'\[[12]기(?:-part\s*\d+)?\]', r'\([ⅠⅡⅢIVX]+\)', r'\bpart\s*\d+\b',
    r'환경오염방지', r'통합환경관리', r'통합관리', r'최적가용기법', r'기준서',
    r'환경오염의 예방과 최적관리를 위한', r'환경오염 예방 및 통합관리를 위한',
]


def core_title(value: str) -> str:
    text=str(value or '').lower()
    for pat in COMMON_PATTERNS:
        text=re.sub(pat,' ',text,flags=re.I)
    text=re.sub(r'[\s·ㆍ,./()\[\]{}:_\-]+','',text)
    # possessive particles after industry/facility phrases add no identity value.
    text=text.replace('제조업의','제조업').replace('산업의','산업').replace('시설의','시설').replace('가공업의','가공업')
    return text


def brefos_generation(title: str) -> int:
    m=re.search(r'\[\s*([12])기',str(title or ''))
    return int(m.group(1)) if m else 0


def master_generation(entry: Dict[str,Any]) -> int:
    raw=str(entry.get('revision_generation') or '').strip().upper()
    if raw in {'II','2','Ⅱ'}: return 2
    if raw in {'I','1','Ⅰ'}: return 1
    title=str(entry.get('title') or '')
    if 'Ⅱ' in title or '(II)' in title.upper(): return 2
    return 1 if entry.get('publication_status')=='PUBLISHED' else 0


def similarity(a: str,b: str) -> float:
    if not a or not b: return 0.0
    if a==b: return 1.0
    if a in b or b in a:
        return min(len(a),len(b))/max(len(a),len(b)) * 0.98 + 0.02
    return SequenceMatcher(None,a,b).ratio()


def reconcile(registry: Dict[str,Any], catalog_path: Path=CATALOG_PATH) -> Dict[str,Any]:
    effective,_=build_effective_catalog(Path(catalog_path))
    preferred=[e for e in effective.get('entries',[]) if e.get('preferred') is not False and str(e.get('publication_status') or '').upper()=='PUBLISHED']
    verified=[d for d in registry.get('documents',[]) if d.get('status')=='VERIFIED_PDF']

    master_rows=[]
    matched_brefos=set()
    for entry in preferred:
        mcore=core_title(entry.get('title','')); mgen=master_generation(entry)
        candidates=[]
        for doc in verified:
            bcore=core_title(doc.get('title','')); bgen=brefos_generation(doc.get('title',''))
            score=similarity(mcore,bcore)
            if bgen and mgen and bgen!=mgen: score*=0.45
            candidates.append((score,doc,bcore,bgen))
        candidates.sort(key=lambda x:x[0],reverse=True)
        best=candidates[0] if candidates else (0,None,'',0)
        best_score,best_doc,bcore,bgen=best
        state='AUTO_MATCH' if best_doc and best_score>=0.82 and (not bgen or not mgen or bgen==mgen) else ('REVIEW' if best_doc and best_score>=0.60 else 'NO_MATCH')
        docs=[]
        if state=='AUTO_MATCH':
            # Preserve all BREFOS parts belonging to the same normalized family/generation.
            for score,doc,dc,dg in candidates:
                if dg==bgen and similarity(bcore,dc)>=0.94:
                    docs.append({
                        'atch_file_id':doc.get('atch_file_id'),'ntt_id':doc.get('ntt_id'),'title':doc.get('title'),
                        'official_pdf_url':doc.get('viewer_pdf_url') or doc.get('url'),'bytes':doc.get('bytes'),'sha256':doc.get('sha256'),
                    })
                    matched_brefos.add(str(doc.get('atch_file_id')))
        elif best_doc:
            docs=[{'atch_file_id':best_doc.get('atch_file_id'),'ntt_id':best_doc.get('ntt_id'),'title':best_doc.get('title'),'official_pdf_url':best_doc.get('viewer_pdf_url') or best_doc.get('url'),'bytes':best_doc.get('bytes'),'sha256':best_doc.get('sha256')}]
        master_rows.append({
            'catalog_id':entry.get('catalog_id'),'catalog_family':entry.get('catalog_family'),'master_title':entry.get('title'),
            'master_core':mcore,'master_generation':mgen,'match_state':state,'match_score':round(best_score,4),
            'matched_documents':docs,'matched_document_count':len(docs),
            'locator_already_present':bool(entry.get('official_pdf_url') or entry.get('official_documents')),
            'sha_already_present':bool(entry.get('official_pdf_sha256') or any((x or {}).get('official_pdf_sha256') for x in (entry.get('official_documents') or []))),
        })

    # Latest BREFOS generation per normalized title family that is not represented by an AUTO_MATCH.
    groups={}
    for doc in verified:
        core=core_title(doc.get('title','')); gen=brefos_generation(doc.get('title',''))
        groups.setdefault(core,[]).append((gen,doc))
    missing=[]
    for core,items in groups.items():
        latest=max((g for g,_ in items),default=0)
        latest_docs=[d for g,d in items if g==latest]
        if any(str(d.get('atch_file_id')) in matched_brefos for d in latest_docs):
            continue
        best=max((similarity(core,core_title(e.get('title',''))) for e in preferred),default=0)
        if best<0.82:
            missing.append({'brefos_core':core,'generation':latest,'titles':[d.get('title') for d in latest_docs],'atch_file_ids':[d.get('atch_file_id') for d in latest_docs],'best_master_similarity':round(best,4)})

    counts={}
    for row in master_rows: counts[row['match_state']]=counts.get(row['match_state'],0)+1
    return {
        'schema_version':'1.0','registry_status':registry.get('status'),'verified_pdf_count':registry.get('verified_pdf_count',0),
        'preferred_published_master_entries':len(preferred),'match_state_counts':counts,'master_matches':master_rows,
        'latest_brefos_families_missing_in_master':missing,
        'principle':'Reconciliation is advisory. Catalog mutation requires VERIFIED_PDF plus AUTO_MATCH; REVIEW and MISSING_IN_MASTER never auto-promote.'
    }


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--registry',required=True); ap.add_argument('--out',default='BREFOS_Master_Reconcile.json'); ap.add_argument('--catalog',default=str(CATALOG_PATH)); args=ap.parse_args()
    registry=json.loads(Path(args.registry).read_text(encoding='utf-8'))
    result=reconcile(registry,Path(args.catalog))
    Path(args.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'registry_status':result.get('registry_status'),'verified_pdf_count':result.get('verified_pdf_count'),'preferred_master':result.get('preferred_published_master_entries'),'match_state_counts':result.get('match_state_counts'),'missing_latest_brefos_families':len(result.get('latest_brefos_families_missing_in_master',[]))},ensure_ascii=False,indent=2))


if __name__=='__main__': main()
