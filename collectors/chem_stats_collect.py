import csv, json, re, sys, time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    from .name_filter import matching_exclusion
except ImportError:
    from name_filter import matching_exclusion

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


def field_ci(row,name,default=""):
    target=name.lower()
    return next((v for k,v in row.items() if str(k).lower()==target),default)


def detail_params(year,bid,term=""):
    return {"searchAdres1Text":"","streNo":"","searchMttrWord":"","searchYear":str(year),"searchCategory":"","searchAdres2":"","bplcNm":term,"irsttList":"","pageNo":"1","bplcId":str(bid),"indutyCode2":"","indutyCode3":"","searchAdres2Text":"","mttrGroup":"","indutyCode4":""}


def generic_tables(html,year,bid):
    soup=BeautifulSoup(html,"html.parser"); rows=[]
    for ti,t in enumerate(soup.find_all("table")):
        for ri,tr in enumerate(t.find_all("tr")):
            cells=[x.get_text(" ",strip=True) for x in tr.find_all(["th","td"])]
            if cells: rows.append({"search_year":year,"bplcId":bid,"table_index":ti,"row_index":ri,"cells":cells})
    return rows


def substantive_detail(html,bid):
    """Return true only when a facility/year detail page contains real disclosed rows.

    ICIS returns the same page shell even for an invented/nonexistent bplcId.  Length
    and hidden bplcId therefore cannot validate a record.  A real disclosed survey
    record must contain at least one non-empty data row in the product/chemical tables
    (tables 3+ in the current source markup).
    """
    if str(bid) not in html:
        return False,0
    soup=BeautifulSoup(html,"html.parser"); count=0
    for table in soup.find_all("table")[2:]:
        for tr in table.find_all("tr"):
            tds=tr.find_all("td")
            if tds and any(td.get_text(" ",strip=True) for td in tds):
                count+=1
    return count>0,count


def write_jsonl(path,rows):
    with Path(path).open("w",encoding="utf-8") as f:
        for row in rows: f.write(json.dumps(row,ensure_ascii=False)+"\n")


