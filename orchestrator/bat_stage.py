import csv, json
from pathlib import Path

from bat_resolver import CATALOG_PATH, CANDIDATE_FIELDS, resolve
from bat_collector import collect
from bat_catalog_effective import materialize_effective_catalog
from requested_scope import _selected_address_counts, _candidate_matches


def _read_csv(path):
    p=Path(path)
    if not p.exists() or p.stat().st_size==0: return [],[]
    with p.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); return list(reader),list(reader.fieldnames or [])


def _write_csv(path,rows,fields):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)


def _bridge_into_corp_docs(package):
    """Expose downloaded BAT references to the existing semantic layer without moving files."""
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


def _canonical_candidate_map(package):
    package=Path(package)
    profile=json.loads((package/'Company_Profile.json').read_text(encoding='utf-8')) if (package/'Company_Profile.json').exists() else {}
    candidates=[c for c in profile.get('site_candidates',[]) or [] if isinstance(c,dict)]
    scope_ids=set((profile.get('requested_scope') or {}).get('candidate_ids',[]) or [])
    selected=[c for c in candidates if not scope_ids or str(c.get('candidate_id') or '') in scope_ids]
    address_counts=_selected_address_counts(selected)
    sites,_=_read_csv(package/'Site_Master.csv')
    inverse={}
    for candidate in selected:
        candidate_id=str(candidate.get('candidate_id') or '')
        if not candidate_id: continue
        for site in sites:
            if site.get('identity_status')!='CONFIRMED': continue
            if _candidate_matches(candidate,site.get('canonical_site_name'),site.get('canonical_address_key'),profile,address_counts):
                cid=str(site.get('canonical_site_id') or '')
                if cid: inverse.setdefault(cid,[]).append(candidate_id)
    return profile,inverse


def _filter_plan_to_requested_scope(package,plan):
    """Apply the same verified SITE_SET boundary used by Archive/analysis to BAT candidates.

    Raw environmental collectors remain company-wide, but BAT applicability is a
    downstream interpretation product. It must never project candidates from an
    out-of-scope site into a site-scoped application package.
    """
    package=Path(package); profile,inverse=_canonical_candidate_map(package)
    scope=profile.get('requested_scope') or {'mode':'COMPANY'}
    requested_ids={str(x) for x in scope.get('candidate_ids',[]) or [] if str(x)}
    mode=str(scope.get('mode') or 'COMPANY').upper()
    audit={
        'applied':False,'mode':mode,'requested_candidate_ids':sorted(requested_ids),
        'allowed_canonical_site_ids':[],'mapped_candidate_ids':[],'unmapped_candidate_ids':[],
        'candidate_count_before':len(plan.get('candidates',[]) or []),'candidate_count_after':len(plan.get('candidates',[]) or []),
        'removed_out_of_scope_candidates':0,
    }
    if mode!='SITE_SET' or not requested_ids:
        return plan,audit

    allowed=set(inverse)
    mapped={candidate_id for values in inverse.values() for candidate_id in values}
    filtered=[r for r in (plan.get('candidates',[]) or []) if str(r.get('canonical_site_id') or '') in allowed]
    removed=len(plan.get('candidates',[]) or [])-len(filtered)
    scoped=dict(plan)
    scoped['candidates']=filtered
    scoped['candidate_count']=len(filtered)
    scoped['site_count']=len({str(r.get('canonical_site_id') or '') for r in filtered if r.get('canonical_site_id')})
    scoped['collect_catalog_ids']=sorted({str(r.get('catalog_id') or '') for r in filtered if r.get('collection_action')=='COLLECT' and r.get('catalog_id')})
    boundaries=list(scoped.get('boundaries',[]) or [])
    note='Requested SITE_SET scope is applied before BAT collection; out-of-scope company sites cannot create BAT applicability candidates.'
    if note not in boundaries: boundaries.append(note)
    scoped['boundaries']=boundaries
    audit.update({
        'applied':True,
        'allowed_canonical_site_ids':sorted(allowed),
        'mapped_candidate_ids':sorted(mapped),
        'unmapped_candidate_ids':sorted(requested_ids-mapped),
        'candidate_count_after':len(filtered),
        'removed_out_of_scope_candidates':removed,
    })
    scoped['requested_scope_filter']=audit
    _write_csv(package/'BAT_Applicability_Candidates.csv',filtered,CANDIDATE_FIELDS)
    (package/'BAT_Collection_Plan.json').write_text(json.dumps(scoped,ensure_ascii=False,indent=2),encoding='utf-8')
    return scoped,audit


