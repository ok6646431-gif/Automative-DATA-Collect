import argparse, csv, hashlib, json, re
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

SOURCES=["ENVINFO","PRTR","CHEM_STATS","CLEANSYS_AIR","SOOSIRO_WATER"]
ADDRESS_SOURCES={"ENVINFO","PRTR","CHEM_STATS","SOOSIRO_WATER"}
PROVINCE_MAP={
    "서울특별시":"서울","부산광역시":"부산","대구광역시":"대구","인천광역시":"인천",
    "광주광역시":"광주","대전광역시":"대전","울산광역시":"울산","세종특별자치시":"세종",
    "경기도":"경기","강원특별자치도":"강원","강원도":"강원","충청북도":"충북","충청남도":"충남",
    "전북특별자치도":"전북","전라북도":"전북","전라남도":"전남","경상북도":"경북","경상남도":"경남",
    "제주특별자치도":"제주"
}
LEGAL_PATTERNS=[r"\(주\)",r"㈜",r"주식회사",r"유한회사",r"\(유\)"]
FACILITY_WORDS=["사업장","공장","캠퍼스","연구원","기술연구원"]


def read_json(p, default=None):
    p=Path(p)
    if not p.exists(): return default
    return json.loads(p.read_text(encoding="utf-8"))


def read_jsonl(p):
    p=Path(p)
    if not p.exists(): return []
    out=[]
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip(): out.append(json.loads(line))
    return out


def read_csv(p):
    p=Path(p)
    if not p.exists(): return []
    with p.open(encoding="utf-8-sig",newline="") as f: return list(csv.DictReader(f))


def write_csv(p, rows, fields):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)


def stable_id(prefix,*parts,n=12):
    raw="|".join("" if x is None else str(x) for x in parts)
    return prefix+hashlib.sha1(raw.encode("utf-8")).hexdigest()[:n].upper()


def company_alias_tokens(profile):
    vals=[profile.get("company_display_name","")]
    vals += [x.get("term","") for x in profile.get("aliases",[]) if isinstance(x,dict)]
    out=set()
    for v in vals:
        s=str(v)
        for pat in LEGAL_PATTERNS: s=re.sub(pat,"",s,flags=re.I)
        s=re.sub(r"[^0-9A-Za-z가-힣]","",s).lower()
        if len(s)>=2: out.add(s)
    return sorted(out,key=len,reverse=True)


def normalize_name(x, profile=None):
    s=str(x or "")
    for pat in LEGAL_PATTERNS: s=re.sub(pat,"",s,flags=re.I)
    s=re.sub(r"[^0-9A-Za-z가-힣]","",s).lower()
    if profile:
        for tok in company_alias_tokens(profile):
            s=s.replace(tok,"")
    for word in FACILITY_WORDS:
        s=s.replace(word,"")
    return s


def normalize_address(x, profile=None):
    s=str(x or "").strip()
    if not s: return ""
    for old,new in PROVINCE_MAP.items(): s=s.replace(old,new)
    # Prefer the road-address core through the building number. This removes appended
    # lot numbers, plant labels and floor text without guessing a different address.
    m=re.match(r"^(.*?(?:로|길)\s*\d+(?:-\d+)?)\b",s)
    if m: s=m.group(1)
    s=re.sub(r"\((?:주|유)\)","",s)
    if profile:
        aliases=[profile.get("company_display_name","")]+[a.get("term","") for a in profile.get("aliases",[]) if isinstance(a,dict)]
        for a in sorted(set(aliases),key=len,reverse=True):
            if a: s=re.sub(re.escape(a),"",s,flags=re.I)
    for pat in LEGAL_PATTERNS: s=re.sub(pat,"",s,flags=re.I)
    s=re.sub(r"\s+(?:본사|[0-9A-Za-z가-힣&·._-]+(?:공장|사업장|캠퍼스|연구원))\s*$","",s)
    s=re.sub(r"[\s,._·ㆍ()\[\]{}\-_/\\]","",s).lower()
    return s


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables=[]; self.table=None; self.in_caption=False; self.in_cell=False; self.cell=""; self.row=None
    def handle_starttag(self,tag,attrs):
        if tag=="table": self.table={"caption":"","rows":[]}
        elif self.table is not None and tag=="caption": self.in_caption=True
        elif self.table is not None and tag=="tr": self.row=[]
        elif self.table is not None and tag in {"th","td"} and self.row is not None:
            self.in_cell=True; self.cell=""
    def handle_data(self,data):
        if self.table is None: return
        if self.in_caption: self.table["caption"]+=data
        if self.in_cell: self.cell+=data
    def handle_endtag(self,tag):
        if self.table is None: return
        if tag=="caption": self.in_caption=False
        elif tag in {"th","td"} and self.in_cell:
            self.row.append(re.sub(r"\s+"," ",self.cell).strip()); self.in_cell=False; self.cell=""
        elif tag=="tr" and self.row is not None:
            if self.row: self.table["rows"].append(self.row)
            self.row=None
        elif tag=="table":
            self.tables.append(self.table); self.table=None


