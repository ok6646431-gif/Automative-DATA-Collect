import argparse, json
from collections import defaultdict
from pathlib import Path

from review_selection_common import read_csv, read_json, write_csv, stable_id
from document_semantics import run_document_semantics

LAYER_FIELDS=[
    'evidence_id','layer','domain','canonical_site_id','site_name','time_key','title','statement',
    'source_key','source_locator','semantic_state','interpretation_boundary'
]
CROSS_FIELDS=[
    'review_id','topic_id','canonical_site_id','site_name','domain','review_state',
    'observed_evidence_ids','company_action_evidence_ids','industry_reference_evidence_ids','future_direction_evidence_ids',
    'company_action_source_state','company_action_evidence_state',
    'industry_semantic_ready','industry_source_state','industry_evidence_state',
    'future_direction_source_state','future_direction_evidence_state',
    'evidence_layers','why_review','limitations','human_decision'
]
QUESTION_FIELDS=['question_id','review_id','domain','site_name','question_type','question','needed_evidence','status']
SOURCE_AVAILABILITY_FIELDS=[
    'source_key','evidence_family','availability_state','collection_status',
    'declared_count','available_count','failed_count','skipped_count','notes'
]

DOMAIN_WORDS={
    'AIR':['대기','nox','sox','hcl','hf','먼지','배기','scrubber','집진','버너','악취'],
    'WATER_RESOURCES':['용수','재이용','재사용','water stewardship','aws','upw','ro 농축수','수자원'],
    'WATER':['수질','폐수','방류','오수','toc','cod','bod','t-n','t-p','tn','tp','ss'],
    'CHEMICALS':['화학','chemical','물질','약품','누출','prtr','유해','규제물질'],
    'WASTE':['폐기물','재활용','자원순환','waste','zero waste'],
    'GHG_ENERGY':['온실가스','carbon','탄소','scope 1','scope1','scope 2','scope2','pfc','hfc','sf6','nf3','에너지','전력','re100','net zero','넷제로']
}
FUTURE_MARKERS=['전략','목표','계획','mou','협약','추진','예정','target','strategy','roadmap','2030','2040','2050','2029']
INDUSTRY_DOC_TYPES={'BAT_REFERENCE','GUIDELINE'}
NON_READINESS_EVENT_ROLES={'CONTEXT_MARKER','COMPARABILITY_MARKER','IDENTITY_MARKER','BASELINE_MARKER'}
COLLECTOR_SOURCES=['ENVINFO','PRTR','CHEM_STATS','CLEANSYS_AIR','SOOSIRO_WATER','CORP_DOCS']


def infer_domains(text):
    s=str(text or '').lower(); hits=[]
    for domain,words in DOMAIN_WORDS.items():
        if any(w.lower() in s for w in words): hits.append(domain)
    return hits or ['CROSS_MEDIA']


def site_allowed(site_id,scope):
    if str(scope.get('mode') or 'COMPANY').upper()!='SITE_SET': return True
    if not site_id or site_id=='MULTI_SITE': return True
    if site_id in set(scope.get('_review_topic_ids') or []): return True
    return site_id in set(scope.get('target_canonical_site_ids') or [])


def layer_row(layer,domain,site_id,site_name,time_key,title,statement,source_key,source_locator,state,boundary,*idparts):
    return {
        'evidence_id':stable_id('EVD_',layer,domain,site_id,time_key,title,*idparts),'layer':layer,'domain':domain,
        'canonical_site_id':site_id or '','site_name':site_name or '','time_key':time_key or '','title':title or '',
        'statement':statement or '','source_key':source_key or '','source_locator':source_locator or '',
        'semantic_state':state,'interpretation_boundary':boundary
    }


def collector_availability(status):
    state=str((status or {}).get('status') or '').upper()
    if state in {'DATA_FOUND','COMPLETE','SUCCESS','PASS'}: return 'AVAILABLE'
    if 'PARTIAL' in state: return 'PARTIAL'
    if state in {'NOT_RUN','INVALID_SCOPE'}: return 'NOT_COLLECTED'
    if state.startswith('NO_'): return 'NO_DATA'
    return 'UNKNOWN'


