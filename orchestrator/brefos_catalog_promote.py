"""Build a reviewable BAT master-catalog promotion candidate from BREFOS verification.

This command never writes to the repository. It reads a byte registry plus reconciliation
report and writes a proposed catalog and a promotion report. Only VERIFIED_PDF documents
that belong to AUTO_MATCH rows are eligible. Existing conflicting URL/SHA values are a
hard block rather than being overwritten silently.
"""
from __future__ import annotations

import argparse
import copy
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

BREFOS_LIST='https://ieps.nier.go.kr/brefos/home/board/standardDoc/list.do'


def _read(path: Path) -> Dict[str,Any]:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _verified_by_id(registry: Dict[str,Any]) -> Dict[str,Dict[str,Any]]:
    return {
        str(d.get('atch_file_id')): d
        for d in registry.get('documents',[]) or []
        if d.get('status')=='VERIFIED_PDF' and d.get('atch_file_id') is not None
    }


def _same_or_blank(existing: str, proposed: str) -> bool:
    return not str(existing or '').strip() or str(existing).strip()==str(proposed).strip()


def build_candidate(master: Dict[str,Any], registry: Dict[str,Any], reconcile: Dict[str,Any]) -> tuple[Dict[str,Any],Dict[str,Any]]:
    candidate=copy.deepcopy(master)
    entries={str(e.get('catalog_id')):e for e in candidate.get('entries',[]) or []}
    verified=_verified_by_id(registry)
    report={
        'schema_version':'1.0',
        'status':'PASS',
        'registry_status':registry.get('status'),
        'promoted':[],
        'skipped':[],
        'blocked':[],
        'principles':[
            'Only reconciliation AUTO_MATCH rows are considered.',
            'Every promoted document must independently be VERIFIED_PDF in the byte registry.',
            'Existing conflicting URL or SHA values are never overwritten automatically.',
            'Historical entries remain in the master catalog; this builder only hydrates matched current entries.',
        ],
    }
    if registry.get('status') not in {'PASS','PARTIAL'}:
        report['status']='BLOCKED'; report['blocked'].append({'reason':'REGISTRY_NOT_USABLE','registry_status':registry.get('status')})
        return candidate,report

    for match in reconcile.get('master_matches',[]) or []:
        if match.get('match_state')!='AUTO_MATCH':
            continue
        cid=str(match.get('catalog_id') or '')
        entry=entries.get(cid)
        if not entry:
            report['blocked'].append({'catalog_id':cid,'reason':'MASTER_ENTRY_NOT_FOUND'}); continue
        docs=match.get('matched_documents',[]) or []
        if not docs:
            report['blocked'].append({'catalog_id':cid,'reason':'AUTO_MATCH_WITHOUT_DOCUMENT'}); continue

        hydrated=[]; invalid=[]
        for i,doc in enumerate(docs,1):
            aid=str(doc.get('atch_file_id') or '')
            source=verified.get(aid)
            if not source:
                invalid.append({'atch_file_id':aid,'reason':'NOT_VERIFIED_IN_REGISTRY'}); continue
            proposed_url=str(source.get('viewer_pdf_url') or source.get('url') or '')
            proposed_sha=str(source.get('sha256') or '')
            if not proposed_url or len(proposed_sha)!=64:
                invalid.append({'atch_file_id':aid,'reason':'VERIFIED_ROW_MISSING_URL_OR_SHA'}); continue
            hydrated.append({
                'document_part':f'PART_{i}' if len(docs)>1 else 'MAIN',
                'title':str(source.get('title') or doc.get('title') or entry.get('title') or ''),
                'atch_file_id':aid,
                'ntt_id':str(source.get('ntt_id') or doc.get('ntt_id') or ''),
                'official_pdf_url':proposed_url,
                'official_pdf_sha256':proposed_sha,
                'official_pdf_bytes':int(source.get('bytes') or 0),
            })
        if invalid or len(hydrated)!=len(docs):
            report['blocked'].append({'catalog_id':cid,'reason':'DOCUMENT_VERIFICATION_INCOMPLETE','details':invalid}); continue

        if len(hydrated)==1:
            d=hydrated[0]
            if not _same_or_blank(entry.get('official_pdf_url',''),d['official_pdf_url']) or not _same_or_blank(entry.get('official_pdf_sha256',''),d['official_pdf_sha256']):
                report['blocked'].append({'catalog_id':cid,'reason':'EXISTING_SINGLE_DOCUMENT_CONFLICT','existing_url':entry.get('official_pdf_url',''),'proposed_url':d['official_pdf_url'],'existing_sha':entry.get('official_pdf_sha256',''),'proposed_sha':d['official_pdf_sha256']}); continue
            entry['official_pdf_url']=d['official_pdf_url']
            entry['official_pdf_sha256']=d['official_pdf_sha256']
            entry['official_pdf_bytes']=d['official_pdf_bytes']
            entry.pop('official_documents',None)
        else:
            existing_docs=entry.get('official_documents') or []
            if existing_docs:
                existing_pairs={(str(d.get('official_pdf_url') or ''),str(d.get('official_pdf_sha256') or '')) for d in existing_docs if isinstance(d,dict)}
                proposed_pairs={(d['official_pdf_url'],d['official_pdf_sha256']) for d in hydrated}
                if existing_pairs!=proposed_pairs:
                    report['blocked'].append({'catalog_id':cid,'reason':'EXISTING_MULTI_DOCUMENT_CONFLICT','existing_document_count':len(existing_docs),'proposed_document_count':len(hydrated)}); continue
            if str(entry.get('official_pdf_url') or '').strip() or str(entry.get('official_pdf_sha256') or '').strip():
                report['blocked'].append({'catalog_id':cid,'reason':'SINGLE_TO_MULTI_CONFLICT'}); continue
            entry['official_documents']=hydrated
            entry['official_pdf_url']=''
            entry['official_pdf_sha256']=''

        entry['official_source_locator']=BREFOS_LIST
        entry['official_document_page']=BREFOS_LIST
        if str(entry.get('publication_status') or '').upper()=='PUBLISHED':
            entry['collection_policy']='COLLECT_WHEN_MATCHED'
        stamp=str(date.today())
        note=f"{stamp} BREFOS 현행 목록 및 원문 PDF byte 검증 완료"
        if len(hydrated)>1:
            note+=f" ({len(hydrated)}개 part 모두 검증)."
        else:
            note+=f" ({hydrated[0]['official_pdf_bytes']:,} bytes, SHA-256 {hydrated[0]['official_pdf_sha256']})."
        old=str(entry.get('notes') or '').strip()
        if note not in old:
            entry['notes']=(old+' '+note).strip()
        report['promoted'].append({'catalog_id':cid,'document_count':len(hydrated),'documents':hydrated})

    if report['blocked']:
        report['status']='BLOCKED'
    candidate['catalog_as_of']=str(date.today())
    candidate.setdefault('discovery',{})
    candidate['discovery'].update({
        'primary_list_url':BREFOS_LIST,
        'verified_list_item_count':registry.get('discovered_document_count'),
        'verified_on':str(date.today()),
        'registry_status':registry.get('status'),
    })
    return candidate,report


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--catalog',required=True)
    ap.add_argument('--registry',required=True)
    ap.add_argument('--reconcile',required=True)
    ap.add_argument('--out-catalog',default='BAT_Master_Catalog_Proposed.json')
    ap.add_argument('--out-report',default='BREFOS_Promotion_Report.json')
    args=ap.parse_args()
    candidate,report=build_candidate(_read(Path(args.catalog)),_read(Path(args.registry)),_read(Path(args.reconcile)))
    Path(args.out_catalog).write_text(json.dumps(candidate,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    Path(args.out_report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'promoted':len(report['promoted']),'blocked':len(report['blocked']),'skipped':len(report['skipped'])},ensure_ascii=False,indent=2))
    if report['blocked']:
        raise SystemExit(2)


if __name__=='__main__': main()
