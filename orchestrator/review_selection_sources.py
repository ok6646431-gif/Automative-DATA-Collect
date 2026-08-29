import math, statistics
from collections import defaultdict
from pathlib import Path
from review_selection_common import read_jsonl, num, year, resolve_site, stable_id, scope_allows

AIR={'tsp_dscamt':'TSP','sox_dscamt':'SOx','nox_dscamt':'NOx','hcl_dscamt':'HCl','hf_dscamt':'HF','nh3_dscamt':'NH3','co_dscamt':'CO','dscamt_sm':'TOTAL_DISCLOSED'}
WATER={'PH_AVRG_DNSTY':'pH','BOD_AVRG_DNSTY':'BOD_CONC','COD_AVRG_DNSTY':'COD_CONC','TOC_AVRG_DNSTY':'TOC_CONC','SS_AVRG_DNSTY':'SS_CONC','TN_AVRG_DNSTY':'TN_CONC','TP_AVRG_DNSTY':'TP_CONC','INTGFL_AVRG_DNSTY':'INTEGRATED_CONC','AMOUNT_FLOW':'FLOW','BOD_DSCAMT':'BOD_LOAD','COD_DSCAMT':'COD_LOAD','TOC_DSCAMT':'TOC_LOAD','SS_DSCAMT':'SS_LOAD','TN_DSCAMT':'TN_LOAD','TP_DSCAMT':'TP_LOAD'}
FLAGS=['인체등유해성물질','제한물질','금지물질','허가물질','사고대비물질','중점관리물질','화평법_금지허가물질','산안법_노출허용기준물질','산안법_작업환경측정물질등','위험물','독성가스']

def parse_cleansys(root,idmap):
    out=[]
    for r in read_jsonl(Path(root)/'CLEANSYS_AIR'/'annual_rows.jsonl'):
        sid=str(r.get('source_fact_code') or r.get('fact_code') or ''); cid,cname=resolve_site(idmap,'CLEANSYS_AIR',sid,r.get('fact_manage_nm') or sid)
        for f,m in AIR.items():
            v=num(r.get(f))
            if v is not None: out.append({'source':'CLEANSYS_AIR','source_site_id':sid,'canonical_site_id':cid,'site_name':cname,'sub_scope':'','year':year(r.get('examin_year')),'domain':'AIR','metric':m,'value':v,'unit':'source_native','source_ref':'CLEANSYS_AIR/annual_rows.jsonl','definition_note':'Confirm source-native unit before cross-source comparison.'})
    return out

def parse_soosiro(root,idmap):
    out=[]
    for r in read_jsonl(Path(root)/'SOOSIRO_WATER'/'annual_rows.jsonl'):
        sid=str(r.get('FACT_CODE') or r.get('source_fact_code') or ''); cid,cname=resolve_site(idmap,'SOOSIRO_WATER',sid,r.get('FACT_FNAME') or r.get('FACT_NAME') or sid); outlet=str(r.get('WAST_NO','') or '')
        for f,m in WATER.items():
            v=num(r.get(f))
            if v is None: continue
            note='Do not stitch to TOC as one continuous metric without an explicit bridge.' if f.startswith('COD_') else ('TOC series is kept separate from earlier COD disclosure.' if f.startswith('TOC_') else '')
            out.append({'source':'SOOSIRO_WATER','source_site_id':sid,'canonical_site_id':cid,'site_name':cname,'sub_scope':f'OUTLET_{outlet}' if outlet else '','year':year(r.get('YEAR',r.get('year'))),'domain':'WATER','metric':m,'value':v,'unit':'source_native','source_ref':'SOOSIRO_WATER/annual_rows.jsonl','definition_note':note})
    return out

def parse_prtr(root,idmap):
    rows=read_jsonl(Path(root)/'PRTR'/'detail_table_rows.jsonl'); names={}; out=[]
    for r in rows:
        if r.get('table_index')==0 and r.get('row_index')==0 and len(r.get('cells',[]))>=2: names[str(r.get('entrps_id',''))]=r['cells'][1]
    for r in rows:
        c=r.get('cells',[])
        if r.get('table_index')!=2 or len(c)!=6 or year(c[0]) is None: continue
        sid=str(r.get('entrps_id','')); cid,cname=resolve_site(idmap,'PRTR',sid,names.get(sid,sid))
        out.append({'source':'PRTR','source_site_id':sid,'canonical_site_id':cid,'site_name':cname,'year':year(c[0]),'cas':c[1],'chemical':c[2],'release_kg':num(c[3]) or 0,'landfill_kg':num(c[4]) or 0,'transfer_kg':num(c[5]) or 0})
    return out

