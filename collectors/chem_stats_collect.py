import csv, json, re, sys, time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE="https://icis.mcee.go.kr"
DISCOVERY=BASE+"/iprtr/cdrInfoDetailListJson.do"
DETAIL=BASE+"/iprtr/cdrInfoView.do"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"


def walk(obj):
    if isinstance(obj,dict):
        if any(str(k).lower()=="bplcid" for k in obj): yield obj
        for v in obj.values(): yield from walk(v)
    elif isinstance(obj,list):
        for v in obj: yield from walk(v)

def safe(x): return re.sub(r"[^0-9A-Za-z가-힣._-]+","_",str(x)).strip("_")

def detail_params(year,bid,term=""):
    return {"searchAdres1Text":"","streNo":"","searchMttrWord":"","searchYear":str(year),"searchCategory":"","searchAdres2":"","bplcNm":term,"irsttList":"","pageNo":"1","bplcId":str(bid),"indutyCode2":"","indutyCode3":"","searchAdres2Text":"","mttrGroup":"","indutyCode4":""}

def generic_tables(html,year,bid):
    soup=BeautifulSoup(html,"html.parser"); rows=[]
    for ti,t in enumerate(soup.find_all("table")):
        for ri,tr in enumerate(t.find_all("tr")):
            cells=[x.get_text(" ",strip=True) for x in tr.find_all(["th","td"])]
            if cells: rows.append({"search_year":year,"bplcId":bid,"table_index":ti,"row_index":ri,"cells":cells})
    return rows

def main(req_path):
    req=json.loads(Path(req_path).read_text(encoding="utf-8")); cfg=req.get("sources",{}).get("CHEM_STATS",{})
    years=[int(x) for x in cfg.get("years",[2024])]; terms=cfg.get("search_terms") or [req.get("company_display_name","")]; max_pages=int(cfg.get("max_pages",10))
    out=Path("output/CHEM_STATS"); raw=out/"raw_discovery"; details=out/"raw_detail"; raw.mkdir(parents=True,exist_ok=True); details.mkdir(parents=True,exist_ok=True)
    s=requests.Session(); s.headers.update({"User-Agent":UA,"X-Requested-With":"XMLHttpRequest","Accept":"application/json,text/javascript,*/*;q=0.01","Referer":BASE+"/pageLink.do"})
    status={"source_key":"CHEM_STATS","status":"RUNNING","requests":0,"errors":0,"years":years,"terms":terms}; dedup={}; successful=0
    try:
        try:
            p=s.post(DISCOVERY,data={"searchYear":str(max(years)),"bplcNm":terms[0],"pageNo":"1"},timeout=(8,20)); p.raise_for_status()
        except Exception as e:
            status.update({"status":"REMOTE_HOST_UNREACHABLE","preflight_error":f"{type(e).__name__}: {e}"}); (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(status,ensure_ascii=False)); return 72
        for y in years:
            for term in terms:
                for page in range(1,max_pages+1):
                    status["requests"]+=1
                    try:
                        r=s.post(DISCOVERY,data={"searchYear":str(y),"bplcNm":term,"pageNo":str(page)},timeout=(8,25)); r.raise_for_status(); successful+=1
                    except Exception as e:
                        status["errors"]+=1; (out/"errors.log").open("a",encoding="utf-8").write(f"DISCOVERY\t{y}\t{term}\t{page}\t{type(e).__name__}\t{e}\n"); break
                    fn=safe(term); (raw/f"{y}_{fn}_p{page}.json").write_text(r.text,encoding="utf-8")
                    try: obj=r.json()
                    except Exception: break
                    rows=list(walk(obj))
                    if not rows: break
                    new=0
                    for row in rows:
                        bid=next((v for k,v in row.items() if str(k).lower()=="bplcid"),None)
                        if not bid: continue
                        key=(y,str(bid))
                        if key not in dedup: dedup[key]={"search_year":y,**row,"search_terms_hit":term}; new+=1
                        elif term not in str(dedup[key].get("search_terms_hit","")).split("|"): dedup[key]["search_terms_hit"]+="|"+term
                    if new==0 and page>1: break
                    time.sleep(float(cfg.get("request_delay_ms",80))/1000)
        rows=list(dedup.values())
        if rows:
            keys=sorted({k for r in rows for k in r})
            with (out/"discovery.csv").open("w",newline="",encoding="utf-8-sig") as f: w=csv.DictWriter(f,fieldnames=keys,extrasaction="ignore"); w.writeheader(); w.writerows(rows)
            with (out/"discovery.jsonl").open("w",encoding="utf-8") as f:
                for r in rows: f.write(json.dumps(r,ensure_ascii=False)+"\n")
        detail_ok=0; detail_fail=0; table_rows=[]
        if cfg.get("collect_details",True):
            for row in rows:
                y=row["search_year"]; bid=next((v for k,v in row.items() if str(k).lower()=="bplcid"),None); term=str(row.get("search_terms_hit","")).split("|")[0]
                try:
                    status["requests"]+=1
                    d=s.get(DETAIL,params=detail_params(y,bid,term),headers={"Referer":BASE+"/pageLink.do"},timeout=(8,25)); d.raise_for_status()
                    txt=d.text; (details/f"{y}_{safe(bid)}.html").write_text(txt,encoding="utf-8")
                    valid=(str(bid) in txt and len(txt)>5000)
                    if valid: detail_ok+=1; table_rows.extend(generic_tables(txt,y,bid))
                    else: detail_fail+=1
                except Exception as e:
                    detail_fail+=1; status["errors"]+=1; (out/"errors.log").open("a",encoding="utf-8").write(f"DETAIL\t{y}\t{bid}\t{type(e).__name__}\t{e}\n")
                time.sleep(float(cfg.get("request_delay_ms",80))/1000)
        with (out/"detail_table_rows.jsonl").open("w",encoding="utf-8") as f:
            for r in table_rows: f.write(json.dumps(r,ensure_ascii=False)+"\n")
        ids={next((v for k,v in r.items() if str(k).lower()=="bplcid"),None) for r in rows}
        status.update({"status":"DATA_FOUND" if rows else "NO_MATCH","rows":len(rows),"successful_responses":successful,"unique_bplc_ids":len(ids),"detail_ok":detail_ok,"detail_fail":detail_fail,"detail_table_rows":len(table_rows)})
    except Exception as e: status.update({"status":"REQUEST_OR_PARSE_FAILED","fatal_error":f"{type(e).__name__}: {e}"})
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(status,ensure_ascii=False))
    return 0 if status["status"] not in {"REQUEST_OR_PARSE_FAILED","REMOTE_HOST_UNREACHABLE"} else (72 if status["status"]=="REMOTE_HOST_UNREACHABLE" else 71)

if __name__=="__main__": sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "requests/current.json"))
