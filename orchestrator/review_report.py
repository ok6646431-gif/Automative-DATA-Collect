import csv, html, json, math, shutil, subprocess, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_builder import valid_pdf

DOMAIN_ORDER=['AIR','WATER','WATER_RESOURCES','CHEMICALS','WASTE','GHG_ENERGY']
DOMAIN_KO={'AIR':'대기','WATER':'수질','WATER_RESOURCES':'용수·수자원','CHEMICALS':'화학물질','WASTE':'폐기물·자원순환','GHG_ENERGY':'온실가스·에너지','CROSS_MEDIA':'통합관리'}
DOMAIN_FRAME={
'AIR':'배출원·공정 → 방지시설 → 배출구/모니터링 → 허가·운전조건 → 개선활동',
'WATER':'폐수 수종·유입부하 → 처리계통 → 방류/재이용 → 수질 모니터링 → 개선활동',
'WATER_RESOURCES':'취수·사용 → 공정/유틸리티 수요 → 회수·재이용 → 용수 인프라 → 수급전략',
'CHEMICALS':'도입·사전검토 → 저장·공급 → 공정 사용 → 배출·이동/폐기 → 규제·비상대응',
'WASTE':'공정 발생 → 분류·보관 → 위탁/재활용 → 자원순환 → 감량·처리경로 관리',
'GHG_ENERGY':'공정가스·연료·전력 → 저감/회수 → Scope 1·2 산정 → 에너지효율 → 감축전략'
}
DOMAIN_CAVEAT={
'AIR':'농도/연간 공개값만으로 총 환경부하·법적 준수·방지시설 효율을 판정하지 않는다.',
'WATER':'방류값만으로 처리효율을 판정하지 않는다. 유입농도·유량·부하·적용기준이 필요하다.',
'WATER_RESOURCES':'사용량 증가를 곧바로 비효율로 해석하지 않는다. 생산규모·제품믹스·재이용 용도를 함께 봐야 한다.',
'CHEMICALS':'배출·이동량은 위험도 점수가 아니다. 유해성·규제성·공정경로·관리방법을 분리해서 본다.',
'WASTE':'발생량·재활용률만으로 관리수준을 단정하지 않는다. 폐기물 종류와 처리경로가 필요하다.',
'GHG_ENERGY':'절대배출량 변화만으로 성과를 판정하지 않는다. 생산량·전력구성·산정범위 변경을 함께 본다.'
}
TERM_EXPAND={
'HCl':['hcl','염화 수소','염화수소','산성가스'], 'NOx':['nox','질소산화물','탈질'],
'SS':['ss','부유물질','suspended solid'], 'TN':['t-n','tn','총질소','질소'], 'TOC':['toc','총유기탄소','유기물'], 'TP':['t-p','tp','총인','인'],
'황산':['황산','sulfuric'], '2-프로판올':['2-프로판올','ipa','isopropyl'], '과산화 수소':['과산화 수소','과산화수소','hydrogen peroxide'],
'플루오르화 수소':['플루오르화 수소','불산','hf','hydrogen fluoride'], '암모니아':['암모니아','ammonia'],
'CHEMICALS':['화학물질','chemical','유해물질','규제물질'], 'AIR':['대기','배기','scrubber','배출'],
'WATER':['수질','폐수','방류','wastewater'], 'WATER_RESOURCES':['용수','재이용','수자원','water reuse'],
'WASTE':['폐기물','재활용','waste'], 'GHG_ENERGY':['온실가스','scope','pfc','hfc','sf6','nf3','에너지','전력']
}

def read_csv(p):
    p=Path(p)
    if not p.exists() or p.stat().st_size==0: return []
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def read_json(p,default=None):
    p=Path(p)
    try: return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default
    except Exception: return default

def esc(v): return html.escape(str(v or ''))
def money(v):
    try:
        x=float(v); return f'{x:,.0f}' if abs(x)>=1 else f'{x:,.2f}'
    except Exception: return '-'
def nice(v):
    try:
        x=float(v)
        if abs(x)>=1_000_000: return f'{x/1_000_000:.2f}M'
        if abs(x)>=1_000: return f'{x/1_000:.1f}k'
        if abs(x)>=100: return f'{x:.0f}'
        if abs(x)>=10: return f'{x:.1f}'
        return f'{x:.2f}'
    except Exception: return str(v)

def split_ids(v): return [x for x in str(v or '').split('|') if x and x!='nan']

