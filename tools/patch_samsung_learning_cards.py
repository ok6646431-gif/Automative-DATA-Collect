from pathlib import Path
import json


def replace_once(path, old, new):
    p=Path(path)
    text=p.read_text(encoding='utf-8')
    if old not in text:
        raise RuntimeError(f'target snippet not found: {path}')
    p.write_text(text.replace(old,new,1),encoding='utf-8')

# 1) Generic address normalization: lot-address text may carry the road address in parentheses.
p=Path('orchestrator/postprocess.py')
text=p.read_text(encoding='utf-8')
old='''def normalize_address(x, profile=None):\n    s=str(x or "").strip()\n    if not s: return ""\n    for old,new in PROVINCE_MAP.items(): s=s.replace(old,new)\n'''
new='''def normalize_address(x, profile=None):\n    s=str(x or "").strip()\n    if not s: return ""\n    # Some public registers expose a legacy lot address first and the usable road\n    # address in parentheses, e.g. "... 반월동 산 16(삼성전자로 1)".  Promote the\n    # parenthesized road core while preserving only the outer administrative prefix.\n    # This is intentionally structural: a genuinely different road address remains\n    # different and is never auto-merged.\n    pm=re.search(r"\\(([^)]*?(?:로|길)\\s*\\d+(?:-\\d+)?)[^)]*\\)",s)\n    if pm:\n        road=re.sub(r"\\s+"," ",pm.group(1)).strip()\n        outer=s[:pm.start()].strip()\n        outer=re.sub(r"\\s+[^\\s]+(?:동|리|가)\\s+(?:산\\s*)?\\d+(?:-\\d+)?\\s*$","",outer).strip()\n        s=(outer+' '+road).strip()\n    for old,new in PROVINCE_MAP.items(): s=s.replace(old,new)\n'''
if old not in text: raise RuntimeError('normalize_address anchor not found')
p.write_text(text.replace(old,new,1),encoding='utf-8')

t=Path('tests/test_postprocess.py')
txt=t.read_text(encoding='utf-8')
anchor='''    def test_eup_myeon_is_not_removed_from_road_address(self):\n'''
test='''    def test_parenthesized_road_address_after_lot_address_is_promoted(self):\n        self.assertEqual(\n            normalize_address("경기도 화성시 반월동 산 16(삼성전자로 1)",PROFILE),\n            normalize_address("경기도 화성시 삼성전자로 1",PROFILE),\n        )\n        # A different parenthesized road remains a different address; the rule must\n        # not silently equate two facilities merely because their site name matches.\n        self.assertNotEqual(\n            normalize_address("경기도 용인시 기흥구 농서동 산 24(삼성전자2로 95)",PROFILE),\n            normalize_address("경기도 용인시 기흥구 삼성로 1",PROFILE),\n        )\n\n'''
if anchor not in txt: raise RuntimeError('postprocess test anchor not found')
t.write_text(txt.replace(anchor,test+anchor,1),encoding='utf-8')

# 2) Samsung-specific BAT applicability declaration.  Applicability means only that
# the semiconductor industry reference is relevant to the verified semiconductor sites;
# it does not prove Samsung applies any particular BAT technique.
app={
  'schema_version':'1.2',
  'request_id':'samsung-electronics-ds-env-20260830-v1',
  'references':[{
    'document_id':'NIER_SEMICONDUCTOR_KBREF_2019',
    'applicability_state':'VERIFIED',
    'candidate_ids':['samsung-ds-giheung','samsung-ds-hwaseong','samsung-ds-pyeongtaek','samsung-ds-cheonan','samsung-ds-onyang'],
    'reference_domains':['AIR','WATER','CHEMICALS','GHG_ENERGY'],
    'basis':'국립환경과학원 통합환경허가시스템이 해당 문서를 반도체 제조업 K-BREF로 공식 공개하고 있고, 대상 5개 사업장은 삼성전자 1차 공식 사업장 자료로 반도체 DS 사업장임이 검증되어 있다. 이 매핑은 업종 기준서의 적용 가능 범위만 뜻하며 삼성전자의 개별 BAT 적용 또는 허가조건을 의미하지 않는다.',
    'source_locator':'https://ieps.nier.go.kr/web/board/5/664/?pMENUMST_ID=95&page=1'
  }],
  'current_reference_note':'반도체 제조업 K-BREF 2판은 2025년 발행 기록이 확인되지만 본 단계에서 원문 기술본문을 확보하지 못했으므로 2판의 개별 기술내용은 자동 근거로 사용하지 않는다.',
  'principle':'Industry-reference existence, verified site applicability, topic-specific technical semantics, and company application are separate claims.'
}
Path('requests/industry_reference_applicability.json').write_text(json.dumps(app,ensure_ascii=False,indent=2),encoding='utf-8')

