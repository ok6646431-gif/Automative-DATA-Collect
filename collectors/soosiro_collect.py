import json, re, sys, time
from pathlib import Path

import requests

BASE="https://www.soosiro.or.kr"
ANNUAL=BASE+"/open/web/annual/listJson"
FACTS=BASE+"/open/web/annual/factListJson"
DAILY=BASE+"/open/web/daily/listJson"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
QUARTERS=["1분기","2분기","3분기","4분기"]
TRANSIENT_STATUSES={408,429,500,502,503,504}

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
    years=[int(x) for x in cfg.get("annual_years",[cfg.get("proof_year",2025)])]
    daily_years=[int(x) for x in cfg.get("daily_years",[])]
    out=Path("output/SOOSIRO_WATER"); raw=out/"raw_annual"; draw=out/"raw_daily"; raw.mkdir(parents=True,exist_ok=True); draw.mkdir(parents=True,exist_ok=True)
    headers={"User-Agent":UA,"Referer":BASE+"/open/web/annual?pMENU_NO=410","Content-Type":"application/x-www-form-urlencoded; charset=UTF-8","Accept":"application/json,text/plain,*/*"}
    status={"source_key":"SOOSIRO_WATER","status":"RUNNING","annual_years":years,"daily_years":daily_years,"terms":terms,"requests":0,"errors":0}
    dedup={}; candidates={}
    try:
        rf=_post(FACTS,data={"pDoCode":""},headers=headers); (out/"fact_list_raw.json").write_text(rf.text,encoding="utf-8")
        for y in years:
            for term in cfg.get("search_terms_by_year",{}).get(str(y),terms):
                status["requests"]+=1
                try:
                    r=_post(ANNUAL,data={"pSYear":str(y),"pEYear":str(y),"pDoCode":"","pFactCode":"","pSearchWord":term},headers=headers)
                    fn=re.sub(r"[^0-9A-Za-z가-힣]+","_",term).strip("_"); (raw/f"{y}_{fn}.json").write_text(r.text,encoding="utf-8")
                    obj=r.json(); rows=obj.get("list",[]) if isinstance(obj,dict) else []
                    for row in rows:
                        fc=str(row.get("FACT_CODE","")); wn=str(row.get("WAST_NO","")); key=(str(row.get("YEAR",y)),fc,wn)
                        if key not in dedup: z=dict(row); z["search_terms_hit"]=term; dedup[key]=z
                        elif term not in dedup[key]["search_terms_hit"].split("|"): dedup[key]["search_terms_hit"]+="|"+term
                        if fc: candidates[fc]={"FACT_CODE":fc,"FACT_NAME":row.get("FACT_NAME"),"FACT_FNAME":row.get("FACT_FNAME"),"FACT_ADDR":row.get("FACT_ADDR")}
                except Exception as e:
                    status["errors"]+=1; (out/"errors.log").open("a",encoding="utf-8").write(f"ANNUAL\t{y}\t{term}\t{type(e).__name__}\t{e}\n")
        annual_rows=list(dedup.values())
        with (out/"annual_rows.jsonl").open("w",encoding="utf-8") as f:
            for row in annual_rows: f.write(json.dumps(row,ensure_ascii=False)+"\n")
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
        status.update({"status":"DATA_FOUND" if annual_rows else "NO_MATCH","annual_rows":len(annual_rows),"fact_codes":len(candidates),"fact_code_list":sorted(candidates),"daily_requests_success":daily_success,"daily_rows":len(daily_rows)})
    except Exception as e: status.update({"status":"REQUEST_OR_PARSE_FAILED","fatal_error":f"{type(e).__name__}: {e}"})
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(status,ensure_ascii=False))
    return 0 if status["status"]!="REQUEST_OR_PARSE_FAILED" else 31

if __name__=="__main__": sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "requests/current.json"))
