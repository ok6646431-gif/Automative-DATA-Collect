"""Merge a fresh CORP_DOCS attempt with a previously validated document lane.

A transient source failure must not erase a previously downloaded official document.
Fresh successful downloads always win. A prior success is retained only when its
actual source URL is still explicitly allowed by the current document evidence
(primary or verified fallback) and the document identity still matches.
"""

import argparse, csv, json, shutil
from pathlib import Path

STRONG_VERIFICATION={"VERIFIED","SOURCE_VERIFIED"}


def read_json(path,default=None):
    p=Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def read_csv(path):
    p=Path(path)
    if not p.exists() or p.stat().st_size==0: return []
    with p.open(encoding="utf-8-sig",newline="") as f: return list(csv.DictReader(f))


def write_csv(path,rows,fields):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)


def resolve_lane(root):
    root=Path(root)
    for p in (root,root/"CORP_DOCS",root/"output"/"CORP_DOCS"):
        if (p/"document_index.csv").exists(): return p
    raise FileNotFoundError(f"CORP_DOCS lane not found under {root}")


def source_file(lane,stored_path):
    lane=Path(lane); raw=str(stored_path or "").replace("\\","/")
    prefixes=("output/CORP_DOCS/","CORP_DOCS/")
    for prefix in prefixes:
        if raw.startswith(prefix): raw=raw[len(prefix):]; break
    p=lane/raw
    return p if p.exists() else None


def allowed_sources(doc):
    result=[]
    for item in [doc]+list(doc.get("fallback_sources") or []):
        if not isinstance(item,dict): continue
        if str(item.get("verification_status") or "") not in STRONG_VERIFICATION: continue
        url=str(item.get("source_url") or "")
        if url and url not in result: result.append(url)
    return result


def same_identity(row,doc):
    if not row: return False
    if str(row.get("document_type") or "") != str(doc.get("document_type") or ""): return False
    expected_year=str(doc.get("report_year") or "")
    if expected_year and str(row.get("report_year") or "") != expected_year: return False
    return True


def retainable(row,doc,lane):
    if not same_identity(row,doc): return False
    if str(row.get("collection_status") or "")!="DOWNLOADED": return False
    if str(row.get("verification_status") or "") not in STRONG_VERIFICATION: return False
    if str(row.get("source_url") or "") not in allowed_sources(doc): return False
    return source_file(lane,row.get("stored_path")) is not None


def copy_row_file(row,source_lane,dest_lane):
    src=source_file(source_lane,row.get("stored_path"))
    if src is None: return False
    raw=str(row.get("stored_path") or "").replace("\\","/")
    for prefix in ("output/CORP_DOCS/","CORP_DOCS/"):
        if raw.startswith(prefix): raw=raw[len(prefix):]; break
    dst=Path(dest_lane)/raw; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    return True


