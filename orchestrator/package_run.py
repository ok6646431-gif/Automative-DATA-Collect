import argparse, csv, hashlib, json, shutil
from pathlib import Path
from postprocess import run_integration, stable_id
from event_analysis import run_event_analysis
from requested_scope import apply_requested_scope
from review_selection import run_review_selection
from cross_layer_review import run_cross_layer_review
from review_report import build_review_report
from archive_builder import render_html_pdf

BAD={"REMOTE_HOST_UNREACHABLE","REQUEST_OR_PARSE_FAILED","CONFIG_ERROR"}
DEGRADABLE_SOURCE_FAILURES={"REMOTE_HOST_UNREACHABLE","REQUEST_OR_PARSE_FAILED","COLLECTION_FAILED_RETRY_EXHAUSTED"}
STRUCTURAL_SOURCE_FAILURES={"CONFIG_ERROR"}
SOURCES=["ENVINFO","PRTR","CHEM_STATS","CLEANSYS_AIR","SOOSIRO_WATER"]
ROOT_ARTIFACTS=[
    "Company_Profile.json","Event_Evidence.json","Coverage_Matrix.csv","Coverage_Status.csv","Integration_Summary.json",
    "REVIEW_REQUIRED.json","Site_Master.csv","Source_Identity.csv","Validation_Queue.csv","Event_Registry.csv",
    "Coverage_Event_Links.csv","Analysis_Ready_Index.csv","Requested_Scope.json","Analysis_Scope.csv",
    "Review_Metric_Inventory.csv","Review_Signal_Registry.csv","Management_Action_Ledger.csv",
    "Chemical_Review_Candidates.csv","Water_Daily_Stats.csv","Review_Display_Plan.csv",
    "Review_Topic_Candidates.csv","Review_Source_Coverage.csv","Review_Selection_Summary.json",
    "Source_Availability.csv","Evidence_Layer_Registry.csv","Cross_Layer_Review_Candidates.csv","Study_Question_Queue.csv",
    "Cross_Layer_Review_Summary.json","Document_Semantic_Candidates.csv","Generated_Semantic_Evidence.json",
    "Document_Semantics_Summary.json","Environmental_Review_Brief.html","Environmental_Review_Brief.pdf",
    "Environmental_Review_Evidence.xlsx","Environmental_Review_Summary.json"
]

DECLARED_ROW_STREAM_COUNTS={
    "ENVINFO":{"excluded_rows.jsonl":"excluded_rows"},
    "PRTR":{"detail_table_rows.jsonl":"detail_table_rows","excluded_rows.jsonl":"excluded_rows"},
    "CHEM_STATS":{"detail_table_rows.jsonl":"detail_table_rows","excluded_rows.jsonl":"excluded_rows"},
    "CLEANSYS_AIR":{"annual_rows.jsonl":"annual_rows"},
    "SOOSIRO_WATER":{"annual_rows.jsonl":"annual_rows","daily_rows.jsonl":"daily_rows","excluded_rows.jsonl":"excluded_rows"},
}


