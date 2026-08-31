import csv, json, re
from pathlib import Path


def read_csv(path):
    p=Path(path)
    if not p.exists() or p.stat().st_size==0: return []
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))


def read_json(path,default=None):
    p=Path(path)
    try: return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default
    except Exception: return default


def split_pipe(v): return [x for x in str(v or '').split('|') if x]

def parse_values(v):
    try: return json.loads(v or '{}')
    except Exception: return {}

def norm(s): return re.sub(r'\s+',' ',str(s or '')).strip()

PROCESS_GAS_TERMS=['rcs','pfc','f-gas','f gas','불소계 온실가스','온실가스 저감장치','촉매식 pfc','온실가스 처리','온실가스에 대한 촉매']

def process_gas_action(a):
    text=' '.join(str(a.get(k) or '') for k in ['action_name','description','disclosed_effect']).lower()
    return any(t in text for t in PROCESS_GAS_TERMS)

def legal_refs(path,domain):
    payload=read_json(path,{}) or {}
    return [r for r in payload.get('references',[]) or [] if r.get('domain') in {domain,'CROSS_MEDIA'}]

def industry_facts(layers,domain,site_id):
    out=[]
    for r in layers:
        if r.get('layer')!='INDUSTRY_TECHNICAL' or r.get('semantic_state')!='SEMANTIC_FACT': continue
        if r.get('domain') not in {domain,'CROSS_MEDIA'}: continue
        eid=str(r.get('canonical_site_id') or '')
        if eid and eid not in {site_id,'MULTI_SITE'}: continue
        out.append(r)
    return out

def signal_for(signals,site_id,metric):
    hits=[r for r in signals if r.get('canonical_site_id')==site_id and r.get('metric')==metric and r.get('in_requested_scope')=='YES']
    return hits[0] if hits else None

def confirmed_sites(pkg):
    return {r.get('canonical_site_id') for r in read_csv(Path(pkg)/'Site_Master.csv') if r.get('identity_status')=='CONFIRMED'}

def score_topic(t,signals,actions,layers,confirmed):
    if t.get('domain')!='GHG_ENERGY': return -1
    sid=t.get('canonical_site_id','')
    score=1 if sid in confirmed else 0
    s1=signal_for(signals,sid,'GHG_SCOPE1')
    if s1: score+=5
    pa=[a for a in actions if a.get('canonical_site_id')==sid and a.get('in_requested_scope')=='YES' and process_gas_action(a)]
    score+=min(len(pa),3)*3
    facts=industry_facts(layers,'GHG_ENERGY',sid)
    if facts: score+=5
    return score

def endpoint_text(signal):
    if not signal: return ''
    vals=parse_values(signal.get('values_json')); ordered=sorted(vals.items(),key=lambda x:int(x[0])) if vals else []
    if not ordered: return ''
    y0,v0=ordered[0]; y1,v1=ordered[-1]
    return f'{signal.get("metric")}: {y0} {v0:,.3f} → {y1} {v1:,.3f} (signal={signal.get("signal_type")})'

def evidence_ref(kind,source,locator,note=''):
    return {'kind':kind,'source':source,'locator':locator,'note':note}