def document_family_availability(rows,family,predicate,collection_status=''):
    selected=[r for r in rows if predicate(r)]
    declared=len(selected)
    available=sum(r.get('collection_status')=='DOWNLOADED' for r in selected)
    failed=sum(r.get('collection_status')=='DOWNLOAD_FAILED' for r in selected)
    skipped=sum(str(r.get('collection_status') or '').startswith('SKIPPED') for r in selected)
    if available and failed:
        state='PARTIAL'
    elif available:
        state='AVAILABLE'
    elif failed:
        state='UNAVAILABLE'
    elif declared and skipped:
        state='NOT_COLLECTED'
    elif declared:
        state='NOT_AVAILABLE'
    else:
        state='NOT_DECLARED'
    failed_ids=[str(r.get('document_id') or '') for r in selected if r.get('collection_status')=='DOWNLOAD_FAILED']
    notes=('failed_document_ids='+','.join(x for x in failed_ids if x)) if failed_ids else ''
    return {
        'source_key':'CORP_DOCS','evidence_family':family,'availability_state':state,
        'collection_status':collection_status,'declared_count':declared,'available_count':available,
        'failed_count':failed,'skipped_count':skipped,'notes':notes
    }


def source_availability(pkg):
    rows=[]
    for source in COLLECTOR_SOURCES:
        status=read_json(pkg/'output'/source/'status.json',{}) or {}
        rows.append({
            'source_key':source,'evidence_family':'ALL','availability_state':collector_availability(status),
            'collection_status':str(status.get('status') or ''),'declared_count':str(status.get('documents_declared') or ''),
            'available_count':str(status.get('downloaded') or ''),'failed_count':str(status.get('failed') or ''),
            'skipped_count':str(status.get('skipped') or ''),'notes':''
        })
    docs=read_csv(pkg/'output'/'CORP_DOCS'/'document_index.csv')
    corp_status=read_json(pkg/'output'/'CORP_DOCS'/'status.json',{}) or {}
    cstatus=str(corp_status.get('status') or '')
    rows.append(document_family_availability(docs,'INDUSTRY_REFERENCES',lambda r:r.get('document_type') in INDUSTRY_DOC_TYPES,cstatus))
    rows.append(document_family_availability(docs,'COMPANY_DOCUMENTS',lambda r:r.get('document_type') not in INDUSTRY_DOC_TYPES,cstatus))
    return rows


def observed_layer(pkg,scope):
    out=[]; signals={r.get('metric_id'):r for r in read_csv(pkg/'Review_Signal_Registry.csv')}
    for t in read_csv(pkg/'Review_Topic_Candidates.csv'):
        cid=t.get('canonical_site_id','')
        if not site_allowed(cid,scope): continue
        ids=[x for x in str(t.get('signal_metric_ids') or '').split('|') if x]
        if not ids and t.get('domain')!='CHEMICALS': continue
        if t.get('domain')=='CHEMICALS':
            out.append(layer_row('OBSERVED','CHEMICALS',cid,t.get('site_name'),'','Repeated chemical evidence',t.get('signal_labels',''),'PRTR|CHEM_STATS','Review_Topic_Candidates.csv','SEMANTIC_FACT','Repeated/flagged chemical evidence is a review candidate, not a risk ranking.',t.get('topic_id')))
            continue
        for mid in ids:
            s=signals.get(mid,{})
            out.append(layer_row('OBSERVED',t.get('domain'),cid,t.get('site_name'),s.get('years',''),s.get('metric',mid),s.get('signal_type',''),'Review_Signal_Registry','Review_Signal_Registry.csv','SEMANTIC_FACT','Mathematical signal only; not performance, compliance, risk or causality.',t.get('topic_id'),mid))
    return out


