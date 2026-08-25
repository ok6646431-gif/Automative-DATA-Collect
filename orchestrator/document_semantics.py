import csv, json, re, subprocess, sys
from html.parser import HTMLParser
from pathlib import Path

from review_selection_common import read_csv, read_json, write_csv, stable_id

FIELDS=[
    'semantic_id','layer','domain','document_id','document_type','report_year','page','semantic_kind','statement',
    'source_key','source_locator','semantic_state','matched_terms','interpretation_boundary'
]

DOMAIN_WORDS={
    'AIR':['대기','배기','질소산화물','nox','sox','hcl','hf','voc','먼지','scrubber','집진','악취'],
    'WATER_RESOURCES':['용수','수자원','재이용','재사용','upw','초순수','ro 농축수','water stewardship','aws','water reuse'],
    'WATER':['수질','폐수','방류','오수','toc','cod','bod','t-n','t-p','총질소','총인','불소','폐수처리','wastewater'],
    'CHEMICALS':['화학물질','화학','chemical','유해물질','규제물질','약품','누출','hf','불산','황산','암모니아','ipa'],
    'WASTE':['폐기물','재활용','자원순환','waste','zero waste','지정폐기물'],
    'GHG_ENERGY':['온실가스','탄소','carbon','scope 1','scope1','scope 2','scope2','pfc','hfc','sf6','nf3','에너지','전력','re100','net zero','넷제로','greenhouse gas']
}
TECHNIQUE_WORDS=['처리','저감','회수','재이용','재사용','흡수','흡착','세정','scrubber','집진','여과','막','ro','응집','침전','중화','산화','소각','rto','탈질','denox','촉매','분리','재활용','recovery','abatement','treatment','recycle']
ISSUE_WORDS=['배출','발생','오염','부하','폐수','배기가스','환경영향','온실가스','유해','누출','사용량','취급','emission','wastewater','pollutant']
FUTURE_WORDS=['목표','계획','예정','추진','확대할','도입할','달성','2030','2040','2050','2029','target','roadmap','strategy','net zero','re100','will ','aim to']
ACTION_WORDS=['설치','도입','적용','운영','개선','교체','구축','증설','감축','저감','재이용','회수','인증','허가','취득','완료','installed','introduced','applied','reduced','reused','certified']
POLICY_WORDS=['정책','방침','규칙','절차','관리체계','위원회','검토','승인','관리기준','금지','제한','policy','procedure','committee','prohibit','restrict']

SUPPORTED_TYPES={'BAT_REFERENCE','GUIDELINE','SUSTAINABILITY_REPORT','ENVIRONMENTAL_POLICY','CHEMICAL_POLICY','SHE_POLICY','ANNUAL_REPORT'}

class TextHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.skip=0; self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style','noscript'}: self.skip+=1
    def handle_endtag(self,tag):
        if tag in {'script','style','noscript'} and self.skip: self.skip-=1
    def handle_data(self,data):
        if not self.skip and data.strip(): self.parts.append(data.strip())


def normalize(text):
    return re.sub(r'\s+',' ',str(text or '')).strip()


def split_units(text):
    raw=str(text or '').replace('\r\n','\n').replace('\r','\n')
    if not raw.strip(): return []
    # Preserve PDF line structure first.  Collapsing all whitespace before splitting
    # caused long technical pages to become one >900-character block and disappear.
    pieces=[]
    for line in re.split(r'\n+',raw):
        line=normalize(line)
        if not line: continue
        pieces.extend(re.split(r'(?<=[.!?。])\s+',line))
    out=[]
    for piece in pieces:
        piece=normalize(piece)
        if len(piece)<35: continue
        if len(piece)<=900:
            out.append(piece); continue
        # Long table/text rows are retained in bounded chunks rather than dropped.
        for i in range(0,len(piece),850):
            chunk=normalize(piece[i:i+850])
            if len(chunk)>=35: out.append(chunk)
    return out