def signal_terms(topic):
    terms=[]
    for part in str(topic.get('signal_labels') or '').split('|'):
        head=part.split(':',1)[0].strip()
        if head: terms.append(head)
    if topic.get('domain')=='CHEMICALS':
        terms += [x.strip() for x in str(topic.get('signal_labels') or '').split('|')[:8] if x.strip()]
    return terms

def expand_terms(terms,domain):
    out=[]
    for t in list(terms)+[domain]:
        out.append(t.lower())
        for x in TERM_EXPAND.get(t,[]): out.append(x.lower())
    return list(dict.fromkeys(x for x in out if x))

def rank_evidence(rows, terms, layer, limit=4):
    ex=expand_terms(terms, rows[0].get('domain') if rows else '') if rows else []
    scored=[]; seen=set()
    for r in rows:
        if r.get('layer')!=layer: continue
        text=' '.join([r.get('title',''),r.get('statement',''),r.get('source_locator','')]).lower()
        score=sum(3 if t in text else 0 for t in ex)
        if r.get('semantic_state') in {'SEMANTIC_FACT','PAGE_GROUNDED_EXTRACT'}: score+=2
        key=(r.get('statement','')[:180],r.get('source_locator',''))
        if key in seen: continue
        seen.add(key); scored.append((score,r))
    scored.sort(key=lambda x:(-x[0],str(x[1].get('time_key','')),str(x[1].get('title',''))))
    positive=[r for s,r in scored if s>2]
    return (positive or [r for _,r in scored])[:limit]

def sparkline(values):
    pts=[]; data=[]
    for y,v in sorted(values.items(), key=lambda z:int(z[0])):
        try:data.append((str(y),float(v)))
        except:pass
    if not data:return ''
    lo=min(v for _,v in data); hi=max(v for _,v in data); span=hi-lo or 1; W,H=280,62
    for i,(y,v) in enumerate(data):
        x=8+(W-16)*(i/(max(len(data)-1,1))); yy=8+(H-20)*(1-(v-lo)/span); pts.append((x,yy,y,v))
    poly=' '.join(f'{x:.1f},{y:.1f}' for x,y,_,_ in pts)
    dots=''.join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6"/><text x="{x:.1f}" y="{H-2}" text-anchor="middle">{esc(yr)}</text>' for x,y,yr,_ in pts)
    return f'<svg class="spark" viewBox="0 0 {W} {H}" role="img"><polyline points="{poly}"/>{dots}</svg>'

def evidence_card(title, rows):
    if not rows: return f'<div class="evi"><b>{esc(title)}</b><p class="muted">근거 없음 또는 추가 확인 필요</p></div>'
    lis=[]
    for r in rows:
        locator=r.get('source_locator',''); page=''
        if '#page=' in locator: page=' · p.'+locator.split('#page=')[-1]
        elif r.get('page'): page=' · p.'+str(r.get('page'))
        lis.append(f'<li>{esc(r.get("statement") or r.get("title"))}<span class="src">{esc(r.get("source_key"))}{esc(page)}</span></li>')
    return f'<div class="evi"><b>{esc(title)}</b><ul>{"".join(lis)}</ul></div>'

