import argparse, json, statistics
from collections import Counter, defaultdict
from pathlib import Path
from review_selection_common import (
    read_json, read_jsonl, read_csv, write_csv, year, stable_id, source_identity_map,
    requested_scope, scope_allows, scope_flag,
)
from review_selection_envinfo import parse_metrics as env_metrics, parse_actions
from review_selection_sources import parse_cleansys, parse_soosiro, parse_prtr, parse_chem_stats, chemical_candidates, daily_stats

NON_ACTIONABLE_SIGNALS={'MIXED_OR_STABLE','SHORT_SERIES','ZERO_SEMANTICS_REVIEW'}


def series_signal(vals,min_obs=4,source=''):
    v=sorted((int(y),float(x)) for y,x in vals if y is not None and x is not None)
    if len(v)<min_obs: return 'SHORT_SERIES'
    # CleanSYS can expose a leading zero when a facility/TMS first appears in the
    # public annual series. Public data alone does not prove whether that zero is
    # a true measured no-emission baseline or a registration/disclosure boundary.
    # Fail closed instead of converting it into an automatic upward trend.
    if source=='CLEANSYS_AIR' and abs(v[0][1])<=1e-12 and any(abs(x)>1e-12 for _,x in v[1:]):
        return 'ZERO_SEMANTICS_REVIEW'
    d=[v[i][1]-v[i-1][1] for i in range(1,len(v))]; nz=[x for x in d if abs(x)>1e-12]; labels=[]
    if nz:
        pos=sum(x>0 for x in nz); neg=sum(x<0 for x in nz)
        if max(pos,neg)/len(nz)>=.75: labels.append('DIRECTIONAL_UP' if pos>neg else 'DIRECTIONAL_DOWN')
        a=[abs(x) for x in nz]; med=statistics.median(a)
        if len(a)>=2 and med>0 and max(a)>=2*med: labels.append('LEVEL_SHIFT_CANDIDATE')
    return '|'.join(labels) if labels else 'MIXED_OR_STABLE'


def metric_selection(metrics,actions,protocol,scope):
    g=defaultdict(list)
    for r in metrics:
        g[(r['source'],str(r.get('source_site_id') or ''),r['canonical_site_id'],r['site_name'],r['sub_scope'],r['domain'],r['metric'],r.get('definition_note',''))].append(r)
    amin=defaultdict(list)
    for a in actions:
        a['in_requested_scope']=scope_flag(scope,a.get('source',''),a.get('source_site_id',''),a.get('canonical_site_id',''))
        if a['in_requested_scope']!='YES': continue
        for d in str(a['domain']).split('|'): amin[(a['canonical_site_id'],d)].append(a['action_id'])
    min_obs=int(protocol.get('comparability',{}).get('trend_min_observations',4)); inv=[]; sig=[]; plan=[]
    for k,rs in sorted(g.items()):
        source,sid,cid,cname,sub,domain,metric,note=k; vals=sorted((r['year'],r['value']) for r in rs if r.get('year') is not None and r.get('value') is not None); ys=sorted(set(y for y,x in vals)); s=series_signal(vals,min_obs,source)
        comp='ZERO_SEMANTICS_REVIEW' if s=='ZERO_SEMANTICS_REVIEW' else ('TREND_ELIGIBLE' if len(ys)>=min_obs else ('CONTEXT_ONLY' if len(ys)>=2 else 'EVIDENCE_ONLY'))
        allowed=scope_allows(scope,source,sid,cid); acts=sorted(set(amin[(cid,domain)])) if allowed else []; level='OVERVIEW' if ys else 'EVIDENCE'; reason=['available_metric'] if ys else []
        if comp=='TREND_ELIGIBLE' and s not in NON_ACTIONABLE_SIGNALS: level='MAIN'; reason.append('comparable_signal')
        if comp=='TREND_ELIGIBLE' and acts: level='MAIN'; reason.append('same_site_domain_action')
        note_out=note
        if s=='ZERO_SEMANTICS_REVIEW':
            extra='Leading CleanSYS zero is retained as source-native data but excluded from automatic trend interpretation until zero semantics are verified.'
            note_out=(str(note_out).strip()+' '+extra).strip()
            reason.append('leading_zero_requires_semantic_review')
        mid=stable_id('MET_',source,sid,cid,sub,domain,metric); in_scope='YES' if allowed else 'NO'
        inv.append({'metric_id':mid,'source':source,'source_site_id':sid,'canonical_site_id':cid,'site_name':cname,'sub_scope':sub,'domain':domain,'metric':metric,'years':'|'.join(map(str,ys)),'observation_count':len(ys),'comparability':comp,'definition_note':note_out,'source_ref':rs[0].get('source_ref',''),'scope_label':scope.get('label',''),'in_requested_scope':in_scope})
        sig.append({'signal_id':stable_id('SIG_',mid,s),'metric_id':mid,'source':source,'source_site_id':sid,'canonical_site_id':cid,'site_name':cname,'domain':domain,'metric':metric,'signal_type':s,'years':'|'.join(map(str,ys)),'values_json':json.dumps({str(y):x for y,x in vals},ensure_ascii=False),'scope_label':scope.get('label',''),'in_requested_scope':in_scope,'interpretation_boundary':'Mathematical review signal only; not performance, compliance, risk or causality.'})
        if allowed:
            plan.append({'object_id':mid,'object_type':'METRIC','domain':domain,'site_name':cname,'label':metric,'display_level':level,'selection_reason':'|'.join(reason),'evidence_dimensions':'numeric_signal' if level=='MAIN' and s not in NON_ACTIONABLE_SIGNALS else '','related_action_ids':'|'.join(acts),'scope_label':scope.get('label',''),'human_decision':'UNREVIEWED'})
    return inv,sig,plan


