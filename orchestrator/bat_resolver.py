import csv, json, re
from collections import defaultdict
from datetime import date
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name('bat_master_catalog.json')

CANDIDATE_FIELDS = [
    'candidate_id','catalog_id','canonical_site_id','site_name','candidate_role','candidate_state',
    'applicability_state','publication_status','legal_status','effective_from','matched_ksic_prefixes',
    'matched_industry_terms','matched_process_terms','matched_utility_terms','evidence_channels',
    'evidence_basis','collection_action','official_source_locator'
]

SOURCE_SPECS = {
    'ENVINFO': ('discovery.csv', ['compId','comp_id','source_site_id']),
    'PRTR': ('discovery.csv', ['entrps_id','entrpsId','source_site_id']),
    'CHEM_STATS': ('discovery.csv', ['bplcId','bplc_id','source_site_id']),
}
INDUSTRY_KEY_MARKERS = ('industry','induty','ksic','업종','업태','산업분류')
IDENTITY_KEYS = {
    'compnm','comp_nm','compname','entrps_nm','entrpsnm','bplcnm','bplc_nm','사업장명','업체명','회사명',
    'address','addr','adres','도로명주소','소재지','사업장주소'
}


def read_json(path, default=None):
    p=Path(path)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default


def read_csv(path):
    p=Path(path)
    if not p.exists() or p.stat().st_size==0: return []
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)


def norm(value):
    return re.sub(r'\s+',' ',str(value or '')).strip().lower()


def first_value(row, keys):
    for key in keys:
        if row.get(key) not in (None,''): return str(row.get(key))
    return ''


def _identity_maps(pkg):
    """Resolve source-native site IDs only through confirmed identity rows.

    Source_Identity.csv uses ``match_status`` in the canonical integration schema.
    ``identity_status`` is accepted only for compatibility with older/test fixtures.
    """
    source_map={}; site_names={}
    for row in read_csv(Path(pkg)/'Source_Identity.csv'):
        status=str(row.get('match_status') or row.get('identity_status') or '').upper()
        if status!='CONFIRMED': continue
        source=str(row.get('source_key') or '')
        sid=str(row.get('source_site_id') or '')
        cid=str(row.get('canonical_site_id') or '')
        if source and sid and cid: source_map[(source,sid)]=cid
    for row in read_csv(Path(pkg)/'Site_Master.csv'):
        cid=str(row.get('canonical_site_id') or '')
        if cid: site_names[cid]=str(row.get('canonical_site_name') or '')
    return source_map,site_names


def _industry_fields(row):
    out=[]
    for key,value in row.items():
        lk=str(key or '').lower()
        if any(marker in lk for marker in INDUSTRY_KEY_MARKERS) and value not in (None,''):
            out.append(str(value))
    return out


def _process_fields(row):
    out=[]
    for key,value in row.items():
        if value in (None,''): continue
        lk=str(key or '').lower()
        if lk in IDENTITY_KEYS: continue
        if any(marker in lk for marker in INDUSTRY_KEY_MARKERS): continue
        out.append(str(value))
    return out


def _profile_structured_evidence(profile):
    industry=[]; process=[]
    def walk(obj,key=''):
        if isinstance(obj,dict):
            for k,v in obj.items(): walk(v,str(k))
        elif isinstance(obj,list):
            for v in obj: walk(v,key)
        elif obj not in (None,''):
            lk=key.lower()
            if any(m in lk for m in INDUSTRY_KEY_MARKERS): industry.append(str(obj))
            elif any(m in lk for m in ('process','공정','facility','설비','boiler','보일러','product','제품')): process.append(str(obj))
    walk(profile)
    return industry,process


