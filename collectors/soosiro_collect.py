import json, re, sys, time
from collections import defaultdict
from pathlib import Path

import requests

try:
    from .name_filter import matching_exclusion
except ImportError:
    from name_filter import matching_exclusion

BASE="https://www.soosiro.or.kr"
ANNUAL=BASE+"/open/web/annual/listJson"
FACTS=BASE+"/open/web/annual/factListJson"
DAILY=BASE+"/open/web/daily/listJson"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
QUARTERS=["1분기","2분기","3분기","4분기"]
TRANSIENT_STATUSES={408,429,500,502,503,504}
PROVINCE_MAP={
    "서울특별시":"서울","부산광역시":"부산","대구광역시":"대구","인천광역시":"인천",
    "광주광역시":"광주","대전광역시":"대전","울산광역시":"울산","세종특별자치시":"세종",
    "경기도":"경기","강원특별자치도":"강원","강원도":"강원","충청북도":"충북","충청남도":"충남",
    "전북특별자치도":"전북","전라북도":"전북","전라남도":"전남","경상북도":"경북","경상남도":"경남",
    "제주특별자치도":"제주"
}


def normalize_address(value):
    text=str(value or "").strip()
    if not text: return ""
    for old,new in PROVINCE_MAP.items(): text=text.replace(old,new)
    # Keep the road-address core through the building number when available, so
    # postal-code annotations or appended facility labels do not break exact match.
    m=re.match(r"^(.*?(?:로|길)\s*\d+(?:-\d+)?)\b",text)
    if m: text=m.group(1)
    return re.sub(r"[\s,._·ㆍ()\[\]{}\-_/\\]","",text).lower()


def address_seed_candidates(facts, site_addresses):
    """Return only unambiguous FACT rows matching a verified official address."""
    target={normalize_address(x) for x in site_addresses if normalize_address(x)}
    by_addr=defaultdict(list)
    for row in facts:
        key=normalize_address(row.get("FACT_ADDR"))
        if key: by_addr[key].append(row)
    seeded=[]
    for key in sorted(target):
        hits=by_addr.get(key,[])
        if len(hits)==1:
            seeded.append(hits[0])
    return seeded


def _post(url, *, data, headers, attempts=3, connect_timeout=5, read_timeout=20):
    """POST with bounded retry for transient transport/server failures only."""
    last=None
    for attempt in range(1, attempts+1):
        try:
            r=requests.post(url,data=data,headers=headers,timeout=(connect_timeout,read_timeout))
            if r.status_code in TRANSIENT_STATUSES and attempt < attempts:
                time.sleep(attempt)
                continue
            r.raise_for_status()
            return r
        except (requests.Timeout, requests.ConnectionError) as e:
            last=e
            if attempt >= attempts:
                raise
            time.sleep(attempt)
        except requests.HTTPError as e:
            last=e
            status=getattr(e.response,"status_code",None)
            if status in TRANSIENT_STATUSES and attempt < attempts:
                time.sleep(attempt)
                continue
            raise
    if last:
        raise last
    raise RuntimeError("SOOSIRO request failed without response")