# 3) Add the official NIER K-BREF index page to the document lane as a reference artifact.
docp=Path('requests/document_evidence.json')
doc=json.loads(docp.read_text(encoding='utf-8'))
if not any(d.get('document_id')=='NIER_SEMICONDUCTOR_KBREF_2019' for d in doc.get('documents',[])):
    doc.setdefault('documents',[]).append({
      'document_id':'NIER_SEMICONDUCTOR_KBREF_2019',
      'document_type':'BAT_REFERENCE',
      'title':'반도체 제조업의 환경오염방지 및 통합관리를 위한 최적가용기법 기준서',
      'report_year':2019,
      'source_url':'https://ieps.nier.go.kr/web/board/5/664/?pMENUMST_ID=95&page=1',
      'source_locator':'https://ieps.nier.go.kr/web/board/5/664/?pMENUMST_ID=95&page=1',
      'expected_extension':'html',
      'verification_status':'VERIFIED',
      'importance':'SUPPORTING',
      'notes':'Official NIER/IEPS K-BREF catalog/index page. Reference existence and semiconductor-industry applicability only; this HTML index is not treated as technical full text.'
    })
docp.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')

# 4) Page/source-grounded secondary technical evidence.  These facts explicitly state
# that they summarize the 2019 K-BREF rather than pretending to be the unavailable full text.
semantic={
  'schema_version':'1.0',
  'request_id':'samsung-electronics-ds-env-20260830-v1',
  'facts':[
    {
      'fact_id':'EXT_KBREF_NF3_PROCESS_2019_SUMMARY', 'document_id':'NIER_SEMICONDUCTOR_KBREF_2019',
      'layer':'INDUSTRY_TECHNICAL','domain':'GHG_ENERGY','time_key':'2019',
      'title':'2019 반도체 K-BREF의 NF3 공정 위치 — 2024 학술논문 요약',
      'statement':'2024년 동료심사 학술논문은 2019 반도체 K-BREF를 인용하여 웨이퍼 가공의 박막 형성(증착) 과정에서 NF3가 사용되고 대기·수질오염물질 형태로 배출될 수 있다고 정리한다.',
      'source_key':'JKSEE_KBREF_REVIEW','source_locator':'https://www.jksee.or.kr/upload/pdf/KSEE-2024-46-5-205.pdf',
      'interpretation_boundary':'2019 K-BREF를 요약한 2차 학술근거다. 2025년 2판의 기술내용 또는 삼성전자의 실제 NF3 사용·배출을 직접 입증하지 않는다.'
    },
    {
      'fact_id':'EXT_KBREF_NF3_BURN_WET_2019_SUMMARY', 'document_id':'NIER_SEMICONDUCTOR_KBREF_2019',
      'layer':'INDUSTRY_TECHNICAL','domain':'GHG_ENERGY','time_key':'2019',
      'title':'2019 반도체 K-BREF의 NF3 처리 — 2024 학술논문 요약',
      'statement':'같은 논문은 K-BREF가 웨이퍼 가공에서 대기오염물질 형태로 배출되는 NF3의 처리기술로 직화식 스크러버(Burn-Wet Scrubber)를 제시한다고 정리한다.',
      'source_key':'JKSEE_KBREF_REVIEW','source_locator':'https://www.jksee.or.kr/upload/pdf/KSEE-2024-46-5-205.pdf',
      'interpretation_boundary':'업종 기술 예시이며 삼성전자 사업장의 설비구성이나 BAT 적용을 뜻하지 않는다.'
    },
    {
      'fact_id':'EXT_KBREF_NF3_SOURCE_REDUCTION_2019_SUMMARY', 'document_id':'NIER_SEMICONDUCTOR_KBREF_2019',
      'layer':'INDUSTRY_TECHNICAL','domain':'GHG_ENERGY','time_key':'2019',
      'title':'2019 반도체 K-BREF의 NF3 원천저감 — 2024 학술논문 요약',
      'statement':'같은 논문은 K-BREF가 웨이퍼 박막형성(증착) 공정 장비 개조를 통해 NF3 가스 사용량을 약 20% 절감할 수 있다고 정리한다.',
      'source_key':'JKSEE_KBREF_REVIEW','source_locator':'https://www.jksee.or.kr/upload/pdf/KSEE-2024-46-5-205.pdf',
      'interpretation_boundary':'2019 기준서에 대한 2차 요약 수치이며 현재 2판의 BAT 수준이나 개별 사업장 기대효과로 사용하지 않는다.'
    }
  ],
  'principle':'Secondary summaries are visibly labeled as secondary. They may explain an industry process/technique but never prove company application or causal effect.'
}
Path('requests/semantic_evidence.json').write_text(json.dumps(semantic,ensure_ascii=False,indent=2),encoding='utf-8')

