import csv, json, math, re, sys, time
from pathlib import Path

import requests

BASE="https://www.env-info.kr"
SEARCH_PAGE=BASE+"/member/open/companyTotalInfoSearch.do"
SEARCH=BASE+"/member/open/retrieveDoc.do"
DETAIL=BASE+"/user/register/viewUserSearch2.do"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"


def safe(x): return re.sub(r"[^0-9A-Za-z가-힣._-]+","_",str(x)).strip("_")

def search_payload(y1,y2,term,page,page_size):
    param={"year":str(y1),"year2":str(y2),"compNm":term,"codeOrders":"","compNmOrders":"","yearOrders":"","firstOrder":"yearOrdersArea"}
    return {"mapData":json.dumps(param,ensure_ascii=False),"currentIndex":str(page),"pageSize":str(page_size),"pageCnt":"10","orderBy":"","baseOrderBy":""}

def rows_from_column_json(d):
    keys=[k for k,v in d.items() if isinstance(v,list)]
    n=max([len(d[k]) for k in keys]+[0])
    rows=[]
    for i in range(n):
        r={k:(d[k][i] if i<len(d[k]) else None) for k in keys if k not in {"totalRows"}}
        if r.get("compId"): rows.append(r)
    return rows

def main(req_path):
    req=json.loads(Path(req_path).read_text(encoding="utf-8")); cfg=req.get("sources",{}).get("ENVINFO",{})
    y1=int(cfg.get("start_year",cfg.get("proof_year",2024))); y2=int(cfg.get("end_year",cfg.get("proof_year",2024)))
    terms=cfg.get("search_terms") or [cfg.get("search_term",req.get("company_display_name",""))]
    page_size=int(cfg.get("page_size",200)); collect_details=bool(cfg.get("collect_details",True)); max_details=int(cfg.get("max_details",30))
    out=Path("output/ENVINFO"); raw=out/"raw_search"; details=out/"raw_detail"; raw.mkdir(parents=True,exist_ok=True); details.mkdir(parents=True,exist_ok=True)
    s=requests.Session(); s.headers.update({"User-Agent":UA})
    status={"source_key":"ENVINFO","status":"RUNNING","year_start":y1,"year_end":y2,"terms":terms,"requests":0,"errors":0}
    dedup={}
    try:
        p=s.get(SEARCH_PAGE,timeout=(5,12)); p.raise_for_status(); (out/"search_page_raw.html").write_text(p.text,encoding="utf-8")
        for term in terms:
            page=1; total=None
            while True:
                status["requests"]+=1
                r=s.post(SEARCH,data=search_payload(y1,y2,term,page,page_size),headers={"Referer":SEARCH_PAGE,"X-Requested-With":"XMLHttpRequest"},timeout=(5,20)); r.raise_for_status()
                (raw/f"{y1}_{y2}_{safe(term)}_p{page}.json").write_text(r.text,encoding="utf-8")
                d=r.json(); rows=rows_from_column_json(d)
                if total is None:
                    tr=d.get("totalRows",[len(rows)]); total=int(tr[0]) if isinstance(tr,list) and tr else len(rows)
                for row in rows:
                    key=(str(row.get("year","")),str(row.get("compId","")))
                    if key not in dedup:
                        row["search_terms_hit"]=term; dedup[key]=row
                    elif term not in dedup[key]["search_terms_hit"].split("|"):
                        dedup[key]["search_terms_hit"]+="|"+term
                if page*page_size>=total or not rows: break
                page+=1
        rows=list(dedup.values())
        all_keys=sorted({k for r in rows for k in r})
        if rows:
            with (out/"discovery.csv").open("w",newline="",encoding="utf-8-sig") as f:
                w=csv.DictWriter(f,fieldnames=all_keys); w.writeheader(); w.writerows(rows)
            with (out/"discovery.jsonl").open("w",encoding="utf-8") as f:
                for r in rows: f.write(json.dumps(r,ensure_ascii=False)+"\n")
        detail_ok=0; detail_fail=0
        if collect_details:
            for row in rows[:max_details]:
                year=str(row.get("year")); comp=str(row.get("compId")); name=str(row.get("compNm",""))
                try:
                    status["requests"]+=1
                    rr=s.get(DETAIL,params={"YEAR":year,"COMP_ID":comp,"OPEN_YN":"Y"},headers={"Referer":SEARCH_PAGE},timeout=(5,20)); rr.raise_for_status()
                    fn=f"{year}_{safe(comp)}_{safe(name)[:60]}.html"; (details/fn).write_text(rr.text,encoding="utf-8")
                    if len(rr.text)>10000: detail_ok+=1
                    else: detail_fail+=1
                except Exception as e:
                    detail_fail+=1; status["errors"]+=1
                    (out/"errors.log").open("a",encoding="utf-8").write(f"DETAIL\t{year}\t{comp}\t{e}\n")
                time.sleep(float(cfg.get("request_delay_ms",80))/1000)
        status.update({"status":"DATA_FOUND" if rows else "NO_MATCH","rows":len(rows),"unique_comp_ids":len({r.get('compId') for r in rows}),"detail_ok":detail_ok,"detail_fail":detail_fail})
    except Exception as e:
        status.update({"status":"REQUEST_OR_PARSE_FAILED","fatal_error":f"{type(e).__name__}: {e}"})
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(status,ensure_ascii=False))
    return 0 if status["status"]!="REQUEST_OR_PARSE_FAILED" else 61

if __name__=="__main__": sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "requests/current.json"))