def merge(prior_root,fresh_root,evidence_path,out_root):
    prior=resolve_lane(prior_root); fresh=resolve_lane(fresh_root); out=Path(out_root)
    if out.exists(): shutil.rmtree(out)
    out.mkdir(parents=True)
    evidence=read_json(evidence_path,{}) or {}; docs=evidence.get("documents",[]) or []
    old={r.get("document_id"):r for r in read_csv(prior/"document_index.csv") if r.get("document_id")}
    new={r.get("document_id"):r for r in read_csv(fresh/"document_index.csv") if r.get("document_id")}
    rows=[]; retained=0; fresh_ok=0; failed=0

    for doc in docs:
        did=str(doc.get("document_id") or ""); cur=new.get(did); prev=old.get(did); chosen=None; lane=None
        if cur and str(cur.get("collection_status") or "")=="DOWNLOADED" and source_file(fresh,cur.get("stored_path")) is not None:
            chosen=dict(cur); lane=fresh; fresh_ok+=1
        elif retainable(prev,doc,prior):
            chosen=dict(prev); lane=prior; retained+=1
            current_state=str((cur or {}).get("collection_status") or "NO_CURRENT_ROW")
            current_error=str((cur or {}).get("notes") or "")
            note=str(chosen.get("notes") or "")
            suffix=f"retained_prior_success_after_current={current_state}"
            if current_error: suffix+=f"; current_error={current_error[:800]}"
            chosen["notes"]="; ".join(x for x in (note,suffix) if x)
        elif cur:
            chosen=dict(cur); failed+=int(str(cur.get("collection_status") or "")!="DOWNLOADED")
        elif prev and same_identity(prev,doc):
            chosen=dict(prev); failed+=int(str(prev.get("collection_status") or "")!="DOWNLOADED")
        else:
            chosen={
                "document_id":did,"document_type":str(doc.get("document_type") or "OTHER_OFFICIAL_DOCUMENT"),
                "title":str(doc.get("title") or ""),"report_year":str(doc.get("report_year") or ""),
                "source_url":str(doc.get("source_url") or ""),"source_locator":str(doc.get("source_locator") or doc.get("source_url") or ""),
                "verification_status":str(doc.get("verification_status") or "UNVERIFIED"),"collection_status":"DOWNLOAD_FAILED",
                "notes":"No current or retainable prior document row."
            }; failed+=1
        if lane is not None: copy_row_file(chosen,lane,out)
        rows.append(chosen)

    fields=[]
    for source in (read_csv(fresh/"document_index.csv"),read_csv(prior/"document_index.csv"),rows):
        for r in source:
            for k in r:
                if k not in fields: fields.append(k)
    write_csv(out/"document_index.csv",rows,fields or ["document_id"])

    attempts=read_csv(fresh/"download_attempts.csv")
    attempt_fields=list(attempts[0]) if attempts else ["document_id","source_order","source_role","source_url","source_locator","verification_status","attempt_status","error","bytes","content_type"]
    for doc in docs:
        did=str(doc.get("document_id") or ""); cur=new.get(did); prev=old.get(did)
        if cur and str(cur.get("collection_status") or "")!="DOWNLOADED" and retainable(prev,doc,prior):
            attempts.append({
                "document_id":did,"source_order":"prior","source_role":"RETAINED_PRIOR","source_url":prev.get("source_url",""),
                "source_locator":prev.get("source_locator",""),"verification_status":prev.get("verification_status",""),
                "attempt_status":"RETAINED_PRIOR_SUCCESS","error":str(cur.get("notes") or ""),"bytes":prev.get("bytes",""),"content_type":prev.get("content_type","")
            })
    write_csv(out/"download_attempts.csv",attempts,attempt_fields)

    gaps=evidence.get("gaps",[]) or []
    (out/"discovery_gaps.json").write_text(json.dumps(gaps,ensure_ascii=False,indent=2),encoding="utf-8")
    total_bytes=sum(int(r.get("bytes") or 0) for r in rows if str(r.get("collection_status") or "")=="DOWNLOADED")
    status={
        "source_key":"CORP_DOCS","status":"DATA_FOUND" if failed==0 else "PARTIAL_DOWNLOAD",
        "request_id":str(evidence.get("request_id") or ""),"discovery_status":str(evidence.get("discovery_status") or "UNKNOWN"),
        "documents_declared":len(docs),"downloaded":sum(1 for r in rows if str(r.get("collection_status") or "")=="DOWNLOADED"),
        "fresh_downloaded":fresh_ok,"retained_prior":retained,"failed":failed,"skipped":sum(1 for r in rows if str(r.get("collection_status") or "").startswith("SKIPPED_")),
        "gaps":len(gaps),"bytes":total_bytes,"principle":"Fresh success wins; current failure may retain an earlier verified download only when that exact source remains allowed by current evidence."
    }
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"merge_summary.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(status,ensure_ascii=False)); return status


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--prior",required=True); ap.add_argument("--fresh",required=True); ap.add_argument("--evidence",default="requests/document_evidence.json"); ap.add_argument("--out",required=True); a=ap.parse_args()
    merge(a.prior,a.fresh,a.evidence,a.out)


if __name__=="__main__": main()