def topic_candidates(inv,sig,actions,chems,scope,site_names=None):
    """Aggregate study topics on the canonical site/domain axis.

    Source-native site labels are presentation metadata, not identity keys. Once
    Source_Identity has resolved multiple public-source labels to one canonical site,
    splitting topics again by those raw labels creates duplicate rows carrying the
    same stable topic_id. Use canonical_site_id + domain as the only site-topic key and
    prefer Site_Master.canonical_site_name for display.
    """
    site_names=site_names or {}
    sm={r['metric_id']:r for r in sig}; ag=defaultdict(list)
    for a in actions:
        if a.get('in_requested_scope')!='YES': continue
        for d in str(a['domain']).split('|'): ag[(a['canonical_site_id'],d)].append(a)
    g=defaultdict(list)
    for m in inv:
        if m.get('in_requested_scope')!='YES': continue
        s=sm[m['metric_id']]
        if m['comparability']=='TREND_ELIGIBLE' and s['signal_type'] not in NON_ACTIONABLE_SIGNALS:
            g[(m['canonical_site_id'],m['domain'])].append((m,s))
    out=[]
    for (cid,domain),ms in sorted(g.items()):
        acts=ag[(cid,domain)]; sources={m[0]['source'] for m in ms}|{a['source'] for a in acts}; state='DEEP_DIVE_CANDIDATE' if acts and len(sources)>=2 else 'MAIN_CONTEXT'
        observed_names=[str(m[0].get('site_name') or '').strip() for m in ms if str(m[0].get('site_name') or '').strip()]
        cname=site_names.get(cid) or (Counter(observed_names).most_common(1)[0][0] if observed_names else cid)
        metric_ids=list(dict.fromkeys(m[0]['metric_id'] for m in ms))
        labels=list(dict.fromkeys(f"{m[0]['metric']}:{m[1]['signal_type']}" for m in ms))
        action_ids=list(dict.fromkeys(a['action_id'] for a in acts))
        out.append({'topic_id':stable_id('TOPIC_',scope.get('label',''),cid,domain),'canonical_site_id':cid,'site_name':cname,'domain':domain,'candidate_state':state,'signal_metric_ids':'|'.join(metric_ids),'signal_labels':'|'.join(labels),'action_ids':'|'.join(action_ids),'evidence_sources':'|'.join(sorted(sources)),'evidence_dimensions':'numeric_signal'+('|management_action' if acts else '')+('|independent_source_overlap' if len(sources)>=2 else ''),'why_review':'Comparable multi-year signal'+(' plus same-site/domain management action.' if acts else '.'),'limitations':'No causal inference; domain-specific denominators/limits/operating data may still be required.','scope_label':scope.get('label',''),'human_decision':'UNREVIEWED'})
    deep=[c for c in chems if c['display_level']=='MAIN' and 'persistence' in c['evidence_dimensions'] and c['regulatory_hazard_flags']]
    if deep:
        out.append({'topic_id':stable_id('TOPIC_',scope.get('label',''),'MULTI_SITE','CHEMICALS'),'canonical_site_id':'MULTI_SITE','site_name':'MULTI_SITE','domain':'CHEMICALS','candidate_state':'DEEP_DIVE_CANDIDATE','signal_metric_ids':'','signal_labels':'|'.join(c['chemical'] for c in deep),'action_ids':'','evidence_sources':'PRTR|CHEM_STATS','evidence_dimensions':'persistence|release_transfer_path|regulatory_hazard_flags|independent_source_overlap','why_review':'Repeated PRTR chemicals overlap with chemical-statistics management flags inside the requested review scope.','limitations':'Process use, treatment difficulty, BAT relevance and company action still need evidence.','scope_label':scope.get('label',''),'human_decision':'UNREVIEWED'})
    return out


