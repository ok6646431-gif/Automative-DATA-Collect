import re
from html.parser import HTMLParser
from pathlib import Path
from review_selection_common import num, year, stable_id, resolve_site

class TableParser(HTMLParser):
    def __init__(self): super().__init__(); self.tables=[]; self.table=None; self.row=None; self.cap=False; self.cell=False; self.buf=''
    def handle_starttag(self,tag,attrs):
        if tag=='table' and self.table is None: self.table={'caption':'','rows':[]}
        elif self.table is not None and tag=='caption': self.cap=True
        elif self.table is not None and tag=='tr': self.row=[]
        elif self.table is not None and tag in {'td','th'} and self.row is not None: self.cell=True; self.buf=''
    def handle_data(self,data):
        if self.table is None: return
        if self.cap: self.table['caption']+=data
        if self.cell: self.buf+=data
    def handle_endtag(self,tag):
        if self.table is None: return
        if tag=='caption': self.cap=False
        elif tag in {'td','th'} and self.cell: self.row.append(re.sub(r'\s+',' ',self.buf).strip()); self.cell=False
        elif tag=='tr' and self.row is not None:
            if self.row: self.table['rows'].append(self.row)
            self.row=None
        elif tag=='table': self.table['caption']=re.sub(r'\s+',' ',self.table['caption']).strip(); self.tables.append(self.table); self.table=None

def tables(path):
    p=TableParser(); p.feed(Path(path).read_text(encoding='utf-8',errors='replace')); return p.tables

def site_name(ts,fallback):
    for t in ts:
        if t['caption']=='본사 / 사업장 현황' and len(t['rows'])>=2 and len(t['rows'][1])>=2: return t['rows'][1][1]
    return fallback

METRICS={
'용수 사용·재활용량 실적':[('WATER_USE','WATER_RESOURCES',r'용수 사용량\s+([\d,.]+)\s*ton'),('WATER_REUSE','WATER_RESOURCES',r'용수 재활용량\s+([\d,.]+)\s*ton')],
'에너지원별 사용 실적':[('ENERGY_TOTAL','GHG_ENERGY',r'에너지 총량\s+([\d,.]+)\s*TJ')],
'온실가스배출 실적':[('GHG_SCOPE1','GHG_ENERGY',r'직접배출량\(scopeⅠ\)\s+([\d,.]+)\s*ton'),('GHG_SCOPE2','GHG_ENERGY',r'간접배출량\(scopeⅡ\)\s+([\d,.]+)\s*ton'),('GHG_TOTAL','GHG_ENERGY',r'온실가스배출총량\s+([\d,.]+)\s*ton')],
'대기오염물질 배출 실적':[('NOX_TOTAL','AIR',r'질소산화물\(Nox\)\s+([\d,.]+)\s*ton'),('SOX_TOTAL','AIR',r'황산화물\(SOX\)\s+([\d,.]+)\s*ton'),('TSP_TOTAL','AIR',r'먼지\(TSP\)\s+([\d,.]+)\s*ton')],
'수질오염물질 배출 실적':[('BOD_TOTAL','WATER',r'생물화학적 산소 요구량\(BOD\)\s+([\d,.]+)\s*ton'),('COD_TOTAL','WATER',r'화학적 산소 요구량\(COD\)\s+([\d,.]+)\s*ton'),('TOC_TOTAL','WATER',r'총유기탄소\(TOC\)\s+([\d,.]+)\s*ton'),('SS_TOTAL','WATER',r'부유물질\(SS\)\s+([\d,.]+)\s*ton'),('TN_TOTAL','WATER',r'총질소\(T-N\)\s+([\d,.]+)\s*ton'),('TP_TOTAL','WATER',r'총인\(T-P\)\s+([\d,.]+)\s*ton')],
'폐기물  발생량·재활용량':[('WASTE_GENERAL','WASTE',r'사업장 일반폐기물 발생량\s+([\d,.]+)\s*ton'),('WASTE_HAZARDOUS','WASTE',r'사업장 지정폐기물 발생량\s+([\d,.]+)\s*ton'),('WASTE_CONSTRUCTION','WASTE',r'사업장 건설폐기물 발생량\s+([\d,.]+)\s*ton'),('WASTE_TOTAL','WASTE',r'폐기물발생 총량\s+([\d,.]+)\s*ton')],
'폐기물 재활용 실적':[('WASTE_RECYCLED','WASTE',r'폐기물재활용량\s+([\d,.]+)\s*ton')],
'화학물질 배출실적':[('CHEMICAL_RELEASE_TOTAL','CHEMICALS',r'화학물질 배출량\s+([\d,.]+)\s*ton')]}

