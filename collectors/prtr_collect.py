import csv, json, re, sys, time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://icis.mcee.go.kr"
SEARCH = BASE + "/prtr/prtrInfo/entrpsSearch.do"
DETAIL = BASE + "/prtr/prtrInfo/entrpsDetailPopup.do"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"


def session():
    s=requests.Session()
    r=Retry(total=2,connect=2,read=2,backoff_factor=0.8,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset(["POST"]))
    s.mount("https://",HTTPAdapter(max_retries=r))
    s.headers.update({"User-Agent":UA,"Accept":"text/html,application/xhtml+xml,*/*;q=0.8"})
    return s

def norm_addr(x):
    x=re.sub(r"[\s()\[\]{},.·ㆍ\-_/\\]","",x or "").lower()
    return re.sub(r"특별자치도|특별자치시|광역시|특별시|경기도|충청북도|충청남도|전라북도|전북특별자치도|전라남도|경상북도|경상남도","",x)

def match_sites(addr,anchors):
    a=norm_addr(addr); hits=[]
    for sid,vals in (anchors or {}).items():
        if any(norm_addr(v) and norm_addr(v) in a for v in vals): hits.append(sid)
    return sorted(set(hits))

def parse_rows(html):
    soup=BeautifulSoup(html,"html.parser"); out=[]
    for tr in soup.find_all("tr"):
        a=tr.find("a",onclick=re.compile(r"fnEntrpsDetail\s*\(",re.I))
        if not a: continue
        m=re.search(r"fnEntrpsDetail\s*\(\s*['\"]([^'\"]+)['\"]",a.get("onclick","") or "",re.I)
        vals=[td.get_text(" ",strip=True) for td in tr.find_all("td")]
        if not m or len(vals)<3: continue
        out.append({"entrps_id":m.group(1),"company_name_raw":a.get_text(" ",strip=True),"address_raw":vals[2],"release_total_raw":vals[3] if len(vals)>3 else "","self_landfill_raw":vals[4] if len(vals)>4 else "","transfer_total_raw":vals[5] if len(vals)>5 else ""})
    return out

def form(year,term,page=1,area=""):
    return {"pageIndex":str(page),"sortColumn":"","sortOrder":"","searchIndutyCode":"","searchIndutyCode2":"","searchIndutyCode3":"","searchIndutyCode4":"","searchIndutyConditonCount":"1","searchYearCheck":str(year),"searchIndutyNm":"","searchIndutyFullNm":"","searchAreaNm1":"","searchAreaNm2":"","searchMttrNm":"","clCode":"2","queryName":"","entrpsId":"","induty":"","indutyTxt":"","mttr":"","nwdSe":"","searchYear":str(year),"searchArea1":area,"searchArea2":"","searchMttr":"","searchEntrpsNm":term,"searchInduty":"","searchInduty2":"","searchInduty3":"","searchInduty4":""}

def table_rows(html,year,eid):
    soup=BeautifulSoup(html,"html.parser"); out=[]
    for ti,t in enumerate(soup.find_all("table")):
        for ri,tr in enumerate(t.find_all("tr")):
            cells=[x.get_text(" ",strip=True) for x in tr.find_all(["th","td"])]
            if cells: out.append({"search_year":year,"entrps_id":eid,"table_index":ti,"row_index":ri,"cells":cells})
    return out

def write_status(out,status):
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(status,ensure_ascii=False))