def coverage(root,metrics,prtr,stats,scope):
    raw={}
    for s,f,k,kind in [('ENVINFO','discovery.csv','year','csv'),('PRTR','discovery.csv','search_year','csv'),('CHEM_STATS','discovery.csv','search_year','csv'),('CLEANSYS_AIR','annual_rows.jsonl','examin_year','jsonl'),('SOOSIRO_WATER','annual_rows.jsonl','YEAR','jsonl')]:
        rows=read_csv(Path(root)/s/f) if kind=='csv' else read_jsonl(Path(root)/s/f); raw[s]=sorted(set(y for y in (year(r.get(k)) for r in rows) if y))
    scoped=defaultdict(set)
    for r in metrics:
        if scope_allows(scope,r.get('source',''),r.get('source_site_id',''),r.get('canonical_site_id','')) and r.get('year') is not None: scoped[r['source']].add(r['year'])
    for r in prtr:
        if scope_allows(scope,'PRTR',r.get('source_site_id',''),r.get('canonical_site_id','')) and r.get('year') is not None: scoped['PRTR'].add(r['year'])
    for r in stats:
        if scope_allows(scope,'CHEM_STATS',r.get('source_site_id',''),r.get('canonical_site_id','')) and r.get('year') is not None: scoped['CHEM_STATS'].add(r['year'])
    out=[]
    for s in ['ENVINFO','PRTR','CHEM_STATS','CLEANSYS_AIR','SOOSIRO_WATER']:
        sy=sorted(scoped[s]); ry=raw.get(s,[]); out.append({'source':s,'raw_years':'|'.join(map(str,ry)),'raw_year_count':len(ry),'requested_scope_years':'|'.join(map(str,sy)),'requested_scope_year_count':len(sy),'scope_mode':scope.get('mode','COMPANY'),'scope_label':scope.get('label','')})
    return out