def company_action_layer(pkg,scope):
    out=[]
    for a in read_csv(pkg/'Management_Action_Ledger.csv'):
        cid=a.get('canonical_site_id','')
        if not site_allowed(cid,scope): continue
        for domain in [x for x in str(a.get('domain') or 'CROSS_MEDIA').split('|') if x]:
            out.append(layer_row('COMPANY_ACTION',domain,cid,a.get('site_name'),a.get('year'),a.get('action_name'),a.get('description') or a.get('disclosed_effect'),'ENVINFO',a.get('source_file'),'SEMANTIC_FACT','Company-disclosed action/effect. Timing overlap does not establish measured causal impact.',a.get('action_id')))
    for e in read_csv(pkg/'Event_Registry.csv'):
        cid=e.get('canonical_site_id','')
        if not site_allowed(cid,scope): continue
        role=str(e.get('analysis_role') or '').strip().upper()
        if role in NON_READINESS_EVENT_ROLES: continue
        text=' '.join([e.get('event_title',''),e.get('event_description',''),e.get('event_type','')])
        is_future=any(x in text.lower() for x in FUTURE_MARKERS) and not any(x in text.lower() for x in ['완료','취득'])
        layer='FUTURE_DIRECTION' if is_future or 'STRATEGY' in str(e.get('event_type') or '') or 'MOU' in str(e.get('event_type') or '') else 'COMPANY_ACTION'
        boundary='Company-stated future direction or planned project; not achieved performance.' if layer=='FUTURE_DIRECTION' else 'Verified event/action context; no causal claim to environmental data.'
        for domain in infer_domains(text):
            out.append(layer_row(layer,domain,cid,e.get('site_name',''),e.get('event_date_start'),e.get('event_title'),e.get('event_description'),e.get('source_key'),e.get('source_locator'),'SEMANTIC_FACT',boundary,e.get('event_id')))
    for r in read_csv(pkg/'Document_Semantic_Candidates.csv'):
        layer=r.get('layer','')
        if layer not in {'COMPANY_ACTION','FUTURE_DIRECTION'}: continue
        locator=str(r.get('source_locator') or '')+(('#page='+str(r.get('page'))) if r.get('page') else '')
        out.append(layer_row(layer,r.get('domain') or 'CROSS_MEDIA','','',r.get('report_year'),f"{r.get('document_id')} p.{r.get('page')}",r.get('statement'),r.get('source_key') or 'CORP_DOCS',locator,'PAGE_GROUNDED_EXTRACT',r.get('interpretation_boundary') or 'Company document excerpt; no performance or causal inference.',r.get('semantic_id')))
    return out


def industry_reference_layer(pkg,semantic_path=None):
    out=[]
    for d in read_csv(pkg/'output'/'CORP_DOCS'/'document_index.csv'):
        if d.get('collection_status')!='DOWNLOADED' or d.get('document_type') not in INDUSTRY_DOC_TYPES: continue
        domains=infer_domains(' '.join([d.get('title',''),d.get('document_type',''),d.get('notes','')]))
        if d.get('document_type')=='BAT_REFERENCE' and domains==['CROSS_MEDIA']:
            domains=['AIR','WATER','WATER_RESOURCES','CHEMICALS','WASTE','GHG_ENERGY']
        for domain in domains:
            out.append(layer_row('INDUSTRY_TECHNICAL',domain,'','',d.get('report_year'),d.get('title'),'Industry technical reference document is available; specific technique/issue semantics have not yet been extracted.','CORP_DOCS',d.get('source_locator') or d.get('source_url'),'REFERENCE_AVAILABLE_ONLY','Do not infer that the company applies any BAT or that a particular technique is relevant until semantic evidence is extracted.',d.get('document_id')))
    if semantic_path and Path(semantic_path).exists():
        payload=read_json(semantic_path,{}) or {}; profile=read_json(pkg/'Company_Profile.json',{}) or {}
        if str(payload.get('request_id') or '')==str(profile.get('request_id') or ''):
            for f in payload.get('facts',[]) or []:
                if str(f.get('layer') or '')!='INDUSTRY_TECHNICAL': continue
                out.append(layer_row('INDUSTRY_TECHNICAL',str(f.get('domain') or 'CROSS_MEDIA'),str(f.get('canonical_site_id') or ''),str(f.get('site_name') or ''),str(f.get('time_key') or f.get('year') or ''),str(f.get('title') or ''),str(f.get('statement') or ''),str(f.get('source_key') or ''),str(f.get('source_locator') or ''),'SEMANTIC_FACT',str(f.get('interpretation_boundary') or 'Industry reference only; company application requires company-specific evidence.'),str(f.get('fact_id') or '')))
    return out


def compatible(topic,evidence):
    td=topic.get('domain',''); ed=evidence.get('domain','')
    if not (ed in {td,'CROSS_MEDIA'} or td=='CROSS_MEDIA'): return False
    tcid=topic.get('canonical_site_id',''); ecid=evidence.get('canonical_site_id','')
    return not ecid or ecid==tcid or tcid=='MULTI_SITE'