def collect_evidence(pkg):
    pkg=Path(pkg); source_map,site_names=_identity_maps(pkg)
    evidence=defaultdict(lambda:{'industry':[],'process':[],'channels':set(),'ksic_codes':set()})

    for source,(filename,id_keys) in SOURCE_SPECS.items():
        for row in read_csv(pkg/'output'/source/filename):
            sid=first_value(row,id_keys); cid=source_map.get((source,sid),'')
            if not cid: continue
            inds=_industry_fields(row); procs=_process_fields(row)
            if inds:
                evidence[cid]['industry'].extend(inds); evidence[cid]['channels'].add(f'{source}:{filename}:industry')
                for text in inds:
                    evidence[cid]['ksic_codes'].update(re.findall(r'(?<!\d)\d{2,5}(?!\d)',str(text)))
            if procs:
                evidence[cid]['process'].extend(procs); evidence[cid]['channels'].add(f'{source}:{filename}:process')

    for row in read_csv(pkg/'output'/'ENVINFO'/'attachment_index.csv'):
        sid=first_value(row,['compId','comp_id','source_site_id']); cid=source_map.get(('ENVINFO',sid),'')
        if not cid: continue
        text=' '.join(str(row.get(k) or '') for k in ['section_title','document_category','original_filename','title','attachment_name'])
        if text.strip():
            evidence[cid]['process'].append(text); evidence[cid]['channels'].add('ENVINFO:attachment_index')

    for row in read_csv(pkg/'Management_Action_Ledger.csv'):
        cid=str(row.get('canonical_site_id') or '')
        if not cid: continue
        text=' '.join(str(row.get(k) or '') for k in ['action_name','description','disclosed_effect','domain'])
        if text.strip():
            evidence[cid]['process'].append(text); evidence[cid]['channels'].add('Management_Action_Ledger')

    profile=read_json(pkg/'Company_Profile.json',{}) or {}
    p_industry,p_process=_profile_structured_evidence(profile)
    if p_industry or p_process:
        evidence['COMPANY']['industry'].extend(p_industry)
        evidence['COMPANY']['process'].extend(p_process)
        if p_industry: evidence['COMPANY']['channels'].add('Company_Profile:industry')
        if p_process: evidence['COMPANY']['channels'].add('Company_Profile:process')
        for text in p_industry:
            evidence['COMPANY']['ksic_codes'].update(re.findall(r'(?<!\d)\d{2,5}(?!\d)',str(text)))

    for row in read_csv(pkg/'Document_Semantic_Candidates.csv'):
        if str(row.get('semantic_state') or '')!='PAGE_GROUNDED_EXTRACT': continue
        text=' '.join(str(row.get(k) or '') for k in ['statement','title','domain'])
        if text.strip():
            evidence['COMPANY']['process'].append(text); evidence['COMPANY']['channels'].add('Document_Semantic_Candidates')

    return evidence,site_names


def _term_hits(terms,text):
    low=norm(text)
    return [term for term in terms if norm(term) and norm(term) in low]


def _ksic_hits(prefixes,codes):
    return [prefix for prefix in prefixes if any(str(code).startswith(str(prefix)) for code in codes)]


def _effective_is_future(value,as_of):
    if not value: return False
    try: return date.fromisoformat(str(value))>as_of
    except ValueError: return False


