import argparse, csv, hashlib, json, shutil
from pathlib import Path
from postprocess import run_integration, stable_id
from event_analysis import run_event_analysis
from requested_scope import apply_requested_scope

BAD={"REMOTE_HOST_UNREACHABLE","REQUEST_OR_PARSE_FAILED","CONFIG_ERROR"}
SOURCES=["ENVINFO","PRTR","CHEM_STATS","CLEANSYS_AIR","SOOSIRO_WATER"]
ROOT_ARTIFACTS=[
    "Company_Profile.json","Event_Evidence.json","Coverage_Matrix.csv","Coverage_Status.csv","Integration_Summary.json",
    "REVIEW_REQUIRED.json","Site_Master.csv","Source_Identity.csv","Validation_Queue.csv","Event_Registry.csv",
    "Coverage_Event_Links.csv","Analysis_Ready_Index.csv","Requested_Scope.json","Analysis_Scope.csv"
]

# Canonical row-stream files and explicit audit row streams are legitimately zero
# bytes when their collector status explicitly reports zero rows. This is different
# from an empty raw response, status file, or other artifact, which must still fail
# structural validation.
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


def good_icis(root):
    try:
        p=read_json(root/"PRTR/status.json"); c=read_json(root/"CHEM_STATS/status.json")
    except Exception:
        return False
    return p.get("status") not in BAD and c.get("status") not in BAD


def choose_icis(icis_root):
    if not icis_root.exists(): return None
    candidates=[]
    for d in sorted([x for x in icis_root.iterdir() if x.is_dir()]):
        roots=[d,d/"output"]
        for r in roots:
            if good_icis(r): candidates.append(r); break
    return candidates[0] if candidates else None


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
        if status in BAD: checks.append("terminal_failure")
        if s=="ENVINFO" and status=="DATA_FOUND" and st.get("detail_fail",0)!=0: checks.append("detail_missing")
        if s=="PRTR" and status=="DATA_FOUND" and st.get("detail_fail",0)!=0: checks.append("detail_missing")
        if s=="CHEM_STATS" and status=="DATA_FOUND" and st.get("detail_fail",0)!=0: checks.append("detail_missing")
        zero=[]
        for p in (root/s).rglob("*"):
            if p.is_file() and p.stat().st_size==0 and not declared_empty_row_stream(s,p,st):
                zero.append(str(p.relative_to(root)))
        if zero: checks.append("zero_byte_artifact")
        if checks: ok=False; review.append({"source":s,"issues":checks,"zero_byte":zero})
        normalized_years=years_from_source(root,s)
        status_payload={k:v for k,v in st.items() if k not in {"status","years","checks"}}
        results[s]={"status":status,"years":normalized_years,"checks":checks,**status_payload}
    return ok,results,review


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


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--stable",default="collected/stable"); ap.add_argument("--icis",default="collected/icis"); ap.add_argument("--profile",default="requests/company_profile.json"); ap.add_argument("--events",default="requests/event_evidence.json"); ap.add_argument("--out",default="assembled")
    args=ap.parse_args(); stable=Path(args.stable); icis=Path(args.icis); profile=Path(args.profile); events=Path(args.events); out=Path(args.out); output=out/"output"
    if out.exists(): shutil.rmtree(out)
    output.mkdir(parents=True,exist_ok=True)
    for s in ["ENVINFO","CLEANSYS_AIR","SOOSIRO_WATER"]: copy_source(stable,output,s) or copy_source(stable/"output",output,s)
    chosen=choose_icis(icis)
    if chosen:
        for s in ["PRTR","CHEM_STATS"]: copy_source(chosen,output,s)

    package_ok,statuses,source_review=validate(output)
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
    with (out/"Validation_Queue.csv").open(encoding="utf-8-sig",newline="") as f: integration["validation_queue"]=sum(1 for _ in csv.DictReader(f))
    (out/"Integration_Summary.json").write_text(json.dumps(integration,ensure_ascii=False,indent=2),encoding="utf-8")
    all_review=read_json(out/"REVIEW_REQUIRED.json"); validation="REVIEW_REQUIRED" if all_review else "PASS"

    idx=artifact_index(output,out)
    with (out/"Artifact_Index.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=["source","path","bytes","sha256"]); w.writeheader(); w.writerows(idx)

    manifest={"schema_version":"1.3","package_health":"PASS" if package_ok else "FAIL","validation":validation,"review_count":len(all_review),"selected_icis_attempt":str(chosen) if chosen else None,"sources":statuses,"integration":integration,"requested_scope":scope_summary,"artifact_count":len(idx)}
    (out/"Master_Manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"package_health":manifest["package_health"],"validation":validation,"review_count":len(all_review),"selected_icis_attempt":manifest["selected_icis_attempt"],"artifacts":len(idx),"integration":integration},ensure_ascii=False))
    raise SystemExit(0 if package_ok else 81)

if __name__=="__main__": main()
