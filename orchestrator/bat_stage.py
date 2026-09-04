import csv, json
from pathlib import Path

from bat_resolver import CATALOG_PATH, resolve
from bat_collector import collect


def _read_csv(path):
    p=Path(path)
    if not p.exists() or p.stat().st_size==0: return [],[]
    with p.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); return list(reader),list(reader.fieldnames or [])


def _bridge_into_corp_docs(package):
    """Expose downloaded BAT references to the existing semantic layer without moving files.

    The authoritative BAT copy stays under output/BAT_REFERENCES.  The CORP_DOCS index
    receives metadata rows only so the already-tested document_semantics/cross-layer
    pipeline can read the PDF by stored_path.  Archive stage later refreshes the company
    document lane independently, so this bridge never rewrites retained source evidence.
    """
    package=Path(package)
    corp=package/'output'/'CORP_DOCS'/'document_index.csv'
    bat=package/'output'/'BAT_REFERENCES'/'document_index.csv'
    corp_rows,fields=_read_csv(corp); bat_rows,_=_read_csv(bat)
    if not bat_rows: return 0
    bridge=[]
    for row in bat_rows:
        if row.get('collection_status')!='DOWNLOADED': continue
        bridge.append({
            'document_id':row.get('document_id',''),'document_type':'BAT_REFERENCE','title':row.get('title',''),
            'report_year':row.get('report_year',''),'source_url':row.get('source_url',''),
            'source_locator':row.get('source_locator',''),'stored_path':row.get('stored_path',''),
            'collection_status':'DOWNLOADED','verification_status':row.get('verification_status','SOURCE_VERIFIED'),
            'importance':'SUPPORTING','notes':(row.get('notes','')+'; BAT_STAGE_BRIDGE').strip('; ')
        })
    if not bridge: return 0
    if not fields:
        fields=['document_id','document_type','title','report_year','source_url','source_locator','stored_path','collection_status','verification_status','importance','notes']
    for row in bridge:
        for key in row:
            if key not in fields: fields.append(key)
    existing={str(r.get('document_id') or '') for r in corp_rows}
    added=[r for r in bridge if str(r.get('document_id') or '') not in existing]
    if not added: return 0
    corp.parent.mkdir(parents=True,exist_ok=True)
    with corp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(corp_rows+added)
    return len(added)


def run(package,catalog_path=CATALOG_PATH,as_of=None):
    package=Path(package)
    plan=resolve(package,catalog_path,as_of)
    status=collect(package,catalog_path)
    bridged=_bridge_into_corp_docs(package)
    summary={
        'schema_version':'1.1',
        'candidate_count':plan.get('candidate_count',0),
        'site_count':plan.get('site_count',0),
        'collect_catalog_ids':plan.get('collect_catalog_ids',[]),
        'collection_status':status,
        'semantic_bridge_documents':bridged,
        'principle':'Many-to-many site/BAT candidates; current legal applicability, future applicability and technical relevance remain separate. A candidate or downloaded reference never proves company adoption.'
    }
    (package/'BAT_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary


if __name__=='__main__':
    import argparse
    from datetime import date
    ap=argparse.ArgumentParser(); ap.add_argument('--package',default='assembled'); ap.add_argument('--catalog',default=str(CATALOG_PATH)); ap.add_argument('--as-of',default='')
    a=ap.parse_args(); d=date.fromisoformat(a.as_of) if a.as_of else None
    print(json.dumps(run(a.package,a.catalog,d),ensure_ascii=False,indent=2))