# 5) Current law evidence used to translate observations into environmental-management work.
legal={
  'schema_version':'1.0','request_id':'samsung-electronics-ds-env-20260830-v1','as_of':'2026-08-31',
  'references':[
    {
      'legal_id':'INTEGRATED_ENV_ART24','domain':'GHG_ENERGY','law':'환경오염시설의 통합관리에 관한 법률','article':'제24조',
      'effective_date':'2026-07-07','title':'최적가용기법 및 K-BREF',
      'statement':'제24조는 오염물질 배출을 효과적으로 줄이고 기술적·경제적으로 적용 가능한 설계·설치·운영·관리기법을 최적가용기법으로 정하며, 업종 현황·주요 배출·BAT·신기술·BAT 연계배출수준 등을 담은 기준서를 마련하도록 한다.',
      'source_locator':'https://law.go.kr/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1022397263',
      'applicability_boundary':'업종 K-BREF와 BAT의 법적 의미를 설명하는 근거다. 특정 삼성전자 사업장의 통합허가 조건 또는 특정 BAT 적용 여부는 별도 허가원문 확인이 필요하다.'
    },
    {
      'legal_id':'ETS_ART24','domain':'GHG_ENERGY','law':'온실가스 배출권의 할당 및 거래에 관한 법률','article':'제24조',
      'effective_date':'2026-04-29','title':'배출량의 보고 및 검증',
      'statement':'할당대상업체는 매 이행연도 종료일부터 3개월 이내에 모든 사업장에서 실제 배출된 온실가스 배출량에 대해 배출량 산정계획서를 기준으로 명세서를 작성하여 보고해야 한다.',
      'source_locator':'https://www.law.go.kr/LSW/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1030666957',
      'applicability_boundary':'할당대상업체에 적용되는 일반 법적 보고체계다. 이 카드만으로 특정 사업장 또는 조직단위의 할당대상 범위를 판정하지 않는다.'
    },
    {
      'legal_id':'ETS_DECREE_ART39','domain':'GHG_ENERGY','law':'온실가스 배출권의 할당 및 거래에 관한 법률 시행령','article':'제39조',
      'effective_date':'2026-04-29','title':'명세서의 측정·보고·검증 정보',
      'statement':'명세서에는 사업장별 배출시설 종류·규모·부하율, 배출량·에너지 사용량, 시설·활동별 산정방법과 근거, 산정방법 변동, 제품 생산량·공정별 배출효율, 온실가스 사용·감축 실적 등이 포함된다.',
      'source_locator':'https://www.law.go.kr/lsLinkCommonInfo.do?lsJoLnkSeq=1033019545',
      'applicability_boundary':'MRV에서 요구되는 정보 구조를 설명한다. 공개 ENV-INFO 값만으로 해당 명세서의 완전성이나 법적 준수 여부를 판단할 수 없다.'
    }
  ]
}
Path('requests/legal_evidence.json').write_text(json.dumps(legal,ensure_ascii=False,indent=2),encoding='utf-8')

# 6) Generic learning-card generator.  Samsung content comes only from package evidence.
Path('orchestrator/learning_cards.py').write_text(r'''import csv, json, re
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
''',encoding='utf-8')

