import csv, hashlib, json, re, sys, time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE="https://www.env-info.kr"
SEARCH_PAGE=BASE+"/member/open/companyTotalInfoSearch.do"
SEARCH=BASE+"/member/open/retrieveDoc.do"
DETAIL=BASE+"/user/register/viewUserSearch2.do"
DOWNLOAD=BASE+"/user/register/downloadFile.do"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
ATTACHMENT_FIELDS=[
    "year","compId","compNm","section_id","section_title","file_id","file_ext","original_filename",
    "stored_path","source_locator","bytes","sha256","content_type","importance","document_category",
    "context_text","collection_status","error"
]
MAX_ATTACHMENT_BYTES=100*1024*1024
MAX_ATTACHMENT_TOTAL_BYTES=500*1024*1024


def safe(x): return re.sub(r"[^0-9A-Za-z가-힣._-]+","_",str(x)).strip("_")

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

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

def classify_text(text):
    text=str(text or "").lower()
    if any(k in text for k in ["수료증","서명지","참석자","참석 명단"]):
        return "CERTIFICATION_EVIDENCE","EVIDENCE_ONLY"
    if any(k in text for k in ["내부심사","내부 심사","자체점검","점검보고","감사 결과"]):
        return "INTERNAL_AUDIT","CORE"
    if any(k in text for k in ["조직도","전담조직","업무.역할.권한","업무·역할·권한","업무 역할 권한","업무분장","책임과 권한"]):
        return "ORGANIZATION_ROLE","CORE"
    if any(k in text for k in ["비상대응","사고대응","대응체계","비상사태","유누출","유·누출","누출 대응"]):
        return "EMERGENCY_RESPONSE","CORE"
    if any(k in text for k in ["환경목표","환경 목표","환경방침","환경 방침","환경경영시스템","환경경영 시스템","환경안전보건방침","녹색경영 목표","녹색경영 비전","녹색경영 전략","목표관리"]):
        return "ENV_POLICY_GOAL","CORE"
    if any(k in text for k in ["유해화학물질","화학물질관리","화학물질 관리","msds"]):
        return "CHEMICAL_MANAGEMENT","SUPPORTING"
    if any(k in text for k in ["교육","워크숍","훈련"]):
        return "EDUCATION_TRAINING","SUPPORTING"
    return None

def classify_attachment(filename,context="",section_title=""):
    # File names are the strongest classification signal. Section/context is fallback only.
    for text in [filename, f"{section_title} {context}"]:
        result=classify_text(text)
        if result: return result
    return "OTHER_ENVINFO_EVIDENCE","SUPPORTING"

def section_titles(soup):
    out={}
    for a in soup.find_all("a",href=True):
        href=str(a.get("href") or "")
        if re.fullmatch(r"#inquiry\d+",href):
            out[href[1:]]=" ".join(a.stripped_strings)
    return out

def extract_attachments(html,year,comp_id,comp_name):
    soup=BeautifulSoup(html,"html.parser"); titles=section_titles(soup); rows=[]; seen=set()
    for a in soup.find_all("a",href=True):
        href=str(a.get("href") or "")
        m=re.search(r"downloadFile\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)",href)
        if not m: continue
        file_id,file_ext=m.group(1),m.group(2).lower().lstrip(".")
        original=" ".join(a.stripped_strings).strip() or f"{file_id}.{file_ext or 'bin'}"
        key=(file_id,original)
        if key in seen: continue
        seen.add(key)
        section=a.find_parent("div",id=re.compile(r"^inquiry\d+$")); section_id=str(section.get("id") or "") if section else ""
        section_title=titles.get(section_id,"")
        tbody=a.find_parent("tbody"); context=" ".join(tbody.stripped_strings) if tbody else ""
        context=re.sub(r"\s+"," ",context).strip()[:2500]
        category,importance=classify_attachment(original,context,section_title)
        rows.append({
            "year":str(year),"compId":str(comp_id),"compNm":str(comp_name),"section_id":section_id,
            "section_title":section_title,"file_id":file_id,"file_ext":file_ext,
            "original_filename":original,"stored_path":"","source_locator":DOWNLOAD,"bytes":"","sha256":"",
            "content_type":"","importance":importance,"document_category":category,"context_text":context,
            "collection_status":"DISCOVERED","error":""
        })
    return rows

def unique_target(directory,original,file_id,file_ext):
    directory.mkdir(parents=True,exist_ok=True)
    name=safe(original)
    if not name:
        name=safe(file_id)+(f".{file_ext}" if file_ext else "")
    p=directory/name
    if not p.exists(): return p
    suffix=p.suffix; stem=p.stem
    return directory/f"{stem}__{safe(file_id)}{suffix}"