def resolve(pkg,catalog_path=CATALOG_PATH,as_of=None):
    pkg=Path(pkg); as_of=as_of or date.today()
    catalog=read_json(catalog_path,{}) or {}; entries=catalog.get('entries',[]) or []
    evidence,site_names=collect_evidence(pkg)
    rows=[]

    site_ids=[cid for cid in evidence if cid!='COMPANY']
    for entry in entries:
        for cid in site_ids:
            site=evidence[cid]; company=evidence.get('COMPANY',{})
            industry_text=' | '.join(site.get('industry',[]))
            process_text=' | '.join(site.get('process',[]))
            company_industry=' | '.join(company.get('industry',[]))
            company_process=' | '.join(company.get('process',[]))
            ksic=_ksic_hits(entry.get('ksic_prefixes',[]),site.get('ksic_codes',set()))
            ind=_term_hits(entry.get('industry_terms',[]),industry_text)
            proc=_term_hits(entry.get('process_terms',[]),process_text)
            util=_term_hits(entry.get('utility_terms',[]),process_text)
            company_ind=_term_hits(entry.get('industry_terms',[]),company_industry)
            company_proc=_term_hits(entry.get('process_terms',[])+entry.get('utility_terms',[]),company_process)

            direct_industry=bool(ksic or ind)
            direct_technical=bool(proc or util)
            inherited_industry=not direct_industry and bool(company_ind)
            inherited_technical=not direct_technical and bool(company_proc)
            if not (direct_industry or direct_technical or inherited_industry or inherited_technical): continue

            default_role=str(entry.get('default_role') or 'SECONDARY_PROCESS')
            if direct_industry or inherited_industry:
                role='PRIMARY' if default_role=='PRIMARY' or entry.get('reference_kind')=='INDUSTRY' else default_role
            elif util:
                role='COMMON_UTILITY'
            else:
                role='SECONDARY_PROCESS'

            future=_effective_is_future(entry.get('effective_from'),as_of) or str(entry.get('legal_status') or '').startswith('PROPOSED_')
            if future and role=='PRIMARY':
                state='FUTURE_PRIMARY_CANDIDATE'
            elif future:
                state='FUTURE_TECHNICAL_CANDIDATE'
            elif role=='PRIMARY':
                state='PRIMARY_CANDIDATE'
            else:
                state='TECHNICAL_CANDIDATE'

            direct_channels=sorted(site.get('channels',set()))
            if direct_industry or (direct_technical and len(direct_channels)>=2):
                applicability='STRONG_CANDIDATE'
            elif direct_technical:
                applicability='SUPPORTING_CANDIDATE'
            else:
                applicability='REVIEW_REQUIRED'

            pub=str(entry.get('publication_status') or '')
            if pub!='PUBLISHED': action='WAIT_FOR_PUBLICATION'
            elif applicability=='REVIEW_REQUIRED': action='REVIEW_BEFORE_COLLECTION'
            else: action='COLLECT'

            evidence_bits=[]
            if ksic: evidence_bits.append('KSIC='+','.join(ksic))
            if ind: evidence_bits.append('industry='+','.join(ind))
            if proc: evidence_bits.append('process='+','.join(proc))
            if util: evidence_bits.append('utility='+','.join(util))
            if inherited_industry: evidence_bits.append('company_industry='+','.join(company_ind))
            if inherited_technical: evidence_bits.append('company_technical='+','.join(company_proc))

            rows.append({
                'candidate_id':f"BATMAP_{entry.get('catalog_id')}_{cid}",
                'catalog_id':entry.get('catalog_id',''),'canonical_site_id':cid,'site_name':site_names.get(cid,''),
                'candidate_role':role,'candidate_state':state,'applicability_state':applicability,
                'publication_status':pub,'legal_status':entry.get('legal_status',''),'effective_from':entry.get('effective_from',''),
                'matched_ksic_prefixes':'|'.join(ksic),'matched_industry_terms':'|'.join(ind),
                'matched_process_terms':'|'.join(proc),'matched_utility_terms':'|'.join(util),
                'evidence_channels':'|'.join(direct_channels),'evidence_basis':'; '.join(evidence_bits),
                'collection_action':action,'official_source_locator':entry.get('official_source_locator','')
            })

    rows.sort(key=lambda r:(r['site_name'],r['candidate_role'],r['catalog_id']))
    write_csv(pkg/'BAT_Applicability_Candidates.csv',rows,CANDIDATE_FIELDS)

    selected_catalog=sorted({r['catalog_id'] for r in rows if r['collection_action']=='COLLECT'})
    plan={
        'schema_version':'1.1','as_of':as_of.isoformat(),'policy':'MULTI_BAT_SITE_LEVEL_FAIL_CLOSED',
        'candidate_count':len(rows),'site_count':len({r['canonical_site_id'] for r in rows}),
        'collect_catalog_ids':selected_catalog,
        'candidates':rows,
        'boundaries':[
            'A BAT candidate is not proof that the company applies that BAT.',
            'Primary industry, secondary process and common utility references may coexist for one site.',
            'Future/proposed legal applicability is kept distinct from current legal applicability.',
            'Unpublished references are recorded as WAIT_FOR_PUBLICATION and never represented by a fake file.'
        ]
    }
    (pkg/'BAT_Collection_Plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    return plan


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--package',default='assembled'); ap.add_argument('--catalog',default=str(CATALOG_PATH)); ap.add_argument('--as-of',default='')
    a=ap.parse_args(); d=date.fromisoformat(a.as_of) if a.as_of else None
    print(json.dumps(resolve(a.package,a.catalog,d),ensure_ascii=False,indent=2))