def missing_evidence_state(has_evidence,source_state,ready_label='EVIDENCE_READY'):
    if has_evidence: return ready_label
    if source_state=='UNAVAILABLE': return 'SOURCE_UNAVAILABLE'
    if source_state=='PARTIAL': return 'SOURCE_PARTIAL'
    if source_state in {'NOT_COLLECTED','NOT_AVAILABLE','NOT_DECLARED','UNKNOWN'}: return 'SOURCE_NOT_CONFIRMED'
    return 'NO_EVIDENCE_FOUND'


def industry_evidence_state(industry,semantic_industry,source_state):
    if semantic_industry: return 'SEMANTIC_READY'
    if industry: return 'REFERENCE_ONLY'
    return missing_evidence_state(False,source_state)


def source_state_map(availability):
    out={}
    for r in availability or []:
        out[(r.get('source_key'),r.get('evidence_family'))]=r.get('availability_state','UNKNOWN')
    return out


def add_gap_question(questions,rid,topic,qtype_prefix,evidence_state,normal_question,normal_need,source_label):
    def q(qtype,text,need):
        questions.append({'question_id':stable_id('Q_',rid,qtype),'review_id':rid,'domain':topic.get('domain',''),'site_name':topic.get('site_name',''),'question_type':qtype,'question':text,'needed_evidence':need,'status':'OPEN'})
    if evidence_state=='SOURCE_UNAVAILABLE':
        q(qtype_prefix+'_SOURCE_UNAVAILABLE',f'{source_label} collection failed. What evidence becomes available after the source is retried?',f'Retry the failed {source_label} source before concluding the evidence layer is absent')
    elif evidence_state=='SOURCE_PARTIAL':
        q(qtype_prefix+'_SOURCE_PARTIAL',f'{source_label} collection is partial. Does the missing portion contain relevant evidence?',f'Retry the missing {source_label} records before concluding the evidence layer is absent')
    elif evidence_state=='SOURCE_NOT_CONFIRMED':
        q(qtype_prefix+'_SOURCE_NOT_CONFIRMED',f'{source_label} availability is not confirmed. Can the source be collected and checked?',f'Confirm {source_label} collection status before concluding the evidence layer is absent')
    else:
        q(qtype_prefix+'_GAP',normal_question,normal_need)