# 7) Package integration.
replace_once('orchestrator/package_run.py',
'''from review_report import build_review_report\nfrom archive_builder import render_html_pdf\n''',
'''from review_report import build_review_report\nfrom learning_cards import run_learning_cards\nfrom archive_builder import render_html_pdf\n''')
replace_once('orchestrator/package_run.py',
'''    "Cross_Layer_Review_Summary.json","Document_Semantic_Candidates.csv","Generated_Semantic_Evidence.json",\n    "Document_Semantics_Summary.json","Environmental_Review_Brief.html","Environmental_Review_Brief.pdf",\n    "Environmental_Review_Evidence.xlsx","Environmental_Review_Summary.json"\n''',
'''    "Cross_Layer_Review_Summary.json","Document_Semantic_Candidates.csv","Generated_Semantic_Evidence.json",\n    "Document_Semantics_Summary.json","Industry_Reference_Applicability.csv","Legal_Evidence.json",\n    "Environmental_Learning_Cards.json","Environmental_Learning_Cards.md",\n    "Environmental_Review_Brief.html","Environmental_Review_Brief.pdf",\n    "Environmental_Review_Evidence.xlsx","Environmental_Review_Summary.json"\n''')
replace_once('orchestrator/package_run.py',
'''    ap=argparse.ArgumentParser(); ap.add_argument("--stable",default="collected/stable"); ap.add_argument("--icis",default="collected/icis"); ap.add_argument("--profile",default="requests/company_profile.json"); ap.add_argument("--events",default="requests/event_evidence.json"); ap.add_argument("--semantic",default="requests/semantic_evidence.json"); ap.add_argument("--out",default="assembled")\n    args=ap.parse_args(); stable=Path(args.stable); icis=Path(args.icis); profile=Path(args.profile); events=Path(args.events); semantic=Path(args.semantic); out=Path(args.out); output=out/"output"\n''',
'''    ap=argparse.ArgumentParser(); ap.add_argument("--stable",default="collected/stable"); ap.add_argument("--icis",default="collected/icis"); ap.add_argument("--profile",default="requests/company_profile.json"); ap.add_argument("--events",default="requests/event_evidence.json"); ap.add_argument("--semantic",default="requests/semantic_evidence.json"); ap.add_argument("--legal",default="requests/legal_evidence.json"); ap.add_argument("--out",default="assembled")\n    args=ap.parse_args(); stable=Path(args.stable); icis=Path(args.icis); profile=Path(args.profile); events=Path(args.events); semantic=Path(args.semantic); legal=Path(args.legal); out=Path(args.out); output=out/"output"\n''')
replace_once('orchestrator/package_run.py',
'''    if profile.exists(): shutil.copy2(profile,out/"Company_Profile.json")\n    if events.exists(): shutil.copy2(events,out/"Event_Evidence.json")\n''',
'''    if profile.exists(): shutil.copy2(profile,out/"Company_Profile.json")\n    if events.exists(): shutil.copy2(events,out/"Event_Evidence.json")\n    if legal.exists(): shutil.copy2(legal,out/"Legal_Evidence.json")\n''')
replace_once('orchestrator/package_run.py',
'''    integration["cross_layer_review"]=run_cross_layer_review(out,semantic if semantic.exists() else None)\n    integration["review_report"]=build_human_review(out)\n''',
'''    integration["cross_layer_review"]=run_cross_layer_review(out,semantic if semantic.exists() else None)\n    integration["learning_cards"]=run_learning_cards(out,out/'Legal_Evidence.json' if (out/'Legal_Evidence.json').exists() else None)\n    integration["review_report"]=build_human_review(out)\n''')

# 8) Human archive: expose learning cards next to the review report and retain in system control-plane copy.
replace_once('orchestrator/archive_builder.py',
'''REVIEW_REPORT_FILES=[\n    ('Environmental_Review_Brief.pdf', True),\n    ('Environmental_Review_Evidence.xlsx', True),\n    ('Environmental_Review_Brief.html', False),\n    ('Environmental_Review_Summary.json', False),\n]\n''',
'''REVIEW_REPORT_FILES=[\n    ('Environmental_Review_Brief.pdf', True),\n    ('Environmental_Review_Evidence.xlsx', True),\n    ('Environmental_Review_Brief.html', False),\n    ('Environmental_Review_Summary.json', False),\n    ('Environmental_Learning_Cards.md', False),\n    ('Environmental_Learning_Cards.json', False),\n]\n''')

