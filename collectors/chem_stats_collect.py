import csv, json, re, sys, time
from pathlib import Path

import requests

URL="https://icis.mcee.go.kr/iprtr/cdrInfoDetailListJson.do"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"


def walk(obj):
    if isinstance(obj,dict):
        if any(str(k).lower()=="bplcid" for k in obj): yield obj
        for v in obj.values(): yield from walk(v)
    elif isinstance(obj,list):
        for v in obj: yield from walk(v)

def main(req_path):
    req=json.loads(Path(req_path).read_text(encoding="utf-8")); cfg=req.get("sources",{}).get("CHEM_STATS",{})
    years=[int(x) for x in cfg.get("years",[2024])]; terms=cfg.get("search_terms") or [req.get("company_display_name","")]; max_pages=int(cfg.get("max_pages",10))
    out=Path("output/CHEM_STATS"); raw=out/"raw_discovery"; raw.mkdir(parents=True,exist_ok=True)
    s=requests.Session(); s.headers.update({"User-Agent":UA,"X-Requested-With":"XMLHttpRequest","Accept":"application/json,text/javascript,*/*;q=0.01","Referer":"https://icis.mcee.go.kr/pageLink.do"})
    status={"source_key":"CHEM_STATS","status":"RUNNING","requests":0,"errors":0,"years":years,"terms":terms}
    dedup={}; successful=0
    try:
        for y in years:
            for term in terms:
                for page in range(1,max_pages+1):
                    status["requests"]+=1
                    try:
                        r=s.post(URL,data={"searchYear":str(y),"bplcNm":term,"pageNo":str(page)},timeout=(5,20)); r.raise_for_status(); successful+=1
                    except Exception as e:
                        status["errors"]+=1
                        (out/"errors.log").open("a",encoding="utf-8").write(f"{y}\t{term}\t{page}\t{type(e).__name__}\t{e}\n"); break
                    fn=re.sub(r"[^0-9A-Za-z가-힣]+","_",term).strip("_")
                    (raw/f"{y}_{fn}_p{page}.json").write_text(r.text,encoding="utf-8")
                    try: obj=r.json()
                    except Exception: break
                    rows=list(walk(obj))
                    if not rows: break
                    new=0
                    for row in rows:
                        bid=next((v for k,v in row.items() if str(k).lower()=="bplcid"),None)
                        if not bid: continue
                        key=(y,str(bid))
                        if key not in dedup:
                            z={"search_year":y,**row,"search_terms_hit":term}; dedup[key]=z; new+=1
                        elif term not in str(dedup[key].get("search_terms_hit","")).split("|"):
                            dedup[key]["search_terms_hit"]+="|"+term
                    if new==0 and page>1: break
                    time.sleep(float(cfg.get("request_delay_ms",100))/1000)
        rows=list(dedup.values())
        if rows:
            keys=sorted({k for r in rows for k in r})
            with (out/"discovery.csv").open("w",newline="",encoding="utf-8-sig") as f:
                w=csv.DictWriter(f,fieldnames=keys,extrasaction="ignore"); w.writeheader(); w.writerows(rows)
            with (out/"discovery.jsonl").open("w",encoding="utf-8") as f:
                for r in rows: f.write(json.dumps(r,ensure_ascii=False)+"\n")
        status.update({"status":"DATA_FOUND" if rows else ("NO_MATCH" if successful else "REMOTE_HOST_UNREACHABLE"),"rows":len(rows),"successful_responses":successful,"unique_bplc_ids":len({next((v for k,v in r.items() if str(k).lower()=='bplcid'),None) for r in rows})})
    except Exception as e:
        status.update({"status":"REQUEST_OR_PARSE_FAILED","fatal_error":f"{type(e).__name__}: {e}"})
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(status,ensure_ascii=False))
    return 0 if status["status"] not in {"REQUEST_OR_PARSE_FAILED"} else 71

if __name__=="__main__": sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "requests/current.json"))
