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
    'industry_semantic_ready','evidence_layers','why_review','limitations','human_decision'
]
QUESTION_FIELDS=['question_id','review_id','domain','site_name','question_type','question','needed_evidence','status']

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
        # Event_Registry deliberately carries production, identity, disclosure and
        # baseline context.  Those records remain useful to a human reviewer, but
        # they must not fill COMPANY_ACTION/FUTURE_DIRECTION readiness merely
        # because they share a site or date with an environmental signal.
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


def build_cross_candidates(pkg,layers,scope):
    by_layer=defaultdict(list)
    for e in layers: by_layer[e['layer']].append(e)
    rows=[]; questions=[]
    for t in read_csv(pkg/'Review_Topic_Candidates.csv'):
        cid=t.get('canonical_site_id','')
        if not site_allowed(cid,scope): continue
        matches={k:[e for e in by_layer[k] if compatible(t,e)] for k in ['OBSERVED','COMPANY_ACTION','INDUSTRY_TECHNICAL','FUTURE_DIRECTION']}
        obs=matches['OBSERVED']; actions_all=matches['COMPANY_ACTION']; industry=matches['INDUSTRY_TECHNICAL']; future=matches['FUTURE_DIRECTION']
        # A company-wide report statement is useful context, but it must not satisfy
        # the 'site action' layer for a site-specific topic.  Site readiness requires
        # action evidence resolved to the same site; MULTI_SITE may use company scope.
        actions=actions_all if not cid or cid=='MULTI_SITE' else [e for e in actions_all if e.get('canonical_site_id')==cid]
        semantic_industry=[e for e in industry if e.get('semantic_state')=='SEMANTIC_FACT']
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
        if semantic_industry: why+=' + page-grounded industry technical context'
        elif industry: why+=' + industry reference document available (semantic extraction pending)'
        if future: why+=' + company future direction'
        rows.append({
            'review_id':rid,'topic_id':t.get('topic_id'),'canonical_site_id':cid,'site_name':t.get('site_name',''),'domain':t.get('domain',''),'review_state':state,
            'observed_evidence_ids':'|'.join(e['evidence_id'] for e in obs),'company_action_evidence_ids':'|'.join(e['evidence_id'] for e in actions),
            'industry_reference_evidence_ids':'|'.join(e['evidence_id'] for e in industry),'future_direction_evidence_ids':'|'.join(e['evidence_id'] for e in future),
            'industry_semantic_ready':'YES' if semantic_industry else ('REFERENCE_ONLY' if industry else 'NO'),'evidence_layers':'|'.join(present),
            'why_review':why+'.','limitations':'Layer overlap is review context only; production/flow/permit/operating denominators and site-specific technology may still be required.','human_decision':'UNREVIEWED'
        })
        def q(qtype,text,need):
            questions.append({'question_id':stable_id('Q_',rid,qtype),'review_id':rid,'domain':t.get('domain',''),'site_name':t.get('site_name',''),'question_type':qtype,'question':text,'needed_evidence':need,'status':'OPEN'})
        if not actions: q('COMPANY_ACTION_GAP','What same-site management action is publicly confirmed for this observed topic?','Site-resolved official company action, ENVINFO investment, permit or verified event evidence')
        if not industry: q('INDUSTRY_REFERENCE_GAP','What industry technical reference explains why this environmental topic matters?','Applicable BAT/K-BREF or equivalent industry technical reference')
        elif not semantic_industry: q('INDUSTRY_SEMANTIC_GAP','What does the available BAT/K-BREF actually say about this issue, process and control technique?','Page-level BAT/K-BREF evidence: issue, technique, applicability/conditions, evidence locator')
        if not future: q('FUTURE_DIRECTION_GAP','Has the company stated a future target or planned action related to this topic?','Official strategy, target, planned investment or project evidence')
        q('INTERPRETATION_BOUNDARY','What additional denominator or operating information is needed before judging performance or causality?','Production/throughput, flow/load, applicable limit, process change, equipment/operating data as relevant')
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
    layers=observed_layer(pkg,scope)+company_action_layer(pkg,scope)+industry_reference_layer(pkg,semantic_path)
    rows,questions=build_cross_candidates(pkg,layers,scope)
    write_csv(pkg/'Evidence_Layer_Registry.csv',layers,LAYER_FIELDS); write_csv(pkg/'Cross_Layer_Review_Candidates.csv',rows,CROSS_FIELDS); write_csv(pkg/'Study_Question_Queue.csv',questions,QUESTION_FIELDS)
    summary={
        'schema_version':'1.4','protocol_version':protocol.get('schema_version'),'evidence_rows':len(layers),
        'layer_counts':{k:sum(e['layer']==k for e in layers) for k in ['OBSERVED','COMPANY_ACTION','INDUSTRY_TECHNICAL','FUTURE_DIRECTION']},
        'review_candidates':len(rows),'four_layer_ready':sum(r['review_state']=='FOUR_LAYER_READY' for r in rows),
        'multi_layer_review':sum(r['review_state']=='MULTI_LAYER_REVIEW' for r in rows),'open_study_questions':len(questions),
        'scoped_topic_site_ids':len(scoped_topic_ids),'document_semantics':semantic_summary,
        'principle':'Independent evidence layers overlap to create review questions; context-only events and company-wide actions do not satisfy site-action readiness; overlap never establishes causality.',
        'hard_boundaries':protocol.get('hard_boundaries',[])
    }
    (pkg/'Cross_Layer_Review_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8'); return summary


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--package-root',default='assembled'); ap.add_argument('--semantic',default=None); ap.add_argument('--protocol',default=None); a=ap.parse_args(); print(json.dumps(run_cross_layer_review(a.package_root,a.semantic,a.protocol),ensure_ascii=False))

if __name__=='__main__': main()
