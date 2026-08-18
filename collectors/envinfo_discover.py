import json, re, sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE="https://www.env-info.kr"
PAGE=BASE+"/member/open/companyTotalInfoSearch.do"
SEARCH=BASE+"/member/open/retrieveDoc.do"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"


def save(p,text):
    p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text,encoding="utf-8")


def main(req_path):
    req=json.loads(Path(req_path).read_text(encoding="utf-8"))
    cfg=req.get("sources",{}).get("ENVINFO",{})
    term=cfg.get("search_term",req.get("company_display_name",""))
    year=str(cfg.get("proof_year",2024))
    out=Path("output/ENVINFO"); out.mkdir(parents=True,exist_ok=True)
    s=requests.Session(); s.headers.update({"User-Agent":UA})
    status={"source_key":"ENVINFO","status":"RUNNING","term":term,"year":year}
    try:
        r=s.get(PAGE,timeout=(5,12)); r.raise_for_status(); save(out/"search_page_raw.html",r.text)
        soup=BeautifulSoup(r.text,"html.parser")
        helper_hits=[]
        for src in [x.get("src") for x in soup.find_all("script") if x.get("src")]:
            u=urljoin(PAGE,src)
            try:
                rr=s.get(u,timeout=(4,10)); rr.raise_for_status()
                if "getDataDSPage" in rr.text:
                    fn=re.sub(r"[^0-9A-Za-z._-]+","_",src.split("/")[-1].split("?")[0] or "helper.js")
                    save(out/("helper_"+fn),rr.text)
                    helper_hits.append({"url":u,"bytes":len(rr.content),"file":"helper_"+fn})
            except Exception:
                pass

        param={"year":year,"year2":year,"compNm":term,"codeOrders":"","compNmOrders":"","yearOrders":"","firstOrder":"yearOrdersArea"}
        pageinfo={"currentIndex":"1","pageSize":"200","pageCnt":"10","orderBy":"","baseOrderBy":""}
        attempts=[
            ("form_map_page_fields",{"data":{"mapData":json.dumps(param,ensure_ascii=False),**pageinfo}}),
            ("form_map_pageinfo",{"data":{"mapData":json.dumps(param,ensure_ascii=False),"pageInfo":json.dumps(pageinfo,ensure_ascii=False)}}),
            ("form_flat",{"data":{**param,**pageinfo}}),
            ("json_nested",{"json":{"mapData":param,"pageInfo":pageinfo}}),
        ]
        found=[]; metas=[]
        for name,kwargs in attempts:
            try:
                rr=s.post(SEARCH,headers={"Referer":PAGE,"X-Requested-With":"XMLHttpRequest"},timeout=(5,15),**kwargs)
                text=rr.text; save(out/f"retrieve_{name}_raw.txt",text)
                hit=(term in text) or ("compId" in text and len(text)>100)
                metas.append({"attempt":name,"status_code":rr.status_code,"bytes":len(rr.content),"content_type":rr.headers.get("content-type"),"hit":hit})
                if hit: found.append(name)
            except Exception as e:
                metas.append({"attempt":name,"error":f"{type(e).__name__}: {e}"})
        (out/"attempts.json").write_text(json.dumps(metas,ensure_ascii=False,indent=2),encoding="utf-8")
        status.update({"status":"SEARCH_RESPONSE_FOUND" if found else "PAGE_AND_HELPER_CAPTURED","helper_hits":helper_hits,"successful_search_attempts":found,"attempts":metas})
    except Exception as e:
        status.update({"status":"REQUEST_OR_PARSE_FAILED","error":f"{type(e).__name__}: {e}"})
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(status,ensure_ascii=False))
    return 0 if status["status"]!="REQUEST_OR_PARSE_FAILED" else 51

if __name__=="__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "requests/current.json"))