def main(req_path):
    req=json.loads(Path(req_path).read_text(encoding="utf-8")); cfg=req.get("sources",{}).get("CHEM_STATS",{})
    years=sorted({int(x) for x in cfg.get("years",[2024])}); terms=cfg.get("search_terms") or [req.get("company_display_name","")]; max_pages=int(cfg.get("max_pages",10)); exclude_terms=cfg.get("exclude_terms",[])
    out=Path("output/CHEM_STATS"); raw=out/"raw_discovery"; details=out/"raw_detail"; raw.mkdir(parents=True,exist_ok=True); details.mkdir(parents=True,exist_ok=True)
    s=requests.Session(); s.headers.update({"User-Agent":UA,"X-Requested-With":"XMLHttpRequest","Accept":"application/json,text/javascript,*/*;q=0.01","Referer":BASE+"/pageLink.do"})
    status={"source_key":"CHEM_STATS","status":"RUNNING","requests":0,"errors":0,"years":years,"terms":terms}; dedup={}; successful=0; excluded_rows=[]
    detail_cache={}; backfill_audit=[]
    try:
        try:
            p=s.post(DISCOVERY,data={"searchYear":str(max(years)),"bplcNm":terms[0],"pageNo":"1"},timeout=(8,20)); p.raise_for_status()
        except Exception as e:
            status.update({"status":"REMOTE_HOST_UNREACHABLE","preflight_error":f"{type(e).__name__}: {e}"}); (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(status,ensure_ascii=False)); return 72

        # 1) Normal source-native name discovery for every disclosed survey round.
        for y in years:
            for term in cfg.get("search_terms_by_year",{}).get(str(y),terms):
                for page in range(1,max_pages+1):
                    status["requests"]+=1
                    try:
                        r=s.post(DISCOVERY,data={"searchYear":str(y),"bplcNm":term,"pageNo":str(page)},timeout=(8,25)); r.raise_for_status(); successful+=1
                    except Exception as e:
                        status["errors"]+=1; (out/"errors.log").open("a",encoding="utf-8").write(f"DISCOVERY\t{y}\t{term}\t{page}\t{type(e).__name__}\t{e}\n"); break
                    fn=safe(term); (raw/f"{y}_{fn}_p{page}.json").write_text(r.text,encoding="utf-8")
                    try: obj=r.json()
                    except Exception: break
                    found=list(walk(obj))
                    if not found: break
                    new=0
                    for source_row in found:
                        bid=field_ci(source_row,"bplcid",None)
                        if not bid: continue
                        exclusion=matching_exclusion(field_ci(source_row,"bplcnm",""),exclude_terms)
                        if exclusion:
                            excluded_rows.append({"search_year":y,"search_term":term,"excluded_by":exclusion,**source_row})
                            continue
                        key=(y,str(bid))
                        if key not in dedup:
                            dedup[key]={"search_year":y,**source_row,"search_terms_hit":term,"discovery_basis":"NAME_SEARCH"}; new+=1
                        elif term not in str(dedup[key].get("search_terms_hit","")).split("|"):
                            dedup[key]["search_terms_hit"]+="|"+term
                    if new==0 and page>1: break
                    time.sleep(float(cfg.get("request_delay_ms",80))/1000)

        normal_rows=len(dedup)

        # 2) Source-native ID backfill. Some ICIS rounds retain the facility's bplcId
        # and detailed chemical tables but omit the name metadata from name discovery.
        # Once a bplcId is discovered in any selected round, probe the same source ID
        # in other selected rounds. Only a populated detail table can create a row.
        # Identity labels/address remain explicitly anchored to the discovered round;
        # they are not represented as raw metadata from the hidden round.
        anchors={}
        for source_row in dedup.values():
            bid=str(field_ci(source_row,"bplcid","") or "")
            if not bid: continue
            prior=anchors.get(bid)
            if prior is None or int(source_row["search_year"])>int(prior["search_year"]): anchors[bid]=source_row

        if cfg.get("source_native_id_backfill",True):
            for bid,anchor in sorted(anchors.items()):
                for y in years:
                    if (y,bid) in dedup: continue
                    status["requests"]+=1
                    try:
                        d=s.get(DETAIL,params=detail_params(y,bid,""),headers={"Referer":BASE+"/pageLink.do"},timeout=(8,25)); d.raise_for_status()
                        txt=d.text; valid,data_rows=substantive_detail(txt,bid)
                        audit={"search_year":y,"bplcId":bid,"identity_anchor_year":anchor.get("search_year"),"identity_anchor_bplcNm":field_ci(anchor,"bplcnm",""),"identity_anchor_locplcAdres":field_ci(anchor,"locplcadres",""),"query_status":"DATA_PRESENT" if valid else "NO_DATA_CONFIRMED","substantive_rows":data_rows,"http_status":d.status_code}
                        backfill_audit.append(audit)
                        if valid:
                            target=details/f"{y}_{safe(bid)}.html"; target.write_text(txt,encoding="utf-8"); detail_cache[(y,bid)]=txt
                            dedup[(y,bid)]={
                                "search_year":y,"bplcId":bid,"bplcNm":"","locplcAdres":"",
                                "search_terms_hit":"SOURCE_NATIVE_ID_BACKFILL","discovery_basis":"SOURCE_NATIVE_ID_BACKFILL",
                                "identity_anchor_year":anchor.get("search_year"),
                                "identity_anchor_bplcNm":field_ci(anchor,"bplcnm",""),
                                "identity_anchor_locplcAdres":field_ci(anchor,"locplcadres",""),
                                "source_identity_evidence":"same source-native bplcId disclosed in another selected survey round; hidden-round detail contains substantive tables"
                            }
                    except Exception as e:
                        status["errors"]+=1
                        backfill_audit.append({"search_year":y,"bplcId":bid,"identity_anchor_year":anchor.get("search_year"),"query_status":"QUERY_FAILED","error":f"{type(e).__name__}: {e}"})
                        (out/"errors.log").open("a",encoding="utf-8").write(f"ID_BACKFILL\t{y}\t{bid}\t{type(e).__name__}\t{e}\n")
                    time.sleep(float(cfg.get("request_delay_ms",80))/1000)

        rows=list(dedup.values())
        if rows:
            keys=sorted({k for r in rows for k in r})
            with (out/"discovery.csv").open("w",newline="",encoding="utf-8-sig") as f: w=csv.DictWriter(f,fieldnames=keys,extrasaction="ignore"); w.writeheader(); w.writerows(rows)
            write_jsonl(out/"discovery.jsonl",rows)
        write_jsonl(out/"excluded_rows.jsonl",excluded_rows)
        write_jsonl(out/"source_id_backfill_audit.jsonl",backfill_audit)

        # 3) Collect/validate the actual detail artifact for every discovered or
        # source-ID-backfilled facility-round. The same substantive-table validation
        # is used here, so a generic empty ICIS shell cannot count as success.
        detail_ok=0; detail_fail=0; table_rows=[]
        if cfg.get("collect_details",True):
            for source_row in rows:
                y=int(source_row["search_year"]); bid=str(field_ci(source_row,"bplcid",None) or source_row.get("bplcId") or ""); term=str(source_row.get("search_terms_hit","")).split("|")[0]
                try:
                    txt=detail_cache.get((y,bid))
                    if txt is None:
                        status["requests"]+=1
                        d=s.get(DETAIL,params=detail_params(y,bid,"" if term=="SOURCE_NATIVE_ID_BACKFILL" else term),headers={"Referer":BASE+"/pageLink.do"},timeout=(8,25)); d.raise_for_status(); txt=d.text
                        (details/f"{y}_{safe(bid)}.html").write_text(txt,encoding="utf-8")
                    valid,_=substantive_detail(txt,bid)
                    if valid: detail_ok+=1; table_rows.extend(generic_tables(txt,y,bid))
                    else:
                        detail_fail+=1; (out/"errors.log").open("a",encoding="utf-8").write(f"DETAIL_INVALID\t{y}\t{bid}\tempty_or_shell_response\n")
                except Exception as e:
                    detail_fail+=1; status["errors"]+=1; (out/"errors.log").open("a",encoding="utf-8").write(f"DETAIL\t{y}\t{bid}\t{type(e).__name__}\t{e}\n")
                time.sleep(float(cfg.get("request_delay_ms",80))/1000)

        write_jsonl(out/"detail_table_rows.jsonl",table_rows)
        ids={str(field_ci(r,"bplcid","") or r.get("bplcId") or "") for r in rows}
        status.update({
            "status":"DATA_FOUND" if rows else "NO_MATCH","rows":len(rows),"normal_discovery_rows":normal_rows,
            "source_id_backfill_attempts":len(backfill_audit),"source_id_backfill_rows":sum(1 for r in backfill_audit if r.get("query_status")=="DATA_PRESENT"),
            "source_id_no_data_confirmed":sum(1 for r in backfill_audit if r.get("query_status")=="NO_DATA_CONFIRMED"),
            "source_id_backfill_failed":sum(1 for r in backfill_audit if r.get("query_status")=="QUERY_FAILED"),
            "successful_responses":successful,"excluded_rows":len(excluded_rows),"unique_bplc_ids":len({x for x in ids if x}),
            "detail_ok":detail_ok,"detail_fail":detail_fail,"detail_table_rows":len(table_rows)
        })
    except Exception as e: status.update({"status":"REQUEST_OR_PARSE_FAILED","fatal_error":f"{type(e).__name__}: {e}"})
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(status,ensure_ascii=False))
    return 0 if status["status"] not in {"REQUEST_OR_PARSE_FAILED","REMOTE_HOST_UNREACHABLE"} else (72 if status["status"]=="REMOTE_HOST_UNREACHABLE" else 71)

if __name__=="__main__": sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "requests/current.json"))