def infer_domains(text):
    s=str(text or '').lower(); out=[]
    for domain,words in DOMAIN_WORDS.items():
        if any(w.lower() in s for w in words): out.append(domain)
    return out


def matched(text,words):
    s=str(text or '').lower(); return [w for w in words if w.lower() in s]


def classify_unit(document_type,text):
    domains=infer_domains(text)
    if not domains: return []
    tech=matched(text,TECHNIQUE_WORDS); issues=matched(text,ISSUE_WORDS); future=matched(text,FUTURE_WORDS); actions=matched(text,ACTION_WORDS); policy=matched(text,POLICY_WORDS)
    rows=[]
    if document_type in {'BAT_REFERENCE','GUIDELINE'}:
        if not (tech or issues): return []
        kind='TECHNIQUE_CONTEXT' if tech else 'ISSUE_CONTEXT'
        for d in domains: rows.append((d,'INDUSTRY_TECHNICAL',kind,sorted(set(tech+issues))))
    else:
        if future:
            for d in domains: rows.append((d,'FUTURE_DIRECTION','TARGET_OR_PLAN',sorted(set(future+actions))))
        if actions:
            for d in domains: rows.append((d,'COMPANY_ACTION','DISCLOSED_ACTION',sorted(set(actions))))
        elif policy:
            for d in domains: rows.append((d,'COMPANY_ACTION','MANAGEMENT_RULE_OR_SYSTEM',sorted(set(policy))))
    return rows


def resolve_document_path(pkg,row):
    raw=str(row.get('stored_path') or '')
    candidates=[]
    if raw:
        p=Path(raw)
        candidates.append(p if p.is_absolute() else pkg/p)
        parts=list(p.parts)
        if 'CORP_DOCS' in parts:
            i=parts.index('CORP_DOCS'); candidates.append(pkg/'output'/Path(*parts[i:]))
    base=pkg/'output'/'CORP_DOCS'/'raw_documents'
    docid=str(row.get('document_id') or '')
    if base.exists() and docid:
        candidates.extend(base.rglob(docid+'_*'))
    for c in candidates:
        try:
            if Path(c).exists() and Path(c).is_file(): return Path(c)
        except Exception: pass
    return None


def pdf_reader():
    try:
        from pypdf import PdfReader
        return PdfReader
    except ImportError:
        # The package stage is a controlled GitHub Actions environment.  Bootstrap
        # the lightweight parser when the workflow image does not already provide it.
        subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','pypdf'],check=True,capture_output=True,text=True)
        from pypdf import PdfReader
        return PdfReader


def extract_pages(path):
    suffix=path.suffix.lower()
    if suffix=='.pdf':
        PdfReader=pdf_reader(); reader=PdfReader(str(path)); out=[]
        for i,page in enumerate(reader.pages,1):
            try: text=page.extract_text() or ''
            except Exception: text=''
            out.append((i,text))
        return out
    if suffix in {'.html','.htm'}:
        parser=TextHTMLParser(); parser.feed(path.read_text(encoding='utf-8',errors='replace')); return [(1,'\n'.join(parser.parts))]
    if suffix in {'.txt','.csv'}:
        return [(1,path.read_text(encoding='utf-8',errors='replace'))]
    return []


def boundary(layer,kind):
    if layer=='INDUSTRY_TECHNICAL': return 'Page-grounded industry-reference excerpt. It does not prove that the company applies the technique or that the excerpt is site-specific.'
    if layer=='FUTURE_DIRECTION': return 'Page-grounded company statement of a target/plan. It is not evidence that the target has been achieved.'
    if kind=='MANAGEMENT_RULE_OR_SYSTEM': return 'Page-grounded public management rule/system statement. Existence of a rule does not prove outcome or complete internal practice.'
    return 'Page-grounded company statement. Do not infer causal impact on environmental data from the statement alone.'