def parse_metrics(source_root,idmap):
    out=[]; raw=Path(source_root)/'ENVINFO'/'raw_detail'
    if not raw.exists(): return out
    for p in sorted(raw.glob('*.html')):
        y=year(p.name); m=re.match(r'\d{4}_([^_]+)_',p.name); sid=m.group(1) if m else p.stem; ts=tables(p); cid,cname=resolve_site(idmap,'ENVINFO',sid,site_name(ts,p.stem))
        for t in ts:
            if t['caption'] not in METRICS: continue
            text=' '.join(c for row in t['rows'] for c in row)
            for metric,domain,pat in METRICS[t['caption']]:
                mm=re.search(pat,text,re.I)
                if mm: out.append({'source':'ENVINFO','source_site_id':sid,'canonical_site_id':cid,'site_name':cname,'sub_scope':'','year':y,'domain':domain,'metric':metric,'value':num(mm.group(1)),'unit':'source_native','source_ref':str(p.relative_to(source_root)),'definition_note':''})
    return out

def action_domain(text):
    s=str(text or '').lower(); hits=[]
    rules={'AIR':['대기','scrubber','nox','sox','배기','악취','버너','집진','de-nox','denox'],'WATER_RESOURCES':['용수','upw','중수','ro 농축수','재이용','재사용'],'WATER':['폐수','수질','유수분리','방류','오수'],'CHEMICALS':['chemical','화학','약품','acqc','dcu','coupler','누출','폐액'],'WASTE':['폐기물','재활용','흡착제','자원순환'],'GHG_ENERGY':['온실가스','pfc','f-gas','에너지','전력','냉동기','fan','ups','compressor','lng','rto','rcs']}
    for d,words in rules.items():
        if any(w in s for w in words): hits.append(d)
    return '|'.join(hits) if hits else 'CROSS_MEDIA'

def chunks(t):
    flat=[c for row in t['rows'] for c in row]; starts=[i for i,x in enumerate(flat) if x in {'설비명','투자/기술분야'}]; starts.append(len(flat)); out=[]
    labels={'설비명','투자/기술분야','총사업기간','총투자비','사업내용','내용','효과(절감량)'}
    for a,b in zip(starts,starts[1:]):
        pairs={}; c=flat[a:b]; i=0
        while i<len(c):
            if c[i] in labels and i+1<len(c): pairs[c[i]]=c[i+1]; i+=2
            else: i+=1
        if pairs.get('설비명') or pairs.get('투자/기술분야'): out.append(pairs)
    return out

def parse_actions(source_root,idmap):
    out=[]; raw=Path(source_root)/'ENVINFO'/'raw_detail'
    if not raw.exists(): return out
    for p in sorted(raw.glob('*.html')):
        y=year(p.name); m=re.match(r'\d{4}_([^_]+)_',p.name); sid=m.group(1) if m else p.stem; ts=tables(p); cid,cname=resolve_site(idmap,'ENVINFO',sid,site_name(ts,p.stem))
        for t in ts:
            cap=t['caption']
            if '투자' not in cap or not any(k in cap for k in ['기술','저감','절감']): continue
            for r in chunks(t):
                name=r.get('설비명') or r.get('투자/기술분야') or ''; desc=r.get('사업내용') or r.get('내용') or ''; eff=r.get('효과(절감량)') or ''; inv=num(r.get('총투자비')); d=action_domain(' '.join([name,desc,eff])); d=action_domain(cap) if d=='CROSS_MEDIA' else d
                out.append({'action_id':stable_id('ACT_',cid,y,cap,name,r.get('총사업기간',''),desc,inv,eff),'source':'ENVINFO','source_site_id':sid,'canonical_site_id':cid,'site_name':cname,'year':y,'domain':d,'action_name':name,'period':r.get('총사업기간',''),'investment_million_krw':inv,'description':desc,'disclosed_effect':eff,'source_file':str(p.relative_to(source_root)),'source_caption':cap,'statement_boundary':'Company-disclosed action/effect. Do not infer measured causal impact from timing alone.'})
    return out