def envinfo_detail_identity(detail_dir, comp_id):
    hits=sorted(Path(detail_dir).glob(f"*_{comp_id}_*.html"))
    if not hits: return None
    parser=TableParser(); parser.feed(hits[0].read_text(encoding="utf-8",errors="replace"))
    for t in parser.tables:
        if "본사 / 사업장 현황" not in re.sub(r"\s+"," ",t["caption"]).strip(): continue
        rows=t["rows"]
        if len(rows)<2: continue
        header=rows[0]
        try: ni=header.index("사업장명"); ai=header.index("주소")
        except ValueError: continue
        row=rows[1]
        if len(row)>max(ni,ai): return {"name":row[ni],"address":row[ai],"detail_file":str(hits[0])}
    return None


def years_span(years):
    vals=[]
    for y in years:
        try: vals.append(int(str(y)[:4]))
        except Exception: pass
    return sorted(set(vals))


def candidate_key(c): return (c["source_key"],str(c["source_site_id"]))


def extract_candidates(root,profile):
    root=Path(root); out=[]
    detail_dir=root/"ENVINFO"/"raw_detail"
    for r in read_csv(root/"ENVINFO"/"discovery.csv"):
        cid=str(r.get("compId") or "")
        if not cid: continue
        d=envinfo_detail_identity(detail_dir,cid)
        out.append({"source_key":"ENVINFO","source_site_id":cid,"source_site_name_raw":r.get("compNm") or (d or {}).get("name","") ,"source_address_raw":(d or {}).get("address","") ,"years":[r.get("year")],"raw_ref":(d or {}).get("detail_file","")})
    for r in read_csv(root/"PRTR"/"discovery.csv"):
        eid=str(r.get("entrps_id") or "")
        if eid: out.append({"source_key":"PRTR","source_site_id":eid,"source_site_name_raw":r.get("company_name_raw","") ,"source_address_raw":r.get("address_raw","") ,"years":[r.get("search_year")],"raw_ref":"PRTR/discovery.csv"})
    for r in read_csv(root/"CHEM_STATS"/"discovery.csv"):
        bid=str(r.get("bplcId") or "")
        if bid: out.append({"source_key":"CHEM_STATS","source_site_id":bid,"source_site_name_raw":r.get("bplcNm","") ,"source_address_raw":r.get("locplcAdres","") ,"years":[r.get("search_year") or r.get("reportYear")],"raw_ref":"CHEM_STATS/discovery.csv"})
    cy=defaultdict(set)
    for r in read_jsonl(root/"CLEANSYS_AIR"/"annual_rows.jsonl"):
        fc=str(r.get("source_fact_code") or ""); y=r.get("examin_year")
        if fc and y is not None: cy[fc].add(str(y))
    for r in read_json(root/"CLEANSYS_AIR"/"candidates.json",[]) or []:
        fc=str(r.get("fact_code") or "")
        if fc: out.append({"source_key":"CLEANSYS_AIR","source_site_id":fc,"source_site_name_raw":r.get("company_name_raw","") ,"source_address_raw":"","years":sorted(cy[fc]),"raw_ref":"CLEANSYS_AIR/candidates.json"})
    sy=defaultdict(set)
    for r in read_jsonl(root/"SOOSIRO_WATER"/"annual_rows.jsonl"):
        fc=str(r.get("FACT_CODE") or r.get("source_fact_code") or ""); y=r.get("YEAR",r.get("year"))
        if fc and y is not None: sy[fc].add(str(y))
    for r in read_json(root/"SOOSIRO_WATER"/"fact_candidates.json",[]) or []:
        fc=str(r.get("FACT_CODE") or "")
        if fc: out.append({"source_key":"SOOSIRO_WATER","source_site_id":fc,"source_site_name_raw":r.get("FACT_FNAME") or r.get("FACT_NAME","") ,"source_address_raw":r.get("FACT_ADDR","") ,"years":sorted(sy[fc]),"raw_ref":"SOOSIRO_WATER/fact_candidates.json"})
    merged={}
    for c in out:
        k=candidate_key(c)
        if k not in merged: merged[k]=c
        else: merged[k]["years"]=sorted(set(merged[k]["years"]+c["years"]))
    return list(merged.values())