def cas_norm(x):
    p=str(x or '').strip().split('-'); return f'{int(p[0])}-{p[1]}-{p[2]}' if len(p)==3 and all(i.isdigit() for i in p) else str(x or '').strip()

def parse_chem_stats(root,idmap):
    rows=read_jsonl(Path(root)/'CHEM_STATS'/'detail_table_rows.jsonl'); names={}; out=[]
    for r in rows:
        if r.get('table_index')==0 and r.get('row_index')==0 and len(r.get('cells',[]))>=2: names[str(r.get('bplcId',''))]=r['cells'][1]
    for r in rows:
        c=r.get('cells',[])
        if r.get('table_index')!=3 or int(r.get('row_index',-1))<2 or len(c)<13: continue
        sid=str(r.get('bplcId','')); cid,cname=resolve_site(idmap,'CHEM_STATS',sid,names.get(sid,sid)); flags=[FLAGS[i] for i,v in enumerate(c[2:13]) if '▣' in str(v)]
        out.append({'source':'CHEM_STATS','source_site_id':sid,'canonical_site_id':cid,'site_name':cname,'year':year(r.get('search_year')),'chemical':c[0],'cas':cas_norm(c[1]),'flags':flags})
    return out

def chemical_candidates(prtr,stats):
    flags=defaultdict(set)
    for r in stats:
        if r['cas']: flags[r['cas']].update(r['flags'])
    g=defaultdict(lambda:{'sites':set(),'years':set(),'siteyears':set(),'release':0.,'transfer':0.,'landfill':0.,'cas':set()})
    for r in prtr:
        x=g[r['chemical']]; x['sites'].add(r['canonical_site_id']); x['years'].add(r['year']); x['siteyears'].add((r['canonical_site_id'],r['year'])); x['release']+=r['release_kg']; x['transfer']+=r['transfer_kg']; x['landfill']+=r['landfill_kg']; x['cas'].add(cas_norm(r['cas']))
    out=[]
    for name,x in sorted(g.items(),key=lambda kv:(-len(kv[1]['years']),-(kv[1]['release']+kv[1]['transfer']))):
        fs=set(); [fs.update(flags[c]) for c in x['cas'] if c in flags]; dims=[]
        if len(x['years'])>=3: dims.append('persistence')
        if x['release']>0: dims.append('release_path')
        if x['transfer']>0: dims.append('transfer_path')
        if fs: dims.append('regulatory_hazard_flags')
        out.append({'chemical_id':stable_id('CHEM_',name,'|'.join(sorted(x['cas']))),'chemical':name,'cas':'|'.join(sorted(x['cas'])),'site_count':len(x['sites']),'year_count':len(x['years']),'site_year_count':len(x['siteyears']),'years':'|'.join(map(str,sorted(x['years']))),'release_kg':x['release'],'transfer_kg':x['transfer'],'landfill_kg':x['landfill'],'regulatory_hazard_flags':'|'.join(sorted(fs)),'evidence_dimensions':'|'.join(dims),'display_level':'MAIN' if len(dims)>=2 else 'OVERVIEW','interpretation_boundary':'Quantity is not hazard/risk; flags are management relevance, not a risk score.'})
    return out

def daily_stats(root,idmap,scope=None):
    g=defaultdict(list)
    for r in read_jsonl(Path(root)/'SOOSIRO_WATER'/'daily_rows.jsonl'):
        sid=str(r.get('FACT_CODE') or r.get('source_fact_code') or ''); cid,cname=resolve_site(idmap,'SOOSIRO_WATER',sid,r.get('FACT_FNAME') or r.get('FACT_NAME') or sid); outlet=str(r.get('WAST_NO','') or '')
        time_key=r.get('query_year',r.get('YEAR',r.get('year')))
        if scope is not None and not scope_allows(scope,'SOOSIRO_WATER',sid,cid,time_key):
            continue
        for f,m in WATER.items():
            if not (f.endswith('_AVRG_DNSTY') or f=='AMOUNT_FLOW'): continue
            v=num(r.get(f))
            if v is not None: g[(sid,cid,cname,outlet,m)].append(v)
    out=[]
    for (sid,cid,cname,outlet,m),v in sorted(g.items()):
        s=sorted(v); mean=statistics.mean(s); sd=statistics.stdev(s) if len(s)>1 else 0; p95=s[min(len(s)-1,max(0,math.ceil(.95*len(s))-1))]
        out.append({'source':'SOOSIRO_WATER','source_site_id':sid,'canonical_site_id':cid,'site_name':cname,'outlet':outlet,'metric':m,'n':len(s),'mean':mean,'median':statistics.median(s),'p95':p95,'max':max(s),'cv':sd/mean if mean else None,'interpretation_boundary':'Descriptive within-year variability only; not compliance or treatment efficiency.'})
    return out