def main(req_path):
    req=json.loads(Path(req_path).read_text(encoding="utf-8")); cfg=req["sources"]["PRTR"]
    out=Path("output/PRTR"); raw=out/"raw_search"; details=out/"raw_detail"; raw.mkdir(parents=True,exist_ok=True); details.mkdir(parents=True,exist_ok=True)
    status={"source_key":"PRTR","status":"RUNNING","requests":0,"errors":0,"rows":0}
    start=int(cfg.get("start_year",2018)); end=cfg.get("end_year")
    if end in (None,"auto"): status.update({"status":"CONFIG_ERROR","fatal_error":"end_year must be resolved"}); write_status(out,status); return 20
    end=int(end); years=list(range(start,end+1)); first_term=cfg["search_terms"][0]["term"]
    try:
        r0=requests.post(SEARCH,data=form(end,first_term,1),headers={"User-Agent":UA,"Referer":SEARCH},timeout=(8,20)); r0.raise_for_status()
    except Exception as e:
        status.update({"status":"REMOTE_HOST_UNREACHABLE","preflight_error":f"{type(e).__name__}: {e}"}); write_status(out,status); return 22
    s=session(); dedup={}; successful=0
    try:
        for spec in cfg["search_terms"]:
            ys=int(spec.get("year_start",start)); ye=spec.get("year_end",end); ye=end if ye=="auto" else int(ye); term=spec["term"]
            for y in [x for x in years if ys<=x<=ye]:
                for page in range(1,int(cfg.get("max_pages",50))+1):
                    status["requests"]+=1
                    try:
                        r=s.post(SEARCH,data=form(y,term,page),headers={"Referer":SEARCH},timeout=(8,20)); r.raise_for_status(); successful+=1
                    except Exception as e:
                        status["errors"]+=1; (out/"errors.log").open("a",encoding="utf-8").write(f"SEARCH\t{y}\t{term}\t{page}\t{type(e).__name__}\t{e}\n"); break
                    fn=re.sub(r"[^0-9A-Za-z가-힣]+","_",term).strip("_"); (raw/f"{y}_{fn}_p{page}.html").write_text(r.text,encoding="utf-8")
                    rs=parse_rows(r.text)
                    if not rs: break
                    for row in rs:
                        hits=match_sites(row["address_raw"],cfg.get("site_address_anchors",{})); key=(y,row["entrps_id"])
                        if key not in dedup: dedup[key]={"search_year":y,**row,"proposed_site_ids":"|".join(hits),"search_terms_hit":term,"match_status":"ADDRESS_CANDIDATE" if len(hits)==1 else ("REVIEW_REQUIRED" if len(hits)>1 else "UNRESOLVED"),"source_url":SEARCH}
                        elif term not in dedup[key]["search_terms_hit"].split("|"): dedup[key]["search_terms_hit"]+="|"+term
                    time.sleep(float(cfg.get("request_delay_ms",80))/1000)
        rows=list(dedup.values()); cols=["search_year","entrps_id","company_name_raw","address_raw","release_total_raw","self_landfill_raw","transfer_total_raw","proposed_site_ids","search_terms_hit","match_status","source_url"]
        with (out/"discovery.csv").open("w",newline="",encoding="utf-8-sig") as f: w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(rows)
        detail_ok=0; detail_fail=0; flat=[]
        if cfg.get("collect_details",True):
            for row in rows:
                y=row["search_year"]; eid=row["entrps_id"]
                try:
                    status["requests"]+=1
                    d=s.post(DETAIL,data={"pageIndex":"1","entrpsId":eid,"reportYear":str(y),"searchYear":str(y)},headers={"Referer":SEARCH},timeout=(8,25)); d.raise_for_status()
                    txt=d.text; (details/f"{y}_{eid}.html").write_text(txt,encoding="utf-8")
                    valid=(str(eid) in txt and len(txt)>5000)
                    if valid: detail_ok+=1; flat.extend(table_rows(txt,y,eid))
                    else: detail_fail+=1
                except Exception as e:
                    detail_fail+=1; status["errors"]+=1; (out/"errors.log").open("a",encoding="utf-8").write(f"DETAIL\t{y}\t{eid}\t{type(e).__name__}\t{e}\n")
                time.sleep(float(cfg.get("request_delay_ms",80))/1000)
        with (out/"detail_table_rows.jsonl").open("w",encoding="utf-8") as f:
            for r in flat: f.write(json.dumps(r,ensure_ascii=False)+"\n")
        status.update({"status":"DATA_FOUND" if rows else "NO_MATCH","rows":len(rows),"years":years,"successful_responses":successful,"detail_ok":detail_ok,"detail_fail":detail_fail,"detail_table_rows":len(flat)})
    except Exception as e: status.update({"status":"REQUEST_OR_PARSE_FAILED","fatal_error":repr(e)})
    write_status(out,status); return 21 if status["status"] in {"REQUEST_OR_PARSE_FAILED","REMOTE_HOST_UNREACHABLE"} else 0

if __name__=="__main__": sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "requests/current.json"))