def _write_auto_applicability(package):
    """Convert strong resolver matches into cross-layer reference applicability.

    VERIFIED here means only that the reference is applicable context for the selected
    site; it explicitly does not mean the company has adopted the BAT technique.
    """
    package=Path(package); profile,inverse=_canonical_candidate_map(package)
    candidates,_=_read_csv(package/'BAT_Applicability_Candidates.csv')
    docs,_=_read_csv(package/'output'/'BAT_REFERENCES'/'document_index.csv')
    by_catalog={}
    for row in candidates: by_catalog.setdefault(row.get('catalog_id',''),[]).append(row)
    refs=[]
    for doc in docs:
        if doc.get('collection_status')!='DOWNLOADED': continue
        group=by_catalog.get(doc.get('catalog_id',''),[])
        strong=[r for r in group if r.get('applicability_state')=='STRONG_CANDIDATE']
        canonical=sorted({r.get('canonical_site_id','') for r in strong if r.get('canonical_site_id')})
        candidate_ids=[]
        for cid in canonical: candidate_ids.extend(inverse.get(cid,[]))
        candidate_ids=sorted(set(candidate_ids))
        refs.append({
            'document_id':doc.get('document_id',''),
            'applicability_state':'VERIFIED' if canonical and candidate_ids else 'REVIEW_REQUIRED',
            'candidate_ids':candidate_ids,
            'reference_domains':[x for x in str(doc.get('reference_domains') or '').split('|') if x],
            'basis':' | '.join(sorted({r.get('evidence_basis','') for r in strong if r.get('evidence_basis')})),
            'source_locator':doc.get('source_locator',''),
            'interpretation_boundary':'Verified reference applicability only; no inference that the company has adopted or operates the BAT technique.'
        })
    payload={'schema_version':'1.0','request_id':profile.get('request_id',''),'references':refs}
    path=package/'BAT_Industry_Reference_Applicability.json'
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    return path,refs


def run(package,catalog_path=CATALOG_PATH,as_of=None):
    package=Path(package)
    effective_catalog_path,catalog_advisories=materialize_effective_catalog(package,catalog_path)
    plan=resolve(package,effective_catalog_path,as_of)
    plan,scope_filter=_filter_plan_to_requested_scope(package,plan)
    status=collect(package,effective_catalog_path)
    bridged=_bridge_into_corp_docs(package)
    applicability_path,refs=_write_auto_applicability(package)
    summary={
        'schema_version':'1.3',
        'candidate_count':plan.get('candidate_count',0),
        'site_count':plan.get('site_count',0),
        'collect_catalog_ids':plan.get('collect_catalog_ids',[]),
        'collection_status':status,
        'semantic_bridge_documents':bridged,
        'verified_reference_applicability':sum(r.get('applicability_state')=='VERIFIED' for r in refs),
        'applicability_path':str(applicability_path),
        'effective_catalog_path':str(effective_catalog_path),
        'catalog_advisory_count':len(catalog_advisories),
        'requested_scope_filter':scope_filter,
        'principle':'Many-to-many site/BAT candidates; current legal applicability, future applicability and technical relevance remain separate. A candidate or downloaded reference never proves company adoption. Newer revision planning does not supersede the last verified published reference until final publication is independently verified.'
    }
    (package/'BAT_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary


if __name__=='__main__':
    import argparse
    from datetime import date
    ap=argparse.ArgumentParser(); ap.add_argument('--package',default='assembled'); ap.add_argument('--catalog',default=str(CATALOG_PATH)); ap.add_argument('--as-of',default='')
    a=ap.parse_args(); d=date.fromisoformat(a.as_of) if a.as_of else None
    print(json.dumps(run(a.package,a.catalog,d),ensure_ascii=False,indent=2))