def run_review_selection(source_root,package_root,protocol_path=None):
    root=Path(source_root); pkg=Path(package_root); pkg.mkdir(parents=True,exist_ok=True); protocol=read_json(protocol_path or Path(__file__).with_name('review_selection_protocol.json'),{}) or {}; scope=requested_scope(pkg); idmap=source_identity_map(pkg)
    metrics=env_metrics(root,idmap)+parse_cleansys(root,idmap)+parse_soosiro(root,idmap); actions=parse_actions(root,idmap); inv,sig,plan=metric_selection(metrics,actions,protocol,scope)
    prtr=parse_prtr(root,idmap); stats=parse_chem_stats(root,idmap); prtr_scope=[r for r in prtr if scope_allows(scope,'PRTR',r.get('source_site_id',''),r.get('canonical_site_id',''))]; stats_scope=[r for r in stats if scope_allows(scope,'CHEM_STATS',r.get('source_site_id',''),r.get('canonical_site_id',''))]; chems=chemical_candidates(prtr_scope,stats_scope)
    plan += [{'object_id':c['chemical_id'],'object_type':'CHEMICAL','domain':'CHEMICALS','site_name':'MULTI_SITE' if c['site_count']>1 else 'SINGLE_SITE','label':c['chemical'],'display_level':c['display_level'],'selection_reason':'requested_scope_evidence_stack','evidence_dimensions':c['evidence_dimensions'],'related_action_ids':'','scope_label':scope.get('label',''),'human_decision':'UNREVIEWED'} for c in chems]
    site_names={r.get('canonical_site_id',''):r.get('canonical_site_name','') for r in read_csv(pkg/'Site_Master.csv') if r.get('canonical_site_id')}
    topics=topic_candidates(inv,sig,actions,chems,scope,site_names); daily=daily_stats(root,idmap)
    for r in daily: r['scope_label']=scope.get('label',''); r['in_requested_scope']=scope_flag(scope,r.get('source',''),r.get('source_site_id',''),r.get('canonical_site_id',''))
    cov=coverage(root,metrics,prtr,stats,scope)
    write_csv(pkg/'Review_Metric_Inventory.csv',inv,['metric_id','source','source_site_id','canonical_site_id','site_name','sub_scope','domain','metric','years','observation_count','comparability','definition_note','source_ref','scope_label','in_requested_scope'])
    write_csv(pkg/'Review_Signal_Registry.csv',sig,['signal_id','metric_id','source','source_site_id','canonical_site_id','site_name','domain','metric','signal_type','years','values_json','scope_label','in_requested_scope','interpretation_boundary'])
    write_csv(pkg/'Management_Action_Ledger.csv',actions,['action_id','source','source_site_id','canonical_site_id','site_name','year','domain','action_name','period','investment_million_krw','description','disclosed_effect','source_file','source_caption','scope_label','in_requested_scope','statement_boundary'])
    write_csv(pkg/'Chemical_Review_Candidates.csv',chems,['chemical_id','chemical','cas','site_count','year_count','site_year_count','years','release_kg','transfer_kg','landfill_kg','regulatory_hazard_flags','evidence_dimensions','display_level','interpretation_boundary'])
    write_csv(pkg/'Water_Daily_Stats.csv',daily,['source','source_site_id','canonical_site_id','site_name','outlet','metric','n','mean','median','p95','max','cv','scope_label','in_requested_scope','interpretation_boundary'])
    write_csv(pkg/'Review_Display_Plan.csv',plan,['object_id','object_type','domain','site_name','label','display_level','selection_reason','evidence_dimensions','related_action_ids','scope_label','human_decision'])
    write_csv(pkg/'Review_Topic_Candidates.csv',topics,['topic_id','canonical_site_id','site_name','domain','candidate_state','signal_metric_ids','signal_labels','action_ids','evidence_sources','evidence_dimensions','why_review','limitations','scope_label','human_decision'])
    write_csv(pkg/'Review_Source_Coverage.csv',cov,['source','raw_years','raw_year_count','requested_scope_years','requested_scope_year_count','scope_mode','scope_label'])
    summary={'schema_version':'1.3','protocol_version':protocol.get('schema_version'),'scope_mode':scope.get('mode'),'scope_label':scope.get('label'),'metric_rows':len(metrics),'metric_inventory':len(inv),'metric_inventory_in_scope':sum(r['in_requested_scope']=='YES' for r in inv),'signals':len(sig),'signals_in_scope':sum(r['in_requested_scope']=='YES' for r in sig),'zero_semantics_review':sum(r['signal_type']=='ZERO_SEMANTICS_REVIEW' for r in sig),'management_actions':len(actions),'management_actions_in_scope':sum(r.get('in_requested_scope')=='YES' for r in actions),'prtr_chemical_rows':len(prtr),'prtr_chemical_rows_in_scope':len(prtr_scope),'chem_stats_substance_rows':len(stats),'chem_stats_substance_rows_in_scope':len(stats_scope),'chemical_candidates':len(chems),'topic_candidates':len(topics),'deep_dive_candidates':sum(t['candidate_state']=='DEEP_DIVE_CANDIDATE' for t in topics),'daily_stat_rows':len(daily),'daily_stat_rows_in_scope':sum(r['in_requested_scope']=='YES' for r in daily),'boundaries':protocol.get('hard_boundaries',[])}
    (pkg/'Review_Selection_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8'); return summary


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--source-root',default='assembled/output'); ap.add_argument('--package-root',default='assembled'); ap.add_argument('--protocol',default=None); a=ap.parse_args(); print(json.dumps(run_review_selection(a.source_root,a.package_root,a.protocol),ensure_ascii=False))
if __name__=='__main__': main()