def build_review_report(package_root, render_pdf=True):
    root=Path(package_root)
    profile=read_json(root/'Company_Profile.json',{}) or {}; scope=read_json(root/'Requested_Scope.json',{}) or {}
    cov=read_csv(root/'Review_Source_Coverage.csv'); inv=read_csv(root/'Review_Metric_Inventory.csv'); sig=read_csv(root/'Review_Signal_Registry.csv')
    actions=read_csv(root/'Management_Action_Ledger.csv'); chems=read_csv(root/'Chemical_Review_Candidates.csv'); topics=read_csv(root/'Review_Topic_Candidates.csv')
    layers=read_csv(root/'Evidence_Layer_Registry.csv'); cross=read_csv(root/'Cross_Layer_Review_Candidates.csv'); questions=read_csv(root/'Study_Question_Queue.csv')
    review_summary=read_json(root/'Review_Selection_Summary.json',{}) or {}; cross_summary=read_json(root/'Cross_Layer_Review_Summary.json',{}) or {}
    target_ids=set(scope.get('target_canonical_site_ids') or []); sites=[]
    site_master={r.get('canonical_site_id'):r for r in read_csv(root/'Site_Master.csv')}
    for s in profile.get('site_candidates',[]) or []:
        name=s.get('site_name_raw'); addr=s.get('address_raw'); cid=''
        for tid in target_ids:
            m=site_master.get(tid,{})
            if name and name in str(m.get('canonical_site_name','')): cid=tid; break
        sites.append((name,addr,cid))
    sm={r.get('metric_id'):r for r in sig}; am={r.get('action_id'):r for r in actions}; evm={r.get('evidence_id'):r for r in layers}; xmap={r.get('topic_id'):r for r in cross}
    deep=[t for t in topics if t.get('candidate_state')=='DEEP_DIVE_CANDIDATE']
    cvrows=''.join(f'<tr><td>{esc(r.get("source"))}</td><td>{esc(r.get("requested_scope_years"))}</td><td>{esc(r.get("requested_scope_year_count"))}</td></tr>' for r in cov)
    site_rows=''.join(f'<tr><td>{esc(n)}</td><td>{esc(a)}</td><td>{esc(cid or "scope-mapped")}</td></tr>' for n,a,cid in sites)
    domain_html=[]
    for d in DOMAIN_ORDER:
        dinv=[r for r in inv if r.get('in_requested_scope')=='YES' and r.get('domain')==d]
        dmain=[r for r in dinv if sm.get(r.get('metric_id'),{}).get('signal_type') not in {'SHORT_SERIES','MIXED_OR_STABLE',''} and r.get('comparability')=='TREND_ELIGIBLE']
        dacts=[r for r in actions if r.get('in_requested_scope')=='YES' and d in str(r.get('domain','')).split('|')]
        years=sorted(set(r.get('year') for r in dacts if r.get('year'))); labels=[]
        for r in dmain[:8]: labels.append(f'{r.get("site_name")} · {r.get("metric")} ({sm.get(r.get("metric_id"),{}).get("signal_type")})')
        de=[r for r in layers if r.get('domain')==d and r.get('layer') in {'COMPANY_ACTION','FUTURE_DIRECTION'}]
        fut=rank_evidence(de,[d],'FUTURE_DIRECTION',2)
        domain_html.append(f'''<section class="domain"><h3>{DOMAIN_KO[d]}</h3>
        <div class="frame"><b>관리구조를 읽는 순서</b> {esc(DOMAIN_FRAME[d])}</div>
        <div class="stats"><span>가용 지표 <b>{len(dinv)}</b></span><span>장기 Signal <b>{len(dmain)}</b></span><span>관리 Action <b>{len(dacts)}</b></span><span>Action 연도 <b>{esc(', '.join(years) or '-')}</b></span></div>
        <p><b>현재 데이터가 말하는 것:</b> {esc('; '.join(labels[:5]) if labels else '장기 변화 후보가 없거나 현재 공개자료만으로 상세선정 근거가 부족함')}</p>
        <p class="caveat"><b>해석 경계:</b> {esc(DOMAIN_CAVEAT[d])}</p>{evidence_card('회사 미래방향/공개계획 참고',fut)}</section>''')
    scoped_actions=[r for r in actions if r.get('in_requested_scope')=='YES']; by_year=defaultdict(list)
    for a in scoped_actions: by_year[str(a.get('year') or '미상')].append(a)
    year_blocks=[]
    for y in sorted(by_year):
        rows=by_year[y]; cnt=Counter(); total=0
        for a in rows:
            for d in str(a.get('domain','')).split('|'): cnt[d]+=1
            try: total+=float(a.get('investment_million_krw') or 0)
            except: pass
        def inv_key(r):
            try:return float(r.get('investment_million_krw') or 0)
            except:return 0
        top=sorted(rows,key=inv_key,reverse=True)[:4]
        li=''.join(f'<li><b>{esc(a.get("site_name"))}</b> · {esc(a.get("action_name"))} <span class="src">{money(a.get("investment_million_krw"))} 백만원</span></li>' for a in top)
        year_blocks.append(f'<div class="year"><h4>{esc(y)} <span>{len(rows)}건 · 공개 투자액 합계 {money(total)} 백만원*</span></h4><p>{esc(" / ".join(f"{DOMAIN_KO.get(k,k)} {v}" for k,v in cnt.most_common()))}</p><ul>{li}</ul></div>')
    deep_html=[]
    for idx,t in enumerate(deep,1):
        terms=signal_terms(t); x=xmap.get(t.get('topic_id'),{}); signal_rows=[sm[mid] for mid in split_ids(t.get('signal_metric_ids')) if mid in sm]; sig_cards=[]
        for s in signal_rows[:5]:
            try: vals=json.loads(s.get('values_json') or '{}')
            except: vals={}
            values=' · '.join(f'{y}:{nice(v)}' for y,v in sorted(vals.items(),key=lambda z:int(z[0])))
            sig_cards.append(f'<div class="signal"><b>{esc(s.get("metric"))}</b><span class="tag">{esc(s.get("signal_type"))}</span>{sparkline(vals)}<div class="vals">{esc(values)}</div></div>')
        if t.get('domain')=='CHEMICALS':
            cmain=[c for c in chems if c.get('display_level')=='MAIN'][:10]
            rows=''.join(f'<tr><td>{esc(c.get("chemical"))}</td><td>{esc(c.get("years"))}</td><td>{nice(c.get("release_kg"))}</td><td>{nice(c.get("transfer_kg"))}</td><td>{esc(c.get("regulatory_hazard_flags"))}</td></tr>' for c in cmain)
            sig_cards=[f'<table><thead><tr><th>물질</th><th>반복연도</th><th>배출 kg</th><th>이동 kg</th><th>규제·유해 플래그</th></tr></thead><tbody>{rows}</tbody></table>']
        act_rows=[am[i] for i in split_ids(t.get('action_ids')) if i in am]; act_rows=sorted(act_rows,key=lambda r:(str(r.get('year','')),r.get('action_name','')))[:8]
        act_html=''.join(f'<li><b>{esc(a.get("year"))}</b> · {esc(a.get("action_name"))} - {esc(a.get("description"))}<span class="src">ENV-INFO · {money(a.get("investment_million_krw"))} 백만원</span></li>' for a in act_rows) or '<li>같은 사업장·영역의 공개 Action 근거 추가 확인 필요</li>'
        industry=[evm[i] for i in split_ids(x.get('industry_reference_evidence_ids')) if i in evm]; future=[evm[i] for i in split_ids(x.get('future_direction_evidence_ids')) if i in evm]
        industry=rank_evidence(industry,terms,'INDUSTRY_TECHNICAL',4); future=rank_evidence(future,terms,'FUTURE_DIRECTION',3)
        qs=[q for q in questions if q.get('review_id')==x.get('review_id')][:4]
        qhtml=''.join(f'<li>{esc(q.get("question"))}<span class="src">필요근거: {esc(q.get("needed_evidence"))}</span></li>' for q in qs) or '<li>생산량·유량·적용기준·운전조건 등 비공개/현장 정보가 필요할 수 있음.</li>'
        deep_html.append(f'''<section class="deep"><h2>Deep Dive {idx}. {esc(t.get('site_name'))} - {esc(DOMAIN_KO.get(t.get('domain'),t.get('domain')))}</h2>
        <p class="lead"><b>왜 보는가:</b> {esc(t.get('why_review'))} <span class="tag">{esc(x.get('review_state') or t.get('candidate_state'))}</span></p>
        <h3>1) 실제 공개데이터에서 관찰된 변화</h3>{''.join(sig_cards)}
        <h3>2) 같은 사업장/영역에서 공개된 관리활동</h3><ul>{act_html}</ul>
        <div class="grid2">{evidence_card('3) 산업 기술자료: 왜 이 주제를 보는가',industry)}{evidence_card('4) 회사가 밝힌 미래방향',future)}</div>
        <h3>5) 여기서 멈춰야 하는 지점</h3><p class="caveat">{esc(t.get('limitations') or x.get('limitations') or '')}</p>
        <h3>6) 다음에 확인할 질문</h3><ul>{qhtml}</ul></section>''')
    boundaries=review_summary.get('boundaries') or []; bhtml=''.join(f'<li>{esc(x)}</li>' for x in boundaries); report_name=profile.get('requested_company_name') or profile.get('company_display_name') or '기업'
    html_text=f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>
    @page{{size:A4;margin:13mm 12mm 15mm}} body{{font-family:sans-serif;color:#172033;font-size:9.3pt;line-height:1.48}} h1{{font-size:22pt;margin:0 0 4mm}} h2{{font-size:15pt;margin:7mm 0 3mm;border-bottom:2px solid #17365D;padding-bottom:1.5mm}} h3{{font-size:11.5pt;margin:4mm 0 1.5mm;color:#17365D}} h4{{margin:2mm 0 1mm}} p{{margin:1.2mm 0}} ul{{margin:1.2mm 0 2mm;padding-left:5mm}} li{{margin:.8mm 0}} table{{width:100%;border-collapse:collapse;font-size:8.2pt;margin:2mm 0}} th,td{{border:1px solid #c7ced8;padding:1.4mm;vertical-align:top}} th{{background:#eef2f7}} .cover{{min-height:235mm;display:flex;flex-direction:column;justify-content:center}} .kicker{{font-size:10pt;color:#5b6575;letter-spacing:.04em}} .subtitle{{font-size:12pt;color:#465164;margin:3mm 0 8mm}} .box,.domain,.deep{{border:1px solid #d4dbe5;border-radius:6px;padding:4mm;margin:3mm 0;break-inside:avoid}} .domain{{break-inside:auto}} .deep{{break-before:page;border:none;padding:0}} .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:3mm}} .stats{{display:flex;gap:2mm;flex-wrap:wrap;margin:2mm 0}} .stats span,.tag{{background:#eef3f8;border-radius:12px;padding:1mm 2mm;font-size:8pt}} .frame{{background:#f5f7fa;padding:2mm 3mm;border-left:3px solid #17365D}} .caveat{{background:#fff8e7;border-left:3px solid #d49a00;padding:2mm 3mm}} .muted,.src{{color:#697587;font-size:7.6pt}} .src{{display:block;margin-top:.4mm}} .evi{{border:1px solid #d9e0e8;padding:2.5mm;break-inside:avoid}} .signal{{display:inline-block;width:47%;vertical-align:top;border:1px solid #d9e0e8;padding:2mm;margin:1mm;break-inside:avoid}} .spark{{width:100%;height:48px;margin-top:1mm}} .spark polyline{{fill:none;stroke:#17365D;stroke-width:2}} .spark circle{{fill:#17365D}} .spark text{{font-size:8px;fill:#667}} .vals{{font-size:7.5pt;color:#596577;word-break:break-all}} .year{{border-left:3px solid #8fa6bf;padding-left:3mm;margin:3mm 0;break-inside:avoid}} .year h4 span{{font-weight:normal;font-size:8pt;color:#697587}} .lead{{font-size:10pt}} .pagebreak{{break-before:page}}</style></head><body>
    <section class="cover"><div class="kicker">AI-assisted Environmental Management Review</div><h1>{esc(report_name)} 환경관리 검토보고서</h1><div class="subtitle">공개근거 기반 · 요청범위 {esc(scope.get('label') or scope.get('mode'))} · 자동 생성 검증형 프로토타입</div>
    <div class="box"><b>이 보고서의 목적</b><p>기업 환경성과를 평가하거나 현장 원인을 단정하는 문서가 아니다. 비전문가가 공개자료를 통해 <b>무엇을 관리하는 회사인지, 어떤 변화가 보이는지, 무엇을 더 공부해야 하는지</b>를 근거를 따라 이해하도록 돕는 검토자료다.</p></div>
    <div class="stats"><span>요청범위 지표 {review_summary.get('metric_inventory_in_scope','-')}</span><span>관리 Action {review_summary.get('management_actions_in_scope','-')}</span><span>검토주제 {review_summary.get('topic_candidates','-')}</span><span>Deep Dive {review_summary.get('deep_dive_candidates','-')}</span><span>문서 스캔 {cross_summary.get('document_semantics',{}).get('pages_scanned','-')}p</span></div><p class="muted">자동생성 결과는 원자료·페이지 근거와 함께 검토해야 하며, AI가 제시한 연관성은 인과관계를 뜻하지 않는다.</p></section>
    <h2>1. 먼저 머릿속에 넣을 구조</h2><div class="box"><p><b>회사/사업범위</b> → <b>사업장</b> → <b>환경영역</b> → <b>실제 공개값</b> → <b>회사 관리활동</b> → <b>산업 기술근거</b> → <b>미래방향</b> → <b>추가확인</b></p><p>각 층은 독립 근거로 유지한다. 시간적으로 겹친다는 이유만으로 ‘시설투자 때문에 수치가 개선됐다’고 연결하지 않는다.</p></div>
    <h3>요청 사업장</h3><table><thead><tr><th>사업장</th><th>공식 주소</th><th>분석 ID</th></tr></thead><tbody>{site_rows}</tbody></table><h3>공개자료 범위</h3><table><thead><tr><th>Source</th><th>요청범위 연도</th><th>연도 수</th></tr></thead><tbody>{cvrows}</tbody></table><p class="muted">화학물질통계처럼 조사주기가 다른 Source는 동일 연도수로 맞추지 않는다.</p>
    <h2>2. 환경관리 전체 지도</h2>{''.join(domain_html)}
    <h2>3. 2020-2024 관리시설·개선활동 Timeline</h2><p>ENV-INFO에 회사가 공개한 투자·기술도입·개선활동을 요청 사업장 기준으로 모았다. 투자액 합계는 공개 항목의 단순 합이며 성과평가 지표가 아니다.</p>{''.join(year_blocks)}
    <h2>4. 근거가 겹치는 우선 검토주제</h2><p>전체 31개 검토주제 중 현재 규칙상 Deep Dive 후보는 {len(deep)}개다. 선정은 단일 수치의 크기가 아니라 <b>다년도 Signal + 같은 사업장/영역 Action + 독립 Source 중첩</b>을 기본으로 하며, 화학물질은 반복성·배출/이동경로·규제/유해 플래그를 함께 본다.</p>{''.join(deep_html)}
    <h2 class="pagebreak">5. 이 보고서를 읽을 때 지켜야 할 경계</h2><ul>{bhtml}</ul><div class="box"><b>결론 대신 남겨야 하는 것</b><p>[FACT] 원자료에서 직접 확인한 사실 / [AI REVIEW] 근거가 겹쳐 더 볼 가치가 있는 후보 / [TO VERIFY] 공개자료만으로 부족해 현장·허가·운전정보가 필요한 질문을 구분한다.</p></div></body></html>'''
    html_path=root/'Environmental_Review_Brief.html'; html_path.write_text(html_text,encoding='utf-8')
    xlsx_path=root/'Environmental_Review_Evidence.xlsx'
    try:
        import xlsxwriter
        wb=xlsxwriter.Workbook(str(xlsx_path)); hdr=wb.add_format({'bold':True,'bg_color':'#D9E5F2','border':1}); wrap=wb.add_format({'text_wrap':True,'valign':'top'})
        for name,rows in [('Deep_Dive',deep),('Cross_Layer',cross),('Signals',sig),('Actions',scoped_actions),('Chemicals',chems),('Study_Questions',questions),('Evidence_Layers',layers)]:
            ws=wb.add_worksheet(name[:31]); fields=[]
            for r in rows:
                for k in r:
                    if k not in fields: fields.append(k)
            if not fields: fields=['value']; rows=[{'value':'no data'}]
            for c,k in enumerate(fields): ws.write(0,c,k,hdr)
            for i,r in enumerate(rows,1):
                for c,k in enumerate(fields): ws.write(i,c,str(r.get(k,'')),wrap)
            ws.freeze_panes(1,0); ws.autofilter(0,0,max(1,len(rows)),len(fields)-1)
            for c,k in enumerate(fields): ws.set_column(c,c,min(45,max(11,len(k)+2)))
        wb.close()
    except Exception:
        xlsx_path=None
    pdf_path=root/'Environmental_Review_Brief.pdf'; pdf_ok=False; pdf_error=''
    if render_pdf:
        browser=next((shutil.which(x) for x in ['google-chrome','google-chrome-stable','chromium','chromium-browser'] if shutil.which(x)),None)
        if browser:
            # '--headless=new' (not the legacy '--headless' content-shell mode) is required for
            # correct CJK/complex-script text shaping and font embedding in --print-to-pdf output.
            cmd=[browser,'--headless=new','--disable-gpu','--no-sandbox','--allow-file-access-from-files','--no-pdf-header-footer',f'--print-to-pdf={pdf_path.resolve()}',html_path.resolve().as_uri()]
            cp=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
            pdf_ok=valid_pdf(pdf_path)
            if not pdf_ok: pdf_error=cp.stderr.decode('utf-8',errors='replace')[-1000:]
            elif cp.returncode!=0: pdf_error=f'non-zero exit code {cp.returncode} but PDF is valid: '+cp.stderr.decode('utf-8',errors='replace')[-500:]
        else: pdf_error='no chromium-compatible browser found'
    summary={'schema_version':'1.0','report_html':html_path.name,'report_pdf':pdf_path.name if pdf_ok else None,'evidence_xlsx':xlsx_path.name if xlsx_path and xlsx_path.exists() else None,'deep_dive_topics':len(deep),'scope_sites':len(sites),'pdf_ok':pdf_ok,'pdf_error':pdf_error,'principle':'The report organizes evidence for study; it does not automatically judge environmental performance, compliance, risk or causality.'}
    (root/'Environmental_Review_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8'); return summary

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--package-root',default='assembled'); ap.add_argument('--no-pdf',action='store_true'); a=ap.parse_args(); print(json.dumps(build_review_report(a.package_root,not a.no_pdf),ensure_ascii=False))