def build_card(t,signals,actions,layers,legal):
    sid=t.get('canonical_site_id',''); site=t.get('site_name',''); domain=t.get('domain','')
    s1=signal_for(signals,sid,'GHG_SCOPE1'); s2=signal_for(signals,sid,'GHG_SCOPE2'); total=signal_for(signals,sid,'GHG_TOTAL')
    pa=[a for a in actions if a.get('canonical_site_id')==sid and a.get('in_requested_scope')=='YES' and process_gas_action(a)]
    pa=sorted(pa,key=lambda x:str(x.get('year') or ''))
    ind=industry_facts(layers,domain,sid)
    laws=legal
    missing=[]
    if not s1: missing.append('SCOPE1_SIGNAL')
    if not pa: missing.append('COMPANY_PROCESS_GAS_ACTION')
    if not ind: missing.append('INDUSTRY_TECHNICAL_EVIDENCE')
    if not laws: missing.append('LEGAL_EVIDENCE')
    state='READY' if not missing else 'NEEDS_EVIDENCE'
    obs=[]
    for s in [s1,s2,total]:
        if s: obs.append({'metric':s.get('metric'),'signal_type':s.get('signal_type'),'years':split_pipe(s.get('years')),'values':parse_values(s.get('values_json')),'summary':endpoint_text(s),'boundary':s.get('interpretation_boundary')})
    concepts=[{'title':r.get('title'),'statement':r.get('statement'),'boundary':r.get('interpretation_boundary'),'source':r.get('source_key'),'locator':r.get('source_locator')} for r in ind]
    acts=[{'action_id':a.get('action_id'),'year':a.get('year'),'action_name':a.get('action_name'),'description':a.get('description'),'disclosed_effect':a.get('disclosed_effect'),'source_file':a.get('source_file'),'statement_boundary':a.get('statement_boundary')} for a in pa]
    work=[
      {'work':'공정가스 배출원과 저감설비를 시설·공정 단위로 매핑','basis':'Scope 1 신호 + 공정가스 저감설비 조치 + MRV 시설/공정 정보 구조'},
      {'work':'RCS/스크러버의 가동·PM·촉매교체·처리성능 근거를 변경이력과 함께 관리','basis':'회사 공개 저감설비 조치와 BAT의 설계·설치·운영·관리 개념'},
      {'work':'Scope 1/2를 분리해 월·연도 추세를 검토하고 생산량·공정변경·산정방법 변동을 함께 확인','basis':'공개 Scope 지표와 배출권거래제 시행령 제39조의 생산량·산정방법 변동 정보'},
      {'work':'저감활동 전후를 비교할 때 설비 설치시점만으로 인과를 단정하지 않고 활동자료·가동률·처리효율·생산조건을 추가 확인','basis':'공개자료의 해석경계와 MRV 검증가능성 원칙'}
    ]
    questions=[
      'Scope 1의 2022~2024 변화에서 생산량·제품믹스·공정가스 사용량은 어떻게 변했는가?',
      'RCS 증설 및 전처리 배관 증설 전후의 실제 가동률·처리효율·우회/정지시간은 어떠했는가?',
      'Scope 1을 구성하는 PFC/NF3 등 공정가스별 배출기여도와 산정방법은 연도별로 동일했는가?',
      '2022~2023 사이 배출량 산정경계·배출계수·측정방법 변경이 있었는가?',
      '2025년 발행된 반도체 K-BREF 2판에서 NF3/PFC 저감기법과 BAT 연계배출수준은 1기 기준서와 어떻게 달라졌는가?'
    ]
    evidence=[]
    for s in [s1,s2,total]:
        if s: evidence.append(evidence_ref('OBSERVATION','Review_Signal_Registry.csv',s.get('signal_id'),s.get('metric')))
    for a in pa: evidence.append(evidence_ref('COMPANY_ACTION','ENVINFO',a.get('source_file'),f"{a.get('year')} {a.get('action_name')}"))
    for r in ind: evidence.append(evidence_ref('INDUSTRY_TECHNICAL',r.get('source_key'),r.get('source_locator'),r.get('title')))
    for r in laws: evidence.append(evidence_ref('LAW',r.get('law'),r.get('source_locator'),r.get('article')))
    return {
      'card_id':f'LC_{sid}_{domain}','state':state,'missing_evidence':missing,'site_id':sid,'site_name':site,'domain':domain,
      'title':f'{site} 공정가스 저감설비와 Scope 1·2를 함께 읽는 법',
      'observation':obs,
      'concept_and_process':concepts,
      'control_technology':{
        'industry_reference':[x for x in concepts if any(k in (x.get('statement') or '').lower() for k in ['scrubber','스크러버','절감','개조'])],
        'company_actual_actions':acts,
        'boundary':'업종 기술과 회사 공개 조치를 병렬로 제시할 뿐, 회사 조치가 해당 K-BREF BAT를 적용했다거나 관찰된 배출변화를 유발했다고 자동 판정하지 않는다.'
      },
      'environmental_management_work':work,
      'law':[{'law':r.get('law'),'article':r.get('article'),'title':r.get('title'),'statement':r.get('statement'),'source_locator':r.get('source_locator'),'applicability_boundary':r.get('applicability_boundary')} for r in laws],
      'company_actual_action':acts,
      'follow_up_questions':questions,
      'original_evidence':evidence,
      'interpretation_boundary':'공개 연도별 신호와 공개 투자·운영 조치의 시간적 공존은 인과관계가 아니다. 생산량, 공정조건, 가스별 사용량, 산정방법, 설비 가동률 및 처리효율을 추가 확인해야 한다.'
    }