def main(req_path):
    req=json.loads(Path(req_path).read_text(encoding="utf-8")); cfg=req.get("sources",{}).get("SOOSIRO_WATER",{})
    terms=cfg.get("search_terms") or [cfg.get("search_term",req.get("company_display_name",""))]
    exclude_terms=cfg.get("exclude_terms",[]); site_addresses=cfg.get("site_addresses",[]) or []
    years=[int(x) for x in cfg.get("annual_years",[cfg.get("proof_year",2025)])]
    daily_years=[int(x) for x in cfg.get("daily_years",[])]
    out=Path("output/SOOSIRO_WATER"); raw=out/"raw_annual"; draw=out/"raw_daily"; raw.mkdir(parents=True,exist_ok=True); draw.mkdir(parents=True,exist_ok=True)
    headers={"User-Agent":UA,"Referer":BASE+"/open/web/annual?pMENU_NO=410","Content-Type":"application/x-www-form-urlencoded; charset=UTF-8","Accept":"application/json,text/plain,*/*"}
    status={"source_key":"SOOSIRO_WATER","status":"RUNNING","annual_years":years,"daily_years":daily_years,"terms":terms,"requests":0,"errors":0}
    dedup={}; candidates={}; excluded_rows=[]

    def absorb_rows(rows,y,hit):
        for row in rows:
            source_name=" ".join(str(row.get(k) or "") for k in ("FACT_NAME","FACT_FNAME"))
            exclusion=matching_exclusion(source_name,exclude_terms)
            if exclusion:
                excluded_rows.append({"query_year":y,"search_term":hit,"excluded_by":exclusion,**row})
                continue
            fc=str(row.get("FACT_CODE","") or ""); wn=str(row.get("WAST_NO","") or ""); key=(str(row.get("YEAR",y)),fc,wn)
            if key not in dedup:
                z=dict(row); z["search_terms_hit"]=hit; dedup[key]=z
            elif hit and hit not in dedup[key]["search_terms_hit"].split("|"):
                dedup[key]["search_terms_hit"]+=("|" if dedup[key]["search_terms_hit"] else "")+hit
            if fc:
                prior=candidates.get(fc,{})
                candidates[fc]={"FACT_CODE":fc,"FACT_NAME":row.get("FACT_NAME") or prior.get("FACT_NAME"),"FACT_FNAME":row.get("FACT_FNAME") or prior.get("FACT_FNAME"),"FACT_ADDR":row.get("FACT_ADDR") or prior.get("FACT_ADDR"),"discovery_basis":prior.get("discovery_basis") or ("OFFICIAL_ADDRESS" if hit=="OFFICIAL_ADDRESS" else "SEARCH_TERM")}

    try:
        rf=_post(FACTS,data={"pDoCode":""},headers=headers); (out/"fact_list_raw.json").write_text(rf.text,encoding="utf-8")
        fact_obj=rf.json(); fact_rows=fact_obj.get("list",[]) if isinstance(fact_obj,dict) else []
        seeded=address_seed_candidates(fact_rows,site_addresses)
        seeded_codes=[]
        for fact in seeded:
            fc=str(fact.get("FACT_CODE") or "")
            source_name=" ".join(str(fact.get(k) or "") for k in ("FACT_NAME","FACT_FNAME"))
            exclusion=matching_exclusion(source_name,exclude_terms)
            if not fc or exclusion: continue
            candidates[fc]={"FACT_CODE":fc,"FACT_NAME":fact.get("FACT_NAME"),"FACT_FNAME":fact.get("FACT_FNAME"),"FACT_ADDR":fact.get("FACT_ADDR"),"discovery_basis":"OFFICIAL_ADDRESS"}
            seeded_codes.append(fc)

        # Query unambiguous source fact codes found from verified official addresses.
        # This is essential when SOOSIRO's source-native facility name omits the legal
        # company name.  Name queries still run below to preserve broader discovery.
        for y in years:
            for fc in sorted(set(seeded_codes)):
                status["requests"]+=1
                try:
                    r=_post(ANNUAL,data={"pSYear":str(y),"pEYear":str(y),"pDoCode":"","pFactCode":fc,"pSearchWord":""},headers=headers)
                    (raw/f"{y}_FACT_{fc}.json").write_text(r.text,encoding="utf-8")
                    obj=r.json(); rows=obj.get("list",[]) if isinstance(obj,dict) else []
                    absorb_rows(rows,y,"OFFICIAL_ADDRESS")
                except Exception as e:
                    status["errors"]+=1; (out/"errors.log").open("a",encoding="utf-8").write(f"ANNUAL_FACT\t{y}\t{fc}\t{type(e).__name__}\t{e}\n")

        for y in years:
            for term in cfg.get("search_terms_by_year",{}).get(str(y),terms):
                status["requests"]+=1
                try:
                    r=_post(ANNUAL,data={"pSYear":str(y),"pEYear":str(y),"pDoCode":"","pFactCode":"","pSearchWord":term},headers=headers)
                    fn=re.sub(r"[^0-9A-Za-z가-힣]+","_",term).strip("_"); (raw/f"{y}_{fn}.json").write_text(r.text,encoding="utf-8")
                    obj=r.json(); rows=obj.get("list",[]) if isinstance(obj,dict) else []
                    absorb_rows(rows,y,term)
                except Exception as e:
                    status["errors"]+=1; (out/"errors.log").open("a",encoding="utf-8").write(f"ANNUAL\t{y}\t{term}\t{type(e).__name__}\t{e}\n")
        annual_rows=list(dedup.values())
        with (out/"annual_rows.jsonl").open("w",encoding="utf-8") as f:
            for row in annual_rows: f.write(json.dumps(row,ensure_ascii=False)+"\n")
        with (out/"excluded_rows.jsonl").open("w",encoding="utf-8") as f:
            for row in excluded_rows: f.write(json.dumps(row,ensure_ascii=False)+"\n")
        (out/"fact_candidates.json").write_text(json.dumps(list(candidates.values()),ensure_ascii=False,indent=2),encoding="utf-8")

        daily_rows=[]; daily_success=0
        dheaders=dict(headers); dheaders["Referer"]=BASE+"/open/web/daily?pMENU_NO=419"
        if daily_years:
            for y in daily_years:
                for fc in sorted(candidates):
                    for q in QUARTERS:
                        status["requests"]+=1
                        try:
                            r=_post(DAILY,data={"pSYear":str(y),"pQuarter":q,"pDoCode":"","pFactCode":fc,"pSearchWord":""},headers=dheaders)
                            daily_success+=1
                            (draw/f"{y}_{fc}_{q}.json").write_text(r.text,encoding="utf-8")
                            obj=r.json(); rows=obj.get("list",[]) if isinstance(obj,dict) else []
                            for row in rows:
                                z=dict(row); z["query_year"]=y; z["query_quarter"]=q; z["source_fact_code"]=fc; daily_rows.append(z)
                        except Exception as e:
                            status["errors"]+=1; (out/"errors.log").open("a",encoding="utf-8").write(f"DAILY\t{y}\t{fc}\t{q}\t{type(e).__name__}\t{e}\n")
        with (out/"daily_rows.jsonl").open("w",encoding="utf-8") as f:
            for row in daily_rows: f.write(json.dumps(row,ensure_ascii=False)+"\n")
        status.update({"status":"DATA_FOUND" if annual_rows else "NO_MATCH","annual_rows":len(annual_rows),"excluded_rows":len(excluded_rows),"fact_codes":len(candidates),"fact_code_list":sorted(candidates),"address_seeded_fact_codes":sorted(set(seeded_codes)),"daily_requests_success":daily_success,"daily_rows":len(daily_rows)})
    except Exception as e: status.update({"status":"REQUEST_OR_PARSE_FAILED","fatal_error":f"{type(e).__name__}: {e}","excluded_rows":len(excluded_rows)})
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(status,ensure_ascii=False))
    return 0 if status["status"]!="REQUEST_OR_PARSE_FAILED" else 31

if __name__=="__main__": sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "requests/current.json"))
