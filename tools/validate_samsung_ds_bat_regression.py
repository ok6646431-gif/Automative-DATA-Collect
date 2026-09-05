#!/usr/bin/env python3
import csv, json, sys, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ORCH=ROOT/'orchestrator'
if str(ORCH) not in sys.path: sys.path.insert(0,str(ORCH))

from archive_acceptance import assert_pass, validate_archive_zip


def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def main():
    root=Path(sys.argv[1] if len(sys.argv)>1 else 'samsung-assembled')
    candidates=rows(root/'BAT_Applicability_Candidates.csv')
    semiconductor=[r for r in candidates if 'SEMICONDUCT' in ((r.get('catalog_family') or '')+' '+(r.get('catalog_id') or '')).upper()]
    if len(semiconductor)!=5:
        raise SystemExit(f'Expected one semiconductor BAT candidate for each of 5 DS sites, got {len(semiconductor)}: {semiconductor}')
    if {r.get('catalog_id') for r in semiconductor}!={'KBREF_SEMICONDUCTOR_II_2025'}:
        raise SystemExit(f'BREFOS byte-verified semiconductor II is not the active site candidate: {semiconductor}')
    if any(r.get('collection_action')!='COLLECT' for r in semiconductor):
        raise SystemExit(f'Verified published semiconductor II BAT is not collectable: {semiconductor}')

    unrelated=[r for r in candidates if any(x in ((r.get('catalog_family') or '')+' '+(r.get('catalog_id') or '')).upper() for x in ['PLASTIC','ALCOHOL','RUBBER'])]
    if unrelated:
        raise SystemExit(f'Out-of-scope industry BAT candidates leaked: {unrelated}')

    plan=json.loads((root/'BAT_Collection_Plan.json').read_text(encoding='utf-8'))
    scope=plan.get('requested_scope_filter') or {}
    if not scope.get('applied') or scope.get('removed_out_of_scope_candidates',0)<1:
        raise SystemExit(f'Requested SITE_SET BAT scope filter was not proven: {scope}')
    if plan.get('site_count')!=5:
        raise SystemExit(f'BAT plan site_count must be 5 after scope filter: {plan.get("site_count")}')

    advisory=json.loads((root/'BAT_Catalog_Advisories.json').read_text(encoding='utf-8'))
    by_id={a.get('catalog_id'):a for a in advisory.get('advisories',[])}
    current=by_id.get('KBREF_SEMICONDUCTOR_II_2025') or {}
    if current.get('reason_code')!='BREFOS_PUBLISHED_REVISION_BYTE_VERIFIED' or current.get('include_in_effective_catalog') is not True:
        raise SystemExit(f'Semiconductor II publication authority advisory missing: {current}')
    old=by_id.get('KBREF_SEMICONDUCTOR_2019') or {}
    if old.get('reason_code')!='SUPERSEDED_BY_BREFOS_VERIFIED_REVISION_II':
        raise SystemExit(f'Semiconductor 2019 supersession advisory missing: {old}')

    docs=rows(root/'output'/'BAT_REFERENCES'/'document_index.csv')
    semi_docs=[r for r in docs if 'SEMICONDUCT' in ((r.get('catalog_family') or '')+' '+(r.get('catalog_id') or '')).upper()]
    downloaded=[r for r in semi_docs if r.get('collection_status')=='DOWNLOADED']
    if not downloaded:
        raise SystemExit(f'No official semiconductor II BAT PDF downloaded: {semi_docs}')
    if any(r.get('catalog_id')!='KBREF_SEMICONDUCTOR_II_2025' for r in downloaded):
        raise SystemExit(f'Unexpected semiconductor revision downloaded: {downloaded}')
    if any((r.get('sha256') or r.get('official_pdf_sha256') or '') not in ('','05cc62d6c9971c5917f583ba6e7459af7eb0f776c3dccbe7eba81164675edb02') for r in downloaded):
        raise SystemExit(f'Downloaded semiconductor II hash conflicts with verified BREFOS bytes: {downloaded}')

    assert_pass(validate_archive_zip(root/'Human_Archive.zip'),'Samsung Human Archive')
    with zipfile.ZipFile(root/'Human_Archive.zip') as z:
        names=[i.filename for i in z.infolist() if not i.is_dir()]
        bat_files=[n for n in names if '/02_BAT_참고자료/' in n]
        semi_pdfs=[n for n in bat_files if n.lower().endswith('.pdf') and ('반도체' in n or 'SEMICONDUCT' in n.upper())]
        legacy=[n for n in names if '/01_사용자자료/07_가이드라인_참고자료/BAT_기준서/' in n]
        maps=[n for n in bat_files if '/02_사업장별_적용맵/' in n and n.endswith('_BAT_적용맵.xlsx')]
        if not semi_pdfs: raise SystemExit(f'No semiconductor BAT PDF in dedicated BAT area: {bat_files}')
        if legacy: raise SystemExit(f'Legacy embedded BAT area present: {legacy}')
        if len(maps)<5: raise SystemExit(f'Expected BAT applicability maps for 5 DS sites, got {len(maps)}: {maps}')

    source_statuses={}
    for source in ['ENVINFO','PRTR','CHEM_STATS','CLEANSYS_AIR','SOOSIRO_WATER','CORP_DOCS','BAT_REFERENCES']:
        p=root/'output'/source/'status.json'
        source_statuses[source]=json.loads(p.read_text(encoding='utf-8')).get('status') if p.exists() else None
    print(json.dumps({
        'SAMSUNG_DS_REGRESSION':'PASS',
        'site_scope':5,
        'bat_candidate_count':len(candidates),
        'semiconductor_candidates':len(semiconductor),
        'semiconductor_revision':'KBREF_SEMICONDUCTOR_II_2025',
        'semiconductor_downloaded_docs':len(downloaded),
        'site_maps':len(maps),
        'bat_files':len(bat_files),
        'scope_removed_candidates':scope.get('removed_out_of_scope_candidates'),
        'source_statuses':source_statuses,
    },ensure_ascii=False))


if __name__=='__main__': main()