def excluded(c,profile):
    text=normalize_name(c.get("source_site_name_raw"))
    for ex in profile.get("related_entity_exclusions",[]):
        if normalize_name(ex) and normalize_name(ex) in text: return str(ex)
    return ""


def resolve_identity(candidates,profile):
    company_id=profile.get("company_id") or stable_id("COMP_",normalize_name(profile.get("company_display_name")))

    # A verified Discovery site address is first-party identity evidence.  When one
    # normalized official address maps to exactly one confirmed site candidate, a
    # source row with that exact address may be linked without requiring a second
    # public database to spell the site label the same way.  Duplicate official
    # addresses remain ambiguous and never auto-confirm.
    official_by_addr=defaultdict(list)
    for site in profile.get("site_candidates",[]) or []:
        if not isinstance(site,dict): continue
        if site.get("verification_state") not in {"VERIFIED","SOURCE_VERIFIED"}: continue
        if site.get("identity_status") != "CONFIRMED": continue
        addr=normalize_address(site.get("address_raw"),profile)
        if addr: official_by_addr[addr].append(site)
    official_unique={addr:items[0] for addr,items in official_by_addr.items() if len(items)==1}

    # Cross-source confirmation remains available for sites that do not have a
    # unique verified Discovery address anchor.
    by_pair=defaultdict(list); by_addr=defaultdict(list)
    for c in candidates:
        c["address_key"]=normalize_address(c.get("source_address_raw"),profile)
        c["name_key"]=normalize_name(c.get("source_site_name_raw"),profile)
        if c["address_key"]:
            by_addr[c["address_key"]].append(c)
            by_pair[(c["address_key"],c["name_key"])].append(c)
    strong={k:cs for k,cs in by_pair.items() if len({x["source_key"] for x in cs})>=2}

    site_rows=[]; site_by_pair={}; official_sid_by_addr={}; confirmed_name_to_sites=defaultdict(set)
    for addr,site in sorted(official_unique.items()):
        name=str(site.get("site_name_raw") or site.get("candidate_id") or "official site")
        namekey=normalize_name(name,profile)
        sid=stable_id("SITE_",company_id,addr,namekey or site.get("candidate_id") or "official")
        source_years=[y for c in by_addr.get(addr,[]) for y in c.get("years",[])]
        yrs=years_span(source_years)
        site_rows.append({"company_id":company_id,"canonical_site_id":sid,"canonical_site_name":name,"site_type":"UNKNOWN","country":"KR","region":"UNKNOWN","canonical_address_key":addr,"identity_status":"CONFIRMED","first_seen_year":min(yrs) if yrs else "UNKNOWN","last_seen_year":max(yrs) if yrs else "UNKNOWN","active_status":"UNKNOWN","notes":"AUTO_CONFIRMED: unique verified official Discovery address anchor"})
        official_sid_by_addr[addr]=sid
        if namekey: confirmed_name_to_sites[namekey].add(sid)

    for (addr,namekey),cs in sorted(strong.items()):
        if addr in official_sid_by_addr:
            sid=official_sid_by_addr[addr]
            site_by_pair[(addr,namekey)]=sid
            if namekey: confirmed_name_to_sites[namekey].add(sid)
            continue
        sid=stable_id("SITE_",company_id,addr,namekey)
        preferred=next((x for x in cs if x["source_key"]=="ENVINFO"),cs[0])
        yrs=years_span([y for x in cs for y in x.get("years",[])])
        site_rows.append({"company_id":company_id,"canonical_site_id":sid,"canonical_site_name":preferred["source_site_name_raw"],"site_type":"UNKNOWN","country":"KR","region":"UNKNOWN","canonical_address_key":addr,"identity_status":"CONFIRMED","first_seen_year":min(yrs) if yrs else "UNKNOWN","last_seen_year":max(yrs) if yrs else "UNKNOWN","active_status":"UNKNOWN","notes":f"AUTO_CONFIRMED: exact normalized address+site label across {len({x['source_key'] for x in cs})} independent sources"})
        site_by_pair[(addr,namekey)]=sid
        if namekey: confirmed_name_to_sites[namekey].add(sid)

    # Every unresolved address+label pair remains a distinct candidate unless its
    # address is already anchored to one unique verified official site.
    for (addr,namekey),cs in sorted(by_pair.items()):
        if (addr,namekey) in strong: continue
        if addr in official_sid_by_addr:
            site_by_pair[(addr,namekey)]=official_sid_by_addr[addr]
            if namekey: confirmed_name_to_sites[namekey].add(official_sid_by_addr[addr])
            continue
        preferred=next((x for x in cs if x["source_key"]=="ENVINFO"),cs[0])
        sid=stable_id("CAND_",company_id,addr,namekey)
        yrs=years_span([y for x in cs for y in x.get("years",[])])
        site_rows.append({"company_id":company_id,"canonical_site_id":sid,"canonical_site_name":preferred["source_site_name_raw"],"site_type":"UNKNOWN","country":"KR","region":"UNKNOWN","canonical_address_key":addr,"identity_status":"NEW_SITE_CANDIDATE","first_seen_year":min(yrs) if yrs else "UNKNOWN","last_seen_year":max(yrs) if yrs else "UNKNOWN","active_status":"UNKNOWN","notes":"Address/name pair lacks independent cross-source confirmation; not auto-merged"})
        site_by_pair[(addr,namekey)]=sid

    id_rows=[]; validations=[]
    for c in sorted(candidates,key=lambda x:(x["source_key"],str(x["source_site_id"]))):
        ex=excluded(c,profile); years=years_span(c.get("years",[]))
        if c["source_key"]=="CHEM_STATS" and years:
            vf=vt=",".join(map(str,years)); round_note="survey_rounds="+vf
        else:
            vf=min(years) if years else "UNKNOWN"; vt=max(years) if years else "UNKNOWN"; round_note=""
        sid=""; match_status="REVIEW_REQUIRED"; basis="UNRESOLVED"; review=True; note=round_note
        pair=(c["address_key"],c["name_key"])
        if ex:
            match_status="REJECTED"; basis="RELATED_ENTITY_EXCLUSION"; review=False; note=(note+"; " if note else "")+f"excluded entity: {ex}"
        elif c["address_key"] in official_sid_by_addr:
            sid=official_sid_by_addr[c["address_key"]]; match_status="CONFIRMED"; basis="OFFICIAL_SITE_EXACT_ADDRESS"; review=False
        elif pair in strong:
            sid=site_by_pair[pair]; match_status="CONFIRMED"; basis="CROSS_SOURCE_EXACT_ADDRESS_NAME"; review=False
        elif c["address_key"]:
            sid=site_by_pair[pair]; match_status="REVIEW_REQUIRED"; basis="SINGLE_OR_CONFLICTING_SOURCE_ADDRESS"; review=True; note=(note+"; " if note else "")+"address/name pair not independently confirmed"
        elif c["name_key"] and len(confirmed_name_to_sites.get(c["name_key"],set()))==1:
            sid=next(iter(confirmed_name_to_sites[c["name_key"]])); match_status="REVIEW_REQUIRED"; basis="NAME_ONLY_CANDIDATE"; review=True; note=(note+"; " if note else "")+"unique confirmed site-name candidate only; address/detail required"
        elif c["name_key"] and len(confirmed_name_to_sites.get(c["name_key"],set()))>1:
            basis="AMBIGUOUS_NAME"; note=(note+"; " if note else "")+"normalized name maps to multiple confirmed sites"
        else:
            basis="NO_ADDRESS_NO_UNIQUE_NAME"; note=(note+"; " if note else "")+"insufficient identity evidence"
        row={"company_id":company_id,"canonical_site_id":sid,"source_key":c["source_key"],"source_site_id":str(c["source_site_id"]),"source_site_name_raw":c.get("source_site_name_raw","") ,"source_address_raw":c.get("source_address_raw","") ,"valid_from":vf,"valid_to":vt,"match_status":match_status,"match_basis":basis,"review_required":review,"raw_id_text_required":True,"notes":note}
        id_rows.append(row)
        if review:
            vid=stable_id("VAL_",company_id,c["source_key"],c["source_site_id"],basis)
            validations.append({"validation_id":vid,"company_id":company_id,"object_type":"SOURCE_IDENTITY","object_key":f"{c['source_key']}:{c['source_site_id']}","issue_type":"WEAK_CROSS_SOURCE_MATCH" if basis in {"NAME_ONLY_CANDIDATE","AMBIGUOUS_NAME"} else "NEW_SITE_CANDIDATE","severity":"HIGH" if basis in {"NAME_ONLY_CANDIDATE","AMBIGUOUS_NAME"} else "MEDIUM","detected_by":"IDENTITY_RULE","evidence":f"name={c.get('source_site_name_raw','')} | address={c.get('source_address_raw','')} | basis={basis}","recommended_action":"confirm source ID with official address/detail before canonical merge","status":"REVIEW_REQUIRED","resolved_by":"","resolved_at":"","notes":note})
    return company_id,site_rows,id_rows,validations