def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def sha256(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()


def declared_empty_row_stream(source,path,status_payload):
    counter=DECLARED_ROW_STREAM_COUNTS.get(source,{}).get(Path(path).name)
    if not counter: return False
    try: return int(status_payload.get(counter,-1))==0
    except (TypeError,ValueError): return False


def read_icis_statuses(root):
    try:
        return read_json(root/"PRTR/status.json"),read_json(root/"CHEM_STATS/status.json")
    except Exception:
        return None,None


def good_icis(root):
    p,c=read_icis_statuses(root)
    return bool(p and c and p.get("status") not in BAD and c.get("status") not in BAD)


def choose_icis(icis_root):
    """Prefer a good ICIS attempt, but preserve a failed attempt when retries exhaust.

    A failed public source is still evidence about source availability. Returning a
    failed attempt lets downstream packaging retain its status.json instead of turning
    a known outage into an ambiguous missing-source condition.
    """
    if not icis_root.exists(): return None,"NO_ATTEMPT_ARTIFACT"
    usable=[]
    for d in sorted([x for x in icis_root.iterdir() if x.is_dir()]):
        for r in [d,d/"output"]:
            p,c=read_icis_statuses(r)
            if p and c:
                if p.get("status") not in BAD and c.get("status") not in BAD:
                    return r,"GOOD_ATTEMPT"
                usable.append(r)
                break
    if usable: return usable[0],"FAILED_ATTEMPT_PRESERVED"
    return None,"NO_ATTEMPT_ARTIFACT"


def write_unavailable_source(output,source,reason):
    dst=Path(output)/source; dst.mkdir(parents=True,exist_ok=True)
    payload={
        "source_key":source,
        "status":"COLLECTION_FAILED_RETRY_EXHAUSTED",
        "failure_reason":reason,
        "synthetic_status":True,
        "note":"No collector attempt artifact was available after retries. This is source unavailability, not evidence of no data."
    }
    (dst/"status.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")


def copy_source(src_root,dst_root,source):
    src=src_root/source
    if not src.exists(): return False
    dst=dst_root/source
    if dst.exists(): shutil.rmtree(dst)
    shutil.copytree(src,dst)
    return True


def years_from_source(root,source):
    years=set()
    if source=="ENVINFO":
        p=root/source/"discovery.csv"
        if p.exists():
            with p.open(encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    if r.get("year"): years.add(str(r["year"]))
    elif source in {"PRTR","CHEM_STATS"}:
        p=root/source/"discovery.csv"
        if p.exists():
            with p.open(encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    if r.get("search_year"): years.add(str(r["search_year"]))
    elif source=="CLEANSYS_AIR":
        p=root/source/"annual_rows.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    y=json.loads(line).get("examin_year")
                    if y is not None: years.add(str(y))
    elif source=="SOOSIRO_WATER":
        p=root/source/"annual_rows.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r=json.loads(line); y=r.get("YEAR",r.get("year"))
                    if y is not None: years.add(str(y))
    return sorted(years)


def validate(root):
    results={}; review=[]; ok=True
    for s in SOURCES:
        sp=root/s/"status.json"
        if not sp.exists():
            results[s]={"status":"MISSING_STATUS","years":[],"checks":["missing_status"]}; ok=False
            review.append({"source":s,"issues":["missing_status"],"zero_byte":[]})
            continue
        st=read_json(sp); status=st.get("status")
        checks=[]
        if status in BAD or status=="COLLECTION_FAILED_RETRY_EXHAUSTED": checks.append("terminal_failure")
        if s=="ENVINFO" and status=="DATA_FOUND" and st.get("detail_fail",0)!=0: checks.append("detail_missing")
        if s=="PRTR" and status=="DATA_FOUND" and st.get("detail_fail",0)!=0: checks.append("detail_missing")
        if s=="CHEM_STATS" and status=="DATA_FOUND" and st.get("detail_fail",0)!=0: checks.append("detail_missing")
        zero=[]
        for p in (root/s).rglob("*"):
            if p.is_file() and p.stat().st_size==0 and not declared_empty_row_stream(s,p,st):
                zero.append(str(p.relative_to(root)))
        if zero: checks.append("zero_byte_artifact")
        if checks: ok=False; review.append({"source":s,"issues":checks,"zero_byte":zero,"status":status})
        normalized_years=years_from_source(root,s)
        status_payload={k:v for k,v in st.items() if k not in {"status","years","checks"}}
        results[s]={"status":status,"years":normalized_years,"checks":checks,**status_payload}
    return ok,results,review


def package_health(statuses,source_review):
    """Separate recoverable source outages from structural package corruption."""
    for item in source_review:
        source=item.get("source"); issues=set(item.get("issues") or []); status=str((statuses.get(source) or {}).get("status") or item.get("status") or "")
        if "missing_status" in issues or "zero_byte_artifact" in issues: return "FAIL"
        if status in STRUCTURAL_SOURCE_FAILURES: return "FAIL"
    return "DEGRADED" if source_review else "PASS"


def artifact_index(output,package_root):
    rows=[]
    for p in sorted(output.rglob("*")):
        if p.is_file():
            rel=p.relative_to(package_root); source=rel.parts[1] if len(rel.parts)>1 else "SOURCE"
            rows.append({"source":source,"path":str(rel),"bytes":p.stat().st_size,"sha256":sha256(p)})
    for name in ROOT_ARTIFACTS:
        p=package_root/name
        if p.exists() and p.is_file(): rows.append({"source":"INTEGRATION","path":name,"bytes":p.stat().st_size,"sha256":sha256(p)})
    return rows


def append_coverage_reviews(package_root,company_id):
    coverage_path=package_root/"Coverage_Status.csv"; queue_path=package_root/"Validation_Queue.csv"; review_path=package_root/"REVIEW_REQUIRED.json"
    if not coverage_path.exists(): return 0
    with coverage_path.open(encoding="utf-8-sig",newline="") as f: coverage=list(csv.DictReader(f))
    with queue_path.open(encoding="utf-8-sig",newline="") as f: queue=list(csv.DictReader(f)) if queue_path.exists() else []
    fields=["validation_id","company_id","object_type","object_key","issue_type","severity","detected_by","evidence","recommended_action","status","resolved_by","resolved_at","notes"]
    seen={r.get("validation_id") for r in queue}; added=[]
    for c in coverage:
        if c.get("coverage_status") not in {"SHORT_COVERAGE","NO_DATA"}: continue
        vid=stable_id("VAL_",company_id,"COVERAGE",c.get("source_key"),c.get("coverage_status"))
        if vid in seen: continue
        v={"validation_id":vid,"company_id":company_id,"object_type":"COVERAGE","object_key":c.get("source_key","") ,"issue_type":"MINIMUM_COVERAGE_NOT_MET" if c.get("coverage_status")=="SHORT_COVERAGE" else "NO_DATA","severity":"HIGH","detected_by":"COVERAGE_POLICY","evidence":f"collected={c.get('collected_start')}..{c.get('collected_end')} | status={c.get('coverage_status')}","recommended_action":"extend collection window to minimum policy/full public history before trend analysis","status":"REVIEW_REQUIRED","resolved_by":"","resolved_at":"","notes":c.get("next_action","")}
        queue.append(v); added.append(v); seen.add(vid)
    with queue_path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(queue)
    review=read_json(review_path) if review_path.exists() else []; rseen={r.get("validation_id") for r in review if isinstance(r,dict) and r.get("validation_id")}
    for v in added:
        if v["validation_id"] not in rseen: review.append(v); rseen.add(v["validation_id"])
    review_path.write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding="utf-8")
    return len(added)


def build_human_review(out):
    report=build_review_report(out,render_pdf=False)
    html_path=out/"Environmental_Review_Brief.html"; pdf_path=out/"Environmental_Review_Brief.pdf"
    ok,err=render_html_pdf(html_path,pdf_path)
    report["pdf_ok"]=bool(ok); report["pdf_error"]=err or ""; report["report_pdf"]=pdf_path.name if ok else None
    (out/"Environmental_Review_Summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--stable",default="collected/stable"); ap.add_argument("--icis",default="collected/icis"); ap.add_argument("--profile",default="requests/company_profile.json"); ap.add_argument("--events",default="requests/event_evidence.json"); ap.add_argument("--semantic",default="requests/semantic_evidence.json"); ap.add_argument("--out",default="assembled")
    args=ap.parse_args(); stable=Path(args.stable); icis=Path(args.icis); profile=Path(args.profile); events=Path(args.events); semantic=Path(args.semantic); out=Path(args.out); output=out/"output"
    if out.exists(): shutil.rmtree(out)
    output.mkdir(parents=True,exist_ok=True)
    for s in ["ENVINFO","CLEANSYS_AIR","SOOSIRO_WATER","CORP_DOCS"]: copy_source(stable,output,s) or copy_source(stable/"output",output,s)
    chosen,icis_selection_state=choose_icis(icis)
    if chosen:
        for s in ["PRTR","CHEM_STATS"]: copy_source(chosen,output,s)
    else:
        for s in ["PRTR","CHEM_STATS"]: write_unavailable_source(output,s,"No ICIS attempt contained both source status files after retries.")

    _,statuses,source_review=validate(output)
    health=package_health(statuses,source_review)
    (out/"REVIEW_REQUIRED.json").write_text(json.dumps(source_review,ensure_ascii=False,indent=2),encoding="utf-8")
    if profile.exists(): shutil.copy2(profile,out/"Company_Profile.json")
    if events.exists(): shutil.copy2(events,out/"Event_Evidence.json")

    with (out/"Coverage_Matrix.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=["source","status","years","checks"]); w.writeheader()
        for s,r in statuses.items(): w.writerow({"source":s,"status":r.get("status"),"years":"|".join(str(x) for x in r.get("years",[])),"checks":"|".join(str(x) for x in r.get("checks",[]))})

    integration=run_integration(output,profile,out)
    append_coverage_reviews(out,integration["company_id"])
    integration.update(run_event_analysis(out,events if events.exists() else None))
    scope_summary=apply_requested_scope(out)
    integration["requested_scope"]={
        "mode": scope_summary.get("mode"),
        "label": scope_summary.get("label"),
        "target_canonical_site_ids": scope_summary.get("target_canonical_site_ids",[]),
        "analysis_rows_before": scope_summary.get("analysis_rows_before",0),
        "analysis_rows_after": scope_summary.get("analysis_rows_after",0),
        "unresolved_candidates": scope_summary.get("unresolved_candidates",[]),
    }
    integration["review_selection"]=run_review_selection(output,out)
    integration["cross_layer_review"]=run_cross_layer_review(out,semantic if semantic.exists() else None)
    integration["review_report"]=build_human_review(out)
    with (out/"Validation_Queue.csv").open(encoding="utf-8-sig",newline="") as f: integration["validation_queue"]=sum(1 for _ in csv.DictReader(f))
    (out/"Integration_Summary.json").write_text(json.dumps(integration,ensure_ascii=False,indent=2),encoding="utf-8")
    all_review=read_json(out/"REVIEW_REQUIRED.json"); validation="REVIEW_REQUIRED" if all_review else "PASS"

    idx=artifact_index(output,out)
    with (out/"Artifact_Index.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=["source","path","bytes","sha256"]); w.writeheader(); w.writerows(idx)

    manifest={"schema_version":"1.7","package_health":health,"validation":validation,"review_count":len(all_review),"selected_icis_attempt":str(chosen) if chosen else None,"icis_selection_state":icis_selection_state,"sources":statuses,"integration":integration,"requested_scope":scope_summary,"review_selection":integration.get("review_selection",{}),"cross_layer_review":integration.get("cross_layer_review",{}),"review_report":integration.get("review_report",{}),"artifact_count":len(idx)}
    (out/"Master_Manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"package_health":health,"validation":validation,"review_count":len(all_review),"selected_icis_attempt":manifest["selected_icis_attempt"],"icis_selection_state":icis_selection_state,"artifacts":len(idx),"integration":integration},ensure_ascii=False))
    # A degraded package is intentionally deliverable: source outages remain explicit
    # REVIEW_REQUIRED evidence gaps. Structural corruption/configuration errors still fail.
    raise SystemExit(81 if health=="FAIL" else 0)

if __name__=="__main__": main()
