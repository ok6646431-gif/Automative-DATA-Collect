import csv, json, re, sys, time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://icis.mcee.go.kr"
SEARCH = BASE + "/prtr/prtrInfo/entrpsSearch.do"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36"


def session():
    s = requests.Session()
    r = Retry(total=3, connect=3, read=3, backoff_factor=1.0,
              status_forcelist=(429,500,502,503,504), allowed_methods=frozenset(["GET","POST"]))
    s.mount("https://", HTTPAdapter(max_retries=r))
    s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    return s


def norm_addr(x):
    x = re.sub(r"[\s()\[\]{},.·ㆍ\-_/\\]", "", x or "").lower()
    x = re.sub(r"특별자치도|특별자치시|광역시|특별시|경기도|충청북도|충청남도|전라북도|전북특별자치도|전라남도|경상북도|경상남도", "", x)
    return x


def match_sites(addr, anchors):
    a = norm_addr(addr)
    hits=[]
    for sid, vals in (anchors or {}).items():
        for v in vals:
            nv=norm_addr(v)
            if nv and nv in a:
                hits.append(sid); break
    return sorted(set(hits))


def parse_rows(html):
    soup=BeautifulSoup(html,"html.parser")
    out=[]
    for tr in soup.find_all("tr"):
        a=tr.find("a", href=re.compile(r"fnEntrpsDetail"))
        if not a: continue
        href=a.get("href","")
        m=re.search(r"fnEntrpsDetail\(['\"]([^'\"]+)",href)
        if not m: continue
        tds=tr.find_all("td")
        vals=[td.get_text(" ",strip=True) for td in tds]
        if len(vals)<3: continue
        out.append({
            "entrps_id":m.group(1),
            "company_name_raw":a.get_text(" ",strip=True),
            "address_raw":vals[2] if len(vals)>2 else "",
            "release_total_raw":vals[3] if len(vals)>3 else "",
            "self_landfill_raw":vals[4] if len(vals)>4 else "",
            "transfer_total_raw":vals[5] if len(vals)>5 else "",
        })
    return out


def form(year, term, page=1, area=""):
    return {
      "pageIndex":str(page),"sortColumn":"","sortOrder":"",
      "searchIndutyCode":"","searchIndutyCode2":"","searchIndutyCode3":"","searchIndutyCode4":"",
      "searchIndutyConditonCount":"1","searchYearCheck":str(year),
      "searchIndutyNm":"","searchIndutyFullNm":"","searchAreaNm1":"","searchAreaNm2":"","searchMttrNm":"",
      "clCode":"2","queryName":"","entrpsId":"","induty":"","indutyTxt":"","mttr":"","nwdSe":"",
      "searchYear":str(year),"searchArea1":area,"searchArea2":"","searchMttr":"",
      "searchEntrpsNm":term,"searchInduty":"","searchInduty2":"","searchInduty3":"","searchInduty4":""
    }


def main(req_path):
    req=json.loads(Path(req_path).read_text(encoding="utf-8"))
    cfg=req["sources"]["PRTR"]
    out=Path("output/PRTR"); raw=out/"raw_html"; raw.mkdir(parents=True,exist_ok=True)
    s=session()
    status={"source_key":"PRTR","status":"RUNNING","requests":0,"errors":0,"rows":0}
    try:
        g=s.get(SEARCH,timeout=30); g.raise_for_status()
        years=sorted(set(int(x) for x in re.findall(r'<option\s+value="(20\d{2})"',g.text)))
        start=int(cfg.get("start_year",2018)); end=cfg.get("end_year","auto")
        if not years: years=list(range(start,2025))
        years=[y for y in years if y>=start]
        if end!="auto": years=[y for y in years if y<=int(end)]
        dedup={}
        for spec in cfg["search_terms"]:
            ys=int(spec.get("year_start",start)); ye=spec.get("year_end","auto")
            ye=max(years) if ye=="auto" else int(ye)
            term=spec["term"]
            for y in [x for x in years if ys<=x<=ye]:
                empty_streak=0
                for page in range(1,int(cfg.get("max_pages",50))+1):
                    status["requests"]+=1
                    try:
                        r=s.post(SEARCH,data=form(y,term,page),headers={"Referer":SEARCH},timeout=30)
                        r.raise_for_status()
                    except Exception as e:
                        status["errors"]+=1
                        (out/"errors.log").open("a",encoding="utf-8").write(f"{y}\t{term}\t{page}\t{e}\n")
                        break
                    safe=re.sub(r"[^0-9A-Za-z가-힣]+","_",term).strip("_")
                    (raw/f"{y}_{safe}_p{page}.html").write_text(r.text,encoding="utf-8")
                    rows=parse_rows(r.text)
                    if not rows:
                        empty_streak+=1
                        if empty_streak>=1: break
                    else: empty_streak=0
                    for row in rows:
                        hits=match_sites(row["address_raw"],cfg.get("site_address_anchors",{}))
                        key=(y,row["entrps_id"])
                        if key not in dedup:
                            dedup[key]={"search_year":y,**row,"proposed_site_ids":"|".join(hits),"search_terms_hit":term,
                                        "match_status":"ADDRESS_CANDIDATE" if len(hits)==1 else ("REVIEW_REQUIRED" if len(hits)>1 else "UNRESOLVED"),
                                        "source_url":SEARCH}
                        else:
                            old=dedup[key]
                            old["search_terms_hit"]="|".join(sorted(set(old["search_terms_hit"].split("|")+[term])))
                    time.sleep(float(cfg.get("request_delay_ms",150))/1000)
        rows=list(dedup.values())
        cols=["search_year","entrps_id","company_name_raw","address_raw","release_total_raw","self_landfill_raw","transfer_total_raw","proposed_site_ids","search_terms_hit","match_status","source_url"]
        with (out/"discovery.csv").open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(rows)
        status.update({"status":"DATA_FOUND" if rows else "NO_MATCH","rows":len(rows),"years":years})
    except Exception as e:
        status.update({"status":"REQUEST_OR_PARSE_FAILED","fatal_error":repr(e)})
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(status,ensure_ascii=False))
    if status["status"]=="REQUEST_OR_PARSE_FAILED": sys.exit(21)

if __name__=="__main__":
    main(sys.argv[1] if len(sys.argv)>1 else "requests/current.json")