def coverage_rows(root,company_id,id_rows):
    root=Path(root); rows=[]
    linked=defaultdict(set)
    for r in id_rows:
        if r.get("canonical_site_id"): linked[r["source_key"]].add(r["canonical_site_id"])
    for s in SOURCES:
        status=read_json(root/s/"status.json",{}) or {}
        years=[]; detail=""
        if s=="ENVINFO":
            rs=read_csv(root/s/"discovery.csv"); years=years_span([r.get("year") for r in rs]); detail=f"{len(rs)} source identities"
        elif s in {"PRTR","CHEM_STATS"}:
            rs=read_csv(root/s/"discovery.csv"); years=years_span([r.get("search_year") for r in rs]); detail=f"{len(rs)} source identities"
            if s=="CHEM_STATS" and years: detail="survey rounds: "+"/".join(map(str,years))
        elif s=="CLEANSYS_AIR":
            rs=read_jsonl(root/s/"annual_rows.jsonl"); years=years_span([r.get("examin_year") for r in rs]); detail=f"{len(rs)} annual rows / {status.get('candidate_count',0)} fact_codes"
        else:
            rs=read_jsonl(root/s/"annual_rows.jsonl"); years=years_span([r.get("YEAR",r.get("year")) for r in rs]); drows=read_jsonl(root/s/"daily_rows.jsonl"); detail=f"{len(rs)} annual rows / {len(drows)} daily rows / {status.get('fact_codes',0)} fact_codes"
        cstart=min(years) if years else "UNKNOWN"; cend=max(years) if years else "UNKNOWN"
        if s=="CHEM_STATS": meets=(len(years)>=3 and (max(years)-min(years)>=4)) if years else False
        else: meets=(len(years)>=5 and all((years[i+1]-years[i])==1 for i in range(len(years)-1))) if years else False
        comp="SURVEY_ROUND" if s=="CHEM_STATS" else ("PENDING_COD_TOC_CHECK" if s=="SOOSIRO_WATER" else "PENDING")
        cov_status="MEETS_MINIMUM" if meets else ("NO_DATA" if not years else "SHORT_COVERAGE")
        rows.append({"company_id":company_id,"source_key":s,"coverage_scope":f"{len(linked[s])} linked/candidate sites","available_start":"UNKNOWN","available_end":"UNKNOWN","collected_start":cstart,"collected_end":cend,"rounds_or_detail":detail,"meets_minimum":meets,"event_baseline_status":"PENDING_EVENT_LINK","comparability_status":comp,"coverage_status":cov_status,"next_action":"event/comparability review" if meets else "extend collection window to minimum policy/full public history"})
    return rows