def download_attachment(session,row,root,total_bytes,max_attempts=2):
    last_exc=None; attempts=0
    for attempt in range(max_attempts):
        attempts+=1; start_total=total_bytes; target=None
        try:
            referer=f"{DETAIL}?YEAR={row['year']}&COMP_ID={row['compId']}&OPEN_YN=Y"
            r=session.post(DOWNLOAD,data={"FILE_ID":row["file_id"],"FILE_EXT":row["file_ext"]},headers={"Referer":referer,"Origin":BASE},timeout=(8,60),stream=True,allow_redirects=True)
            r.raise_for_status()
            declared=int(r.headers.get("Content-Length") or 0)
            if declared and declared>MAX_ATTACHMENT_BYTES: raise ValueError("attachment exceeds per-file safety limit")
            target=unique_target(root/str(row["year"])/safe(row["compId"]),row["original_filename"],row["file_id"],row["file_ext"])
            count=0
            with target.open("wb") as f:
                for chunk in r.iter_content(1024*1024):
                    if not chunk: continue
                    count+=len(chunk); total_bytes+=len(chunk)
                    if count>MAX_ATTACHMENT_BYTES or total_bytes>MAX_ATTACHMENT_TOTAL_BYTES:
                        raise ValueError("attachment collection size safety limit exceeded")
                    f.write(chunk)
            if count==0: raise ValueError("zero-byte attachment")
            ctype=str(r.headers.get("Content-Type") or "").split(";")[0].lower()
            if row["file_ext"] not in {"html","htm"} and ctype.startswith("text/html"):
                raise ValueError("attachment endpoint returned HTML instead of file")
            row.update({"stored_path":str(target),"bytes":count,"sha256":sha256(target),"content_type":ctype,"collection_status":"DOWNLOADED","error":""})
            return True,total_bytes,attempts
        except Exception as exc:
            last_exc=exc; total_bytes=start_total
            try:
                if target and target.exists(): target.unlink()
            except Exception: pass
            if attempt+1<max_attempts: time.sleep(0.5*(attempt+1))
    row.update({"collection_status":"DOWNLOAD_FAILED","error":f"{type(last_exc).__name__}: {last_exc}"})
    return False,total_bytes,attempts

def write_attachment_index(out,rows):
    with (out/"attachment_index.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=ATTACHMENT_FIELDS,extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    with (out/"attachment_index.jsonl").open("w",encoding="utf-8") as f:
        for row in rows: f.write(json.dumps(row,ensure_ascii=False)+"\n")

def main(req_path):
    req=json.loads(Path(req_path).read_text(encoding="utf-8")); cfg=req.get("sources",{}).get("ENVINFO",{})
    y1=int(cfg.get("start_year",cfg.get("proof_year",2024))); y2=int(cfg.get("end_year",cfg.get("proof_year",2024)))
    terms=cfg.get("search_terms") or [cfg.get("search_term",req.get("company_display_name",""))]
    page_size=int(cfg.get("page_size",200)); collect_details=bool(cfg.get("collect_details",True)); max_details=int(cfg.get("max_details",30)); collect_attachments=bool(cfg.get("collect_attachments",True))
    out=Path("output/ENVINFO"); raw=out/"raw_search"; details=out/"raw_detail"; attachments_root=out/"raw_attachments"
    raw.mkdir(parents=True,exist_ok=True); details.mkdir(parents=True,exist_ok=True); attachments_root.mkdir(parents=True,exist_ok=True)
    s=requests.Session(); s.headers.update({"User-Agent":UA})
    status={"source_key":"ENVINFO","status":"RUNNING","year_start":y1,"year_end":y2,"terms":terms,"requests":0,"errors":0}
    dedup={}; attachment_rows=[]; attachment_ok=attachment_fail=0; attachment_bytes=0
    try:
        p=s.get(SEARCH_PAGE,timeout=(5,12)); p.raise_for_status(); (out/"search_page_raw.html").write_text(p.text,encoding="utf-8")
        term_map=cfg.get("search_terms_by_year",{})
        jobs=[(y,y,term) for y in range(y1,y2+1) for term in term_map.get(str(y),terms)] if term_map else [(y1,y2,term) for term in terms]
        for query_start,query_end,term in jobs:
            page=1; total=None
            while True:
                status["requests"]+=1
                r=s.post(SEARCH,data=search_payload(query_start,query_end,term,page,page_size),headers={"Referer":SEARCH_PAGE,"X-Requested-With":"XMLHttpRequest"},timeout=(5,20)); r.raise_for_status()
                (raw/f"{query_start}_{query_end}_{safe(term)}_p{page}.json").write_text(r.text,encoding="utf-8")
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
                    found=extract_attachments(rr.text,year,comp,name)
                    attachment_rows.extend(found)
                    if collect_attachments:
                        for att in found:
                            ok,attachment_bytes,attempts=download_attachment(s,att,attachments_root,attachment_bytes)
                            status["requests"]+=attempts
                            if ok: attachment_ok+=1
                            else: attachment_fail+=1; status["errors"]+=1
                            time.sleep(float(cfg.get("request_delay_ms",80))/1000)
                except Exception as e:
                    detail_fail+=1; status["errors"]+=1
                    (out/"errors.log").open("a",encoding="utf-8").write(f"DETAIL\t{year}\t{comp}\t{e}\n")
                time.sleep(float(cfg.get("request_delay_ms",80))/1000)
        write_attachment_index(out,attachment_rows)
        status.update({"status":"DATA_FOUND" if rows else "NO_MATCH","rows":len(rows),"unique_comp_ids":len({r.get('compId') for r in rows}),"detail_ok":detail_ok,"detail_fail":detail_fail,"attachments_discovered":len(attachment_rows),"attachment_ok":attachment_ok,"attachment_fail":attachment_fail,"attachment_bytes":attachment_bytes})
    except Exception as e:
        write_attachment_index(out,attachment_rows)
        status.update({"status":"REQUEST_OR_PARSE_FAILED","fatal_error":f"{type(e).__name__}: {e}","attachments_discovered":len(attachment_rows),"attachment_ok":attachment_ok,"attachment_fail":attachment_fail,"attachment_bytes":attachment_bytes})
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(status,ensure_ascii=False))
    return 0 if status["status"]!="REQUEST_OR_PARSE_FAILED" else 61

if __name__=="__main__": sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "requests/current.json"))
