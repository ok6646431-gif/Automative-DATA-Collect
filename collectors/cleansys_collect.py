import json, re, sys, warnings
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning

try:
    from .name_filter import matching_exclusion
except ImportError:
    from name_filter import matching_exclusion

BASE="https://cleansys.or.kr"; INDEX=BASE+"/index.do"; ANNUAL=BASE+"/apiService/selectAnnualResult.do"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
LEGAL_PATTERNS=[r"\(주\)",r"㈜",r"주식회사",r"유한회사",r"\(유\)"]


def normalize_company_text(value):
    """Normalize spelling/layout differences without inventing fuzzy aliases."""
    text=str(value or "")
    for pat in LEGAL_PATTERNS:
        text=re.sub(pat,"",text,flags=re.I)
    return re.sub(r"[^0-9A-Za-z가-힣]","",text).lower()


def term_matches_option(term,name):
    t=normalize_company_text(term); n=normalize_company_text(name)
    return bool(t and n and t in n)


def main(req_path):
    req=json.loads(Path(req_path).read_text(encoding="utf-8")); cfg=req.get("sources",{}).get("CLEANSYS_AIR",{})
    terms=cfg.get("search_terms",[req.get("company_display_name","")]); exclude_terms=cfg.get("exclude_terms",[]); y1=int(cfg.get("start_year",2015)); y2=int(cfg.get("end_year",2025))
    out=Path("output/CLEANSYS_AIR"); raw=out/"raw_annual"; raw.mkdir(parents=True,exist_ok=True)
    status={"source_key":"CLEANSYS_AIR","status":"RUNNING","tls_mode":"VERIFY_FIRST_THEN_LOGGED_SOURCE_EXCEPTION"}
    verify=True; tls_error=None
    try:
        try:
            r=requests.get(INDEX,headers={"User-Agent":UA},timeout=(5,10),verify=True); r.raise_for_status()
        except requests.exceptions.SSLError as e:
            tls_error=str(e); verify=False; warnings.simplefilter("ignore",InsecureRequestWarning)
            r=requests.get(INDEX,headers={"User-Agent":UA},timeout=(5,10),verify=False); r.raise_for_status()
        (out/"index_raw.html").write_text(r.text,encoding="utf-8")
        soup=BeautifulSoup(r.text,"html.parser"); candidates=[]; excluded_candidates=[]
        for opt in soup.find_all("option"):
            name=opt.get_text(" ",strip=True); fact=(opt.get("value") or "").strip()
            if not fact or not any(term_matches_option(t,name) for t in terms):
                continue
            exclusion=matching_exclusion(name,exclude_terms)
            row={"fact_code":fact,"company_name_raw":name}
            if exclusion:
                excluded_candidates.append({**row,"excluded_by":exclusion})
            else:
                candidates.append(row)
        seen=set(); candidates=[x for x in candidates if not ((x["fact_code"],x["company_name_raw"]) in seen or seen.add((x["fact_code"],x["company_name_raw"])))]
        seen_ex=set(); excluded_candidates=[x for x in excluded_candidates if not ((x["fact_code"],x["company_name_raw"],x["excluded_by"]) in seen_ex or seen_ex.add((x["fact_code"],x["company_name_raw"],x["excluded_by"])))]
        rows=[]; errors=[]
        headers={"User-Agent":UA,"Referer":BASE+"/statAnnual.do","Content-Type":"application/x-www-form-urlencoded; charset=UTF-8","Accept":"application/json,text/plain,*/*"}
        for c in candidates:
            try:
                ra=requests.post(ANNUAL,data={"s_year":str(y1),"e_year":str(y2),"selectArea":"","selectComp":"","selectCompDrop":c["fact_code"],"selectOrder":"","type":"json"},headers=headers,timeout=(5,15),verify=verify); ra.raise_for_status()
                fn=re.sub(r"[^0-9A-Za-z가-힣]+","_",c["company_name_raw"]).strip("_")
                (raw/f"{c['fact_code']}_{fn}.json").write_text(ra.text,encoding="utf-8")
                obj=ra.json(); rr=obj.get("ResultList",[]) if isinstance(obj,dict) else []
                for row in rr:
                    z=dict(row); z["source_fact_code"]=c["fact_code"]; z["source_candidate_name"]=c["company_name_raw"]; rows.append(z)
            except Exception as e: errors.append({**c,"error":f"{type(e).__name__}: {e}"})
        (out/"candidates.json").write_text(json.dumps(candidates,ensure_ascii=False,indent=2),encoding="utf-8")
        (out/"excluded_candidates.json").write_text(json.dumps(excluded_candidates,ensure_ascii=False,indent=2),encoding="utf-8")
        with (out/"annual_rows.jsonl").open("w",encoding="utf-8") as f:
            for row in rows: f.write(json.dumps(row,ensure_ascii=False)+"\n")
        status.update({"status":"DATA_FOUND" if rows else ("RESPONSE_OK_NO_TERM_MATCH" if not candidates else "REQUEST_OR_PARSE_FAILED"),"candidate_count":len(candidates),"excluded_candidates":len(excluded_candidates),"annual_rows":len(rows),"annual_years":sorted({str(r.get('examin_year')) for r in rows}),"errors":errors,"tls_verification":verify,"tls_verification_exception":tls_error})
    except Exception as e: status.update({"status":"REQUEST_OR_PARSE_FAILED","fatal_error":f"{type(e).__name__}: {e}"})
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(status,ensure_ascii=False))
    return 0 if status["status"]!="REQUEST_OR_PARSE_FAILED" else 41

if __name__=="__main__": sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "requests/current.json"))