def merge_review_json(path, validations):
    p=Path(path); existing=read_json(p,[]) or []
    seen={x.get("validation_id") for x in existing if isinstance(x,dict) and x.get("validation_id")}
    merged=list(existing)
    for v in validations:
        if v["validation_id"] not in seen: merged.append(v); seen.add(v["validation_id"])
    p.write_text(json.dumps(merged,ensure_ascii=False,indent=2),encoding="utf-8")


def run_integration(root,profile_path,out):
    root=Path(root); out=Path(out); profile=read_json(profile_path,{}) or {}
    candidates=extract_candidates(root,profile)
    company_id,sites,ids,validations=resolve_identity(candidates,profile)
    cov=coverage_rows(root,company_id,ids)
    write_csv(out/"Site_Master.csv",sites,["company_id","canonical_site_id","canonical_site_name","site_type","country","region","canonical_address_key","identity_status","first_seen_year","last_seen_year","active_status","notes"])
    write_csv(out/"Source_Identity.csv",ids,["company_id","canonical_site_id","source_key","source_site_id","source_site_name_raw","source_address_raw","valid_from","valid_to","match_status","match_basis","review_required","raw_id_text_required","notes"])
    write_csv(out/"Coverage_Status.csv",cov,["company_id","source_key","coverage_scope","available_start","available_end","collected_start","collected_end","rounds_or_detail","meets_minimum","event_baseline_status","comparability_status","coverage_status","next_action"])
    write_csv(out/"Validation_Queue.csv",validations,["validation_id","company_id","object_type","object_key","issue_type","severity","detected_by","evidence","recommended_action","status","resolved_by","resolved_at","notes"])
    merge_review_json(out/"REVIEW_REQUIRED.json",validations)
    summary={"company_id":company_id,"identity_candidates":len(candidates),"canonical_confirmed":sum(x["identity_status"]=="CONFIRMED" for x in sites),"new_site_candidates":sum(x["identity_status"]=="NEW_SITE_CANDIDATE" for x in sites),"source_identity_confirmed":sum(x["match_status"]=="CONFIRMED" for x in ids),"identity_review_required":sum(bool(x["review_required"]) for x in ids),"coverage_short":sum(x["coverage_status"]=="SHORT_COVERAGE" for x in cov)}
    (out/"Integration_Summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    return summary


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="assembled/output"); ap.add_argument("--profile",default="requests/company_profile.json"); ap.add_argument("--out",default="assembled")
    a=ap.parse_args(); summary=run_integration(a.root,a.profile,a.out); print(json.dumps(summary,ensure_ascii=False))

if __name__=="__main__": main()