def run_document_semantics(package_root,max_per_document=500):
    pkg=Path(package_root); idx=read_csv(pkg/'output'/'CORP_DOCS'/'document_index.csv'); out=[]; docs=pages=0; failures=[]
    for row in idx:
        dtype=str(row.get('document_type') or '')
        if row.get('collection_status')!='DOWNLOADED' or dtype not in SUPPORTED_TYPES: continue
        path=resolve_document_path(pkg,row)
        if not path:
            failures.append({'document_id':row.get('document_id'),'reason':'LOCAL_FILE_NOT_FOUND'}); continue
        docs+=1; count=0
        try: page_texts=extract_pages(path)
        except Exception as exc:
            failures.append({'document_id':row.get('document_id'),'reason':f'{type(exc).__name__}: {exc}'}); continue
        for page_no,text in page_texts:
            pages+=1
            for unit in split_units(text):
                classes=classify_unit(dtype,unit)
                for domain,layer,kind,terms in classes:
                    out.append({
                        'semantic_id':stable_id('SEM_',row.get('document_id'),page_no,domain,layer,kind,unit[:160]),
                        'layer':layer,'domain':domain,'document_id':row.get('document_id',''),'document_type':dtype,
                        'report_year':row.get('report_year',''),'page':page_no,'semantic_kind':kind,'statement':unit[:900],
                        'source_key':'CORP_DOCS','source_locator':row.get('source_locator') or row.get('source_url') or '',
                        'semantic_state':'PAGE_GROUNDED_EXTRACT','matched_terms':'|'.join(terms),'interpretation_boundary':boundary(layer,kind)
                    }); count+=1
                    if count>=max_per_document: break
                if count>=max_per_document: break
            if count>=max_per_document: break
    dedup=[]; seen=set()
    for r in out:
        key=(r['document_id'],r['page'],r['domain'],r['layer'],r['semantic_kind'],r['statement'])
        if key not in seen: seen.add(key); dedup.append(r)
    write_csv(pkg/'Document_Semantic_Candidates.csv',dedup,FIELDS)

    profile=read_json(pkg/'Company_Profile.json',{}) or {}
    facts=[]
    for r in dedup:
        if r['layer']!='INDUSTRY_TECHNICAL': continue
        locator=r['source_locator'] + (('#page='+str(r['page'])) if r.get('page') else '')
        facts.append({
            'fact_id':r['semantic_id'],'layer':'INDUSTRY_TECHNICAL','domain':r['domain'],'time_key':r.get('report_year',''),
            'title':f"{r['document_id']} p.{r['page']} {r['semantic_kind']}",'statement':r['statement'],
            'source_key':'CORP_DOCS','source_locator':locator,'interpretation_boundary':r['interpretation_boundary']
        })
    generated={'schema_version':'1.0','request_id':profile.get('request_id',''),'facts':facts,
               'generation_rule':'Only page-grounded INDUSTRY_TECHNICAL excerpts are auto-promoted as reference facts. Company action/future excerpts remain page-grounded candidates and may be used only as statements of company action/plan, never as proof of performance or causality.'}
    (pkg/'Generated_Semantic_Evidence.json').write_text(json.dumps(generated,ensure_ascii=False,indent=2),encoding='utf-8')

    summary={'schema_version':'1.2','documents_processed':docs,'pages_scanned':pages,'semantic_candidates':len(dedup),
             'generated_industry_facts':len(facts),'layer_counts':{k:sum(r['layer']==k for r in dedup) for k in ['INDUSTRY_TECHNICAL','COMPANY_ACTION','FUTURE_DIRECTION']},
             'failures':failures,'principle':'Extraction is page-grounded candidate evidence; company BAT application, performance and causality are never inferred automatically.'}
    (pkg/'Document_Semantics_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary


def main():
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--package-root',default='assembled'); ap.add_argument('--max-per-document',type=int,default=500); a=ap.parse_args()
    print(json.dumps(run_document_semantics(a.package_root,a.max_per_document),ensure_ascii=False))

if __name__=='__main__': main()
