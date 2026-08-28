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

def utf8_safe(value):
    """Return text that can always be emitted as strict UTF-8.

    Some PDF extractors can surface isolated UTF-16 surrogate code points. They are
    not valid Unicode scalar values and must never be allowed to crash packaging.
    Normal text is unchanged; only malformed surrogate content is replaced.
    """
    if not isinstance(value,str): return value
    return value.encode('utf-8',errors='replace').decode('utf-8')

def write_csv(path,rows,fields):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader()
        for row in rows:
            # Sanitize in place as well as on disk because callers often reuse the
            # same row objects immediately for JSON generation after CSV emission.
            for k in list(row): row[k]=utf8_safe(row[k])
            w.writerow(row)

def stable_id(prefix,*parts,n=12):
    raw='|'.join('' if x is None else str(x) for x in parts)
    # backslashreplace preserves a deterministic representation of malformed
    # surrogate code points without changing IDs for ordinary valid Unicode.
    safe_bytes=raw.encode('utf-8',errors='backslashreplace')
    return prefix+hashlib.sha1(safe_bytes).hexdigest()[:n].upper()

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

def requested_scope(package_root):
    raw=read_json(Path(package_root)/'Requested_Scope.json',{}) or {}
    mode=str(raw.get('mode') or 'COMPANY').upper()
    canonical={str(x) for x in raw.get('target_canonical_site_ids',[]) or [] if str(x)}
    source_ids={}
    for source,ids in (raw.get('target_source_ids',{}) or {}).items():
        source_ids[str(source)]={str(x) for x in (ids or []) if str(x)}
    return {'mode':mode,'label':raw.get('label') or mode,'target_canonical_site_ids':canonical,'target_source_ids':source_ids,'raw':raw}

def scope_allows(scope,source='',source_site_id='',canonical_site_id=''):
    if not scope or str(scope.get('mode') or 'COMPANY').upper()!='SITE_SET': return True
    cid=str(canonical_site_id or ''); sid=str(source_site_id or ''); src=str(source or '')
    if cid and cid in scope.get('target_canonical_site_ids',set()): return True
    return bool(sid and sid in scope.get('target_source_ids',{}).get(src,set()))

def scope_flag(scope,source='',source_site_id='',canonical_site_id=''):
    return 'YES' if scope_allows(scope,source,source_site_id,canonical_site_id) else 'NO'
