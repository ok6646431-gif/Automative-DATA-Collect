import json, re, sys
from pathlib import Path

import requests

BASE="https://www.soosiro.or.kr"; ANNUAL=BASE+"/open/web/annual/listJson"; FACTS=BASE+"/open/web/annual/factListJson"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"


def main(req_path):
    req=json.loads(Path(req_path).read_text(encoding="utf-8")); cfg=req.get("sources",{}).get("SOOSIRO_WATER",{})
    terms=cfg.get("search_terms") or [cfg.get("search_term",req.get("company_display_name",""))]
    years=[int(x) for x in cfg.get("annual_years",[cfg.get("proof_year",2025)])]
    out=Path("output/SOOSIRO_WATER"); raw=out/"raw_annual"; raw.mkdir(parents=True,exist_ok=True)
    headers={"User-Agent":UA,"Referer":BASE+"/open/web/annual?pMENU_NO=410","Content-Type":"application/x-www-form-urlencoded; charset=UTF-8","Accept":"application/json,text/plain,*/*"}
    status={"source_key":"SOOSIRO_WATER","status":"RUNNING","years":years,"terms":terms,"requests":0,"errors":0}
    dedup={}; candidates={}
    try:
        rf=requests.post(FACTS,data={"pDoCode":""},headers=headers,timeout=(5,15)); rf.raise_for_status(); (out/"fact_list_raw.json").write_text(rf.text,encoding="utf-8")
        for y in years:
            for term in terms:
                status["requests"]+=1
                try:
                    r=requests.post(ANNUAL,data={"pSYear":str(y),"pEYear":str(y),"pDoCode":"","pFactCode":"","pSearchWord":term},headers=headers,timeout=(5,15)); r.raise_for_status()
                    fn=re.sub(r"[^0-9A-Za-z가-힣]+","_",term).strip("_"); (raw/f"{y}_{fn}.json").write_text(r.text,encoding="utf-8")
                    obj=r.json(); rows=obj.get("list",[]) if isinstance(obj,dict) else []
                    for row in rows:
                        fc=str(row.get("FACT_CODE","")); wn=str(row.get("WAST_NO","")); key=(str(row.get("YEAR",y)),fc,wn)
                        z=dict(row)
                        if key not in dedup: z["search_terms_hit"]=term; dedup[key]=z
                        elif term not in dedup[key]["search_terms_hit"].split("|"): dedup[key]["search_terms_hit"]+="|"+term
                        if fc: candidates[fc]={"FACT_CODE":fc,"FACT_NAME":row.get("FACT_NAME"),"FACT_FNAME":row.get("FACT_FNAME"),"FACT_ADDR":row.get("FACT_ADDR")}
                except Exception as e:
                    status["errors"]+=1; (out/"errors.log").open("a",encoding="utf-8").write(f"{y}\t{term}\t{type(e).__name__}\t{e}\n")
        rows=list(dedup.values())
        with (out/"annual_rows.jsonl").open("w",encoding="utf-8") as f:
            for row in rows: f.write(json.dumps(row,ensure_ascii=False)+"\n")
        (out/"fact_candidates.json").write_text(json.dumps(list(candidates.values()),ensure_ascii=False,indent=2),encoding="utf-8")
        status.update({"status":"DATA_FOUND" if rows else "NO_MATCH","annual_rows":len(rows),"fact_codes":len(candidates),"fact_code_list":sorted(candidates)})
    except Exception as e: status.update({"status":"REQUEST_OR_PARSE_FAILED","fatal_error":f"{type(e).__name__}: {e}"})
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(status,ensure_ascii=False))
    return 0 if status["status"]!="REQUEST_OR_PARSE_FAILED" else 31

if __name__=="__main__": sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "requests/current.json"))
