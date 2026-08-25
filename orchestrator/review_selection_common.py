import csv, hashlib, json, re
from pathlib import Path

def read_json(path,default=None):
    p=Path(path); return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default

def read_jsonl(path):
    p=Path(path); out=[]
    if not p.exists(): return out
    for line in p.read_text(encoding='utf-8',errors='replace').splitlines():
        if line.strip():
            try: out.append(json.loads(line))
            except Exception: pass
    return out

def read_csv(path):
    p=Path(path)
    if not p.exists(): return []
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def write_csv(path,rows,fields):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def stable_id(prefix,*parts,n=12):
    raw='|'.join('' if x is None else str(x) for x in parts)
    return prefix+hashlib.sha1(raw.encode('utf-8')).hexdigest()[:n].upper()

def num(v):
    if v is None: return None
    if isinstance(v,(int,float)) and not isinstance(v,bool): return float(v)
    s=str(v).strip().replace(',','')
    if not s or s in {'-','--','N/A','NA','null','None'}: return None
    m=re.search(r'[-+]?\d+(?:\.\d+)?',s)
    return float(m.group(0)) if m else None

def year(v):
    m=re.search(r'(?:19|20)\d{2}',str(v or '')); return int(m.group(0)) if m else None

def source_identity_map(package_root):
    out={}
    for r in read_csv(Path(package_root)/'Source_Identity.csv'):
        src=r.get('source_key',''); sid=str(r.get('source_site_id','') or '')
        if src and sid: out[(src,sid)]=(r.get('canonical_site_id','') or '',r.get('canonical_site_name','') or r.get('source_site_name_raw','') or '')
    return out

def resolve_site(idmap,source,source_id,fallback=''):
    cid,name=idmap.get((source,str(source_id)),('',''))
    return cid or str(source_id), name or fallback or str(source_id)