# 9) Regression tests for the learning-card evidence gate.
Path('tests/test_learning_cards.py').write_text(r'''import csv, json, tempfile, unittest
from pathlib import Path
from orchestrator.learning_cards import run_learning_cards

def wc(p,rows):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

class TestLearningCards(unittest.TestCase):
    def base(self,root,industry=True):
        wc(root/'Site_Master.csv',[{'canonical_site_id':'SITE_P','canonical_site_name':'평택사업장','identity_status':'CONFIRMED'}])
        wc(root/'Review_Topic_Candidates.csv',[{'topic_id':'T1','canonical_site_id':'SITE_P','site_name':'평택사업장','domain':'GHG_ENERGY','scope_label':'x'}])
        sig=[]
        for metric,values,stype in [
            ('GHG_SCOPE1',{'2022':2963576,'2024':939256.22},'DIRECTIONAL_DOWN|LEVEL_SHIFT_CANDIDATE'),
            ('GHG_SCOPE2',{'2022':3658070,'2024':5453585.551},'DIRECTIONAL_UP'),
            ('GHG_TOTAL',{'2022':6621646,'2024':6392841.771},'LEVEL_SHIFT_CANDIDATE')]:
            sig.append({'signal_id':'S_'+metric,'canonical_site_id':'SITE_P','metric':metric,'signal_type':stype,'years':'2022|2024','values_json':json.dumps(values),'in_requested_scope':'YES','interpretation_boundary':'not causal'})
        wc(root/'Review_Signal_Registry.csv',sig)
        wc(root/'Management_Action_Ledger.csv',[{'action_id':'A1','canonical_site_id':'SITE_P','in_requested_scope':'YES','year':'2022','domain':'GHG_ENERGY','action_name':'RCS 증설','description':'생산공정 중 발생하는 온실가스에 대한 촉매 저감장치 설치','disclosed_effect':'온실가스 배출량 감축','source_file':'ENVINFO/x.html','statement_boundary':'company disclosed'}])
        layers=[]
        if industry:
            layers=[{'evidence_id':'E1','layer':'INDUSTRY_TECHNICAL','domain':'GHG_ENERGY','canonical_site_id':'SITE_P','site_name':'평택사업장','time_key':'2019','title':'NF3 처리','statement':'웨이퍼 가공에서 Burn-Wet Scrubber로 NF3를 처리할 수 있다.','source_key':'JKSEE','source_locator':'https://example.com/paper.pdf','semantic_state':'SEMANTIC_FACT','interpretation_boundary':'secondary summary'}]
        wc(root/'Evidence_Layer_Registry.csv',layers)
        (root/'Legal_Evidence.json').write_text(json.dumps({'references':[{'legal_id':'L1','domain':'GHG_ENERGY','law':'법','article':'제24조','title':'보고','statement':'보고한다','source_locator':'https://law.go.kr/x','applicability_boundary':'generic'}]},ensure_ascii=False),encoding='utf-8')
    def test_ready_card_requires_all_evidence_layers(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.base(root,True)
            s=run_learning_cards(root,root/'Legal_Evidence.json')
            self.assertEqual(s['ready_cards'],1); self.assertEqual(s['selected_site'],'평택사업장')
            card=json.loads((root/'Environmental_Learning_Cards.json').read_text(encoding='utf-8'))['cards'][0]
            self.assertEqual(card['state'],'READY'); self.assertTrue(card['company_actual_action']); self.assertTrue(card['law']); self.assertIn('인과관계가 아니다',card['interpretation_boundary'])
    def test_missing_industry_layer_never_invents_ready_card(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.base(root,False)
            s=run_learning_cards(root,root/'Legal_Evidence.json')
            self.assertEqual(s['ready_cards'],0)
            card=json.loads((root/'Environmental_Learning_Cards.json').read_text(encoding='utf-8'))['cards'][0]
            self.assertEqual(card['state'],'NEEDS_EVIDENCE'); self.assertIn('INDUSTRY_TECHNICAL_EVIDENCE',card['missing_evidence'])

if __name__=='__main__': unittest.main()
''',encoding='utf-8')

print('patched Samsung BAT/semantic/legal evidence, generic learning cards, archive integration, and address normalization')