def build_cross_candidates(pkg,layers,scope,availability=None):
    by_layer=defaultdict(list)
    for e in layers: by_layer[e['layer']].append(e)
    smap=source_state_map(availability)
    industry_source_state=smap.get(('CORP_DOCS','INDUSTRY_REFERENCES'),'UNKNOWN')
    company_docs_source_state=smap.get(('CORP_DOCS','COMPANY_DOCUMENTS'),'UNKNOWN')
    envinfo_source_state=smap.get(('ENVINFO','ALL'),'UNKNOWN')
    rows=[]; questions=[]
    for t in read_csv(pkg/'Review_Topic_Candidates.csv'):
        cid=t.get('canonical_site_id','')
        if not site_allowed(cid,scope): continue
        matches={k:[e for e in by_layer[k] if compatible(t,e)] for k in ['OBSERVED','COMPANY_ACTION','INDUSTRY_TECHNICAL','FUTURE_DIRECTION']}
        obs=matches['OBSERVED']; actions_all=matches['COMPANY_ACTION']; industry=matches['INDUSTRY_TECHNICAL']; future=matches['FUTURE_DIRECTION']
        actions=actions_all if not cid or cid=='MULTI_SITE' else [e for e in actions_all if e.get('canonical_site_id')==cid]
        semantic_industry=[e for e in industry if e.get('semantic_state')=='SEMANTIC_FACT']
        action_state=missing_evidence_state(bool(actions),envinfo_source_state)
        ind_state=industry_evidence_state(industry,semantic_industry,industry_source_state)
        future_state=missing_evidence_state(bool(future),company_docs_source_state)
        nonobs=sum(bool(x) for x in [actions,semantic_industry,future])
        if obs and actions and semantic_industry and future: state='FOUR_LAYER_READY'
        elif obs and nonobs>=2: state='MULTI_LAYER_REVIEW'
        elif obs and (actions or industry or future): state='CONTEXT_ONLY'
        elif obs: state='OBSERVED_ONLY'
        else: state='NO_OBSERVED_SIGNAL'
        rid=stable_id('XREV_',t.get('topic_id'),state)
        present=[]
        if obs: present.append('OBSERVED')
        if actions: present.append('COMPANY_ACTION')
        if industry: present.append('INDUSTRY_TECHNICAL')
        if future: present.append('FUTURE_DIRECTION')
        why='Observed public-data signal'
        if actions: why+=' + same-site company action'
        elif action_state=='SOURCE_UNAVAILABLE': why+=' + ENV-INFO unavailable; missing action evidence is unresolved'
        elif action_state=='SOURCE_PARTIAL': why+=' + ENV-INFO partial; missing action evidence is unresolved'
        if semantic_industry: why+=' + page-grounded industry technical context'
        elif industry: why+=' + industry reference document available (semantic extraction pending)'
        elif ind_state=='SOURCE_UNAVAILABLE': why+=' + industry-reference source unavailable; missing evidence is not treated as evidence absence'
        elif ind_state=='SOURCE_PARTIAL': why+=' + industry-reference collection partial; missing evidence remains unresolved'
        if future: why+=' + company future direction'
        elif future_state=='SOURCE_UNAVAILABLE': why+=' + company-document source unavailable; missing future-direction evidence is unresolved'
        elif future_state=='SOURCE_PARTIAL': why+=' + company-document collection partial; missing future-direction evidence is unresolved'
        limitations='Layer overlap is review context only; production/flow/permit/operating denominators and site-specific technology may still be required.'
        incomplete=[]
        if action_state in {'SOURCE_UNAVAILABLE','SOURCE_PARTIAL','SOURCE_NOT_CONFIRMED'}: incomplete.append('company-action source')
        if ind_state in {'SOURCE_UNAVAILABLE','SOURCE_PARTIAL','SOURCE_NOT_CONFIRMED'}: incomplete.append('industry-reference source')
        if future_state in {'SOURCE_UNAVAILABLE','SOURCE_PARTIAL','SOURCE_NOT_CONFIRMED'}: incomplete.append('future-direction source')
        if incomplete:
            limitations+=' Incomplete availability: '+', '.join(incomplete)+'. Missing evidence in these layers must not be interpreted as confirmed absence.'
        rows.append({
            'review_id':rid,'topic_id':t.get('topic_id'),'canonical_site_id':cid,'site_name':t.get('site_name',''),'domain':t.get('domain',''),'review_state':state,
            'observed_evidence_ids':'|'.join(e['evidence_id'] for e in obs),'company_action_evidence_ids':'|'.join(e['evidence_id'] for e in actions),
            'industry_reference_evidence_ids':'|'.join(e['evidence_id'] for e in industry),'future_direction_evidence_ids':'|'.join(e['evidence_id'] for e in future),
            'company_action_source_state':envinfo_source_state,'company_action_evidence_state':action_state,
            'industry_semantic_ready':'YES' if semantic_industry else ('REFERENCE_ONLY' if industry else 'NO'),
            'industry_source_state':industry_source_state,'industry_evidence_state':ind_state,
            'future_direction_source_state':company_docs_source_state,'future_direction_evidence_state':future_state,
            'evidence_layers':'|'.join(present),'why_review':why+'.','limitations':limitations,'human_decision':'UNREVIEWED'
        })
        if not actions:
            add_gap_question(questions,rid,t,'COMPANY_ACTION',action_state,
                'What same-site management action is publicly confirmed for this observed topic?',
                'Site-resolved official company action, ENVINFO investment, permit or verified event evidence','ENV-INFO/company-action')
        if not industry:
            add_gap_question(questions,rid,t,'INDUSTRY',ind_state,
                'What industry technical reference explains why this environmental topic matters?',
                'Applicable BAT/K-BREF or equivalent industry technical reference','industry-reference')
        elif not semantic_industry:
            questions.append({'question_id':stable_id('Q_',rid,'INDUSTRY_SEMANTIC_GAP'),'review_id':rid,'domain':t.get('domain',''),'site_name':t.get('site_name',''),'question_type':'INDUSTRY_SEMANTIC_GAP','question':'What does the available BAT/K-BREF actually say about this issue, process and control technique?','needed_evidence':'Page-level BAT/K-BREF evidence: issue, technique, applicability/conditions, evidence locator','status':'OPEN'})
        if not future:
            add_gap_question(questions,rid,t,'FUTURE_DIRECTION',future_state,
                'Has the company stated a future target or planned action related to this topic?',
                'Official strategy, target, planned investment or project evidence','company-document/future-direction')
        questions.append({'question_id':stable_id('Q_',rid,'INTERPRETATION_BOUNDARY'),'review_id':rid,'domain':t.get('domain',''),'site_name':t.get('site_name',''),'question_type':'INTERPRETATION_BOUNDARY','question':'What additional denominator or operating information is needed before judging performance or causality?','needed_evidence':'Production/throughput, flow/load, applicable limit, process change, equipment/operating data as relevant','status':'OPEN'})
    return rows,questions