def to_markdown(card):
    lines=[f'# {card["title"]}', '', f'**상태:** {card["state"]}', '']
    lines+=['## 1. 관찰']+[f'- {o["summary"]}' for o in card['observation']]+['', '> 해석 경계: '+card['interpretation_boundary'],'']
    lines+=['## 2. 개념·공정']
    for x in card['concept_and_process']: lines += [f'- **{x["title"]}**: {x["statement"]}',f'  - 경계: {x["boundary"]}']
    lines+=['','## 3. 관리기술 — 업종 기준과 회사 실제를 분리해서 보기']
    for x in card['control_technology']['industry_reference']: lines.append(f'- 업종기술: {x["statement"]}')
    for a in card['company_actual_action']: lines.append(f'- 회사 실제조치 ({a["year"]}): **{a["action_name"]}** — {a["description"]}')
    lines+=['',f'> {card["control_technology"]["boundary"]}','','## 4. 환경관리 업무로 연결']
    for w in card['environmental_management_work']: lines += [f'- **{w["work"]}**',f'  - 근거: {w["basis"]}']
    lines+=['','## 5. 법규·제도']
    for l in card['law']: lines += [f'- **{l["law"]} {l["article"]} — {l["title"]}**',f'  - {l["statement"]}',f'  - 적용 경계: {l["applicability_boundary"]}']
    lines+=['','## 6. 추가 확인 질문']+[f'- {q}' for q in card['follow_up_questions']]
    lines+=['','## 7. 원문 근거']
    for e in card['original_evidence']: lines.append(f'- [{e["kind"]}] {e["source"]} — {e["note"]} — `{e["locator"]}`')
    return '\n'.join(lines)+'\n'
def run_learning_cards(package_root,legal_path=None):
    pkg=Path(package_root); topics=read_csv(pkg/'Review_Topic_Candidates.csv'); signals=read_csv(pkg/'Review_Signal_Registry.csv'); actions=read_csv(pkg/'Management_Action_Ledger.csv'); layers=read_csv(pkg/'Evidence_Layer_Registry.csv'); confirmed=confirmed_sites(pkg)
    laws=legal_refs(legal_path or pkg/'Legal_Evidence.json','GHG_ENERGY')
    ranked=sorted(((score_topic(t,signals,actions,layers,confirmed),t) for t in topics),key=lambda x:(-x[0],str(x[1].get('site_name',''))))
    viable=[x for x in ranked if x[0]>=0]
    cards=[]
    if viable:
        cards.append(build_card(viable[0][1],signals,actions,layers,laws))
    payload={'schema_version':'1.0','selection_rule':'Highest-scoring requested-scope GHG topic with Scope 1 signal, company process-gas action, industry technical evidence, and legal evidence. Missing layers yield NEEDS_EVIDENCE rather than invented content.','cards':cards}
    (pkg/'Environmental_Learning_Cards.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    md='\n\n'.join(to_markdown(c).rstrip() for c in cards)+'\n' if cards else '# 환경관리 학습카드\n\n생성 가능한 근거조합이 없습니다.\n'
    (pkg/'Environmental_Learning_Cards.md').write_text(md,encoding='utf-8')
    return {'card_count':len(cards),'ready_cards':sum(c['state']=='READY' for c in cards),'needs_evidence_cards':sum(c['state']!='READY' for c in cards),'selected_card_id':cards[0]['card_id'] if cards else None,'selected_site':cards[0]['site_name'] if cards else None}

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--package-root',default='assembled'); ap.add_argument('--legal',default=''); a=ap.parse_args(); print(json.dumps(run_learning_cards(a.package_root,a.legal or None),ensure_ascii=False))