def run_cross_layer_review(package_root,semantic_path=None,protocol_path=None):
    pkg=Path(package_root); scope=read_json(pkg/'Requested_Scope.json',{}) or {}; protocol=read_json(protocol_path or Path(__file__).with_name('cross_layer_protocol.json'),{}) or {}
    label=str(scope.get('label') or '')
    scoped_topic_ids=set()
    if label:
        for t in read_csv(pkg/'Review_Topic_Candidates.csv'):
            if str(t.get('scope_label') or '')==label and t.get('canonical_site_id'): scoped_topic_ids.add(t['canonical_site_id'])
    scope['_review_topic_ids']=scoped_topic_ids
    semantic_summary=run_document_semantics(pkg,2000)
    generated=pkg/'Generated_Semantic_Evidence.json'
    if not semantic_path or not Path(semantic_path).exists(): semantic_path=generated if generated.exists() else None
    availability=source_availability(pkg)
    layers=observed_layer(pkg,scope)+company_action_layer(pkg,scope)+industry_reference_layer(pkg,semantic_path)
    rows,questions=build_cross_candidates(pkg,layers,scope,availability)
    write_csv(pkg/'Source_Availability.csv',availability,SOURCE_AVAILABILITY_FIELDS)
    write_csv(pkg/'Evidence_Layer_Registry.csv',layers,LAYER_FIELDS)
    write_csv(pkg/'Cross_Layer_Review_Candidates.csv',rows,CROSS_FIELDS)
    write_csv(pkg/'Study_Question_Queue.csv',questions,QUESTION_FIELDS)
    availability_counts=defaultdict(int)
    for r in availability: availability_counts[r.get('availability_state','UNKNOWN')]+=1
    smap=source_state_map(availability)
    summary={
        'schema_version':'1.6','protocol_version':protocol.get('schema_version'),'evidence_rows':len(layers),
        'layer_counts':{k:sum(e['layer']==k for e in layers) for k in ['OBSERVED','COMPANY_ACTION','INDUSTRY_TECHNICAL','FUTURE_DIRECTION']},
        'review_candidates':len(rows),'four_layer_ready':sum(r['review_state']=='FOUR_LAYER_READY' for r in rows),
        'multi_layer_review':sum(r['review_state']=='MULTI_LAYER_REVIEW' for r in rows),'open_study_questions':len(questions),
        'scoped_topic_site_ids':len(scoped_topic_ids),'document_semantics':semantic_summary,
        'source_availability_counts':dict(sorted(availability_counts.items())),
        'company_action_source_state':smap.get(('ENVINFO','ALL'),'UNKNOWN'),
        'industry_reference_source_state':smap.get(('CORP_DOCS','INDUSTRY_REFERENCES'),'UNKNOWN'),
        'future_direction_source_state':smap.get(('CORP_DOCS','COMPANY_DOCUMENTS'),'UNKNOWN'),
        'principle':'Independent evidence layers overlap to create review questions; source collection failure is distinct from evidence absence in action, technical-reference and future-direction layers; context-only events and company-wide actions do not satisfy site-action readiness; overlap never establishes causality.',
        'hard_boundaries':protocol.get('hard_boundaries',[])
    }
    (pkg/'Cross_Layer_Review_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8'); return summary


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--package-root',default='assembled'); ap.add_argument('--semantic',default=None); ap.add_argument('--protocol',default=None); a=ap.parse_args(); print(json.dumps(run_cross_layer_review(a.package_root,a.semantic,a.protocol),ensure_ascii=False))

if __name__=='__main__': main()
