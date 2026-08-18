import argparse, csv, json, re
from collections import defaultdict
from pathlib import Path

from postprocess import stable_id

CORE_SOURCES=["ENVINFO","PRTR","CHEM_STATS","CLEANSYS_AIR","SOOSIRO_WATER"]
EVENT_FIELDS=["event_id","company_id","canonical_site_id","event_scope","event_type","event_date_start","event_date_end","event_title","event_description","source_key","source_locator","verification_status","analysis_role","causality_status","notes"]
LINK_FIELDS=["link_id","company_id","source_key","canonical_site_id","event_id","event_type","event_date","event_year","collected_start","collected_end","relevance_basis","baseline_status","comparability_action","causality_status","verification_status","notes"]
VALIDATION_FIELDS=["validation_id","company_id","object_type","object_key","issue_type","severity","detected_by","evidence","recommended_action","status","resolved_by","resolved_at","notes"]
ANALYSIS_FIELDS=["analysis_id","company_id","canonical_site_id","source_key","source_site_id","time_key","granularity","raw_locator","identity_status","coverage_status","comparability_status","event_link_ids","raw_semantics","analysis_readiness","analysis_eligible","notes"]


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


def read_jsonl(path):
    p=Path(path)
    if not p.exists(): return []
    return [(i,json.loads(line)) for i,line in enumerate(p.read_text(encoding="utf-8").splitlines(),1) if line.strip()]


def event_year(value):
    m=re.match(r"^\s*(\d{4})",str(value or "")); return int(m.group(1)) if m else None


def int_year(value):
    try: return int(str(value)[:4])
    except Exception: return None


def role_for(kind):
    if kind=="DISCLOSURE_DEFINITION_CHANGE": return "COMPARABILITY_MARKER"
    if kind in {"SITE_IDENTITY_CHANGE","CORPORATE_RESTRUCTURE"}: return "IDENTITY_MARKER"
    if kind in {"INTEGRATED_PERMIT","REGULATION_EFFECTIVE_CHANGE"}: return "BASELINE_MARKER"
    return "CONTEXT_MARKER"


def action_for(kind):
    if kind=="DISCLOSURE_DEFINITION_CHANGE": return "SEGMENT_AT_EVENT"
    if kind=="REGULATION_EFFECTIVE_CHANGE": return "REVIEW_SEGMENT_AT_EVENT"
    if kind in {"SITE_IDENTITY_CHANGE","CORPORATE_RESTRUCTURE"}: return "REVIEW_IDENTITY_MAPPING"
    return "CONTEXT_ONLY"


def make_validation(company_id,obj,key,issue,severity,evidence,action,notes=""):
    return {"validation_id":stable_id("VAL_",company_id,obj,key,issue),"company_id":company_id,"object_type":obj,"object_key":key,"issue_type":issue,"severity":severity,"detected_by":"EVENT_ANALYSIS_RULE","evidence":evidence,"recommended_action":action,"status":"REVIEW_REQUIRED","resolved_by":"","resolved_at":"","notes":notes}


def merge_validations(root,new_rows):
    root=Path(root); q=root/"Validation_Queue.csv"; r=root/"REVIEW_REQUIRED.json"
    existing=read_csv(q); by_id={x["validation_id"]:x for x in existing if x.get("validation_id")}; order=list(by_id)
    for row in new_rows:
        vid=row["validation_id"]
        if vid in by_id:
            old=by_id[vid]
            if old.get("status") in {"RESOLVED","ACCEPTED_RISK","REJECTED"}: continue
            for k,v in row.items():
                if not old.get(k) and v not in (None,""): old[k]=v
        else: by_id[vid]=row; order.append(vid)
    write_csv(q,[by_id[x] for x in order],VALIDATION_FIELDS)
    review=read_json(r,[]) or []; seen={x.get("validation_id") for x in review if isinstance(x,dict)}
    for row in new_rows:
        if row["validation_id"] not in seen: review.append(row); seen.add(row["validation_id"])
    r.write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding="utf-8")


def resolve_site(raw,imap,confirmed_sites):
    sid=str(raw.get("canonical_site_id") or "").strip()
    if sid: return sid if sid in confirmed_sites else ""
    ref=raw.get("source_site_ref") or {}; key=(str(ref.get("source_key") or ""),str(ref.get("source_site_id") or ""))
    row=imap.get(key)
    return row.get("canonical_site_id","") if row and row.get("match_status")=="CONFIRMED" else ""


def integrate_events(package_root,evidence_path=None):
    root=Path(package_root); company_id=(read_json(root/"Integration_Summary.json",{}) or {}).get("company_id","")
    sites=read_csv(root/"Site_Master.csv"); confirmed={x.get("canonical_site_id") for x in sites if x.get("identity_status")=="CONFIRMED"}
    identities=read_csv(root/"Source_Identity.csv"); imap={(x.get("source_key",""),x.get("source_site_id","")):x for x in identities}
    coverage=read_csv(root/"Coverage_Status.csv"); covmap={x.get("source_key"):x for x in coverage}
    evidence=read_json(evidence_path,{}) if evidence_path and Path(evidence_path).exists() else None
    validations=[]; raw_events=[]
    if evidence is None:
        evidence={"discovery_status":"NOT_RUN","events":[],"gaps":[]}
        validations.append(make_validation(company_id,"EVENT_DISCOVERY",company_id,"EVENT_DISCOVERY_NOT_RUN","MEDIUM","No event_evidence input supplied.","Run official-source event discovery; no search is not evidence of no event."))
    for gap in evidence.get("gaps",[]) or []:
        key=str(gap.get("gap_id") or gap.get("source_key") or gap.get("query") or "UNKNOWN_GAP")
        validations.append(make_validation(company_id,"EVENT_DISCOVERY",key,"EVENT_DISCOVERY_GAP",str(gap.get("severity") or "MEDIUM"),json.dumps(gap,ensure_ascii=False),"Resolve or retain the gap explicitly; never convert a search gap to 'no event'."))
    for raw in evidence.get("events",[]) or []:
        kind=str(raw.get("event_type") or "UNKNOWN_EVENT"); start=str(raw.get("event_date_start") or "").strip(); locator=str(raw.get("source_locator") or "").strip(); sid=resolve_site(raw,imap,confirmed)
        scope=str(raw.get("event_scope") or ("SITE" if raw.get("canonical_site_id") or raw.get("source_site_ref") else "COMPANY")); eid=str(raw.get("event_id") or stable_id("EVT_",company_id,kind,start,locator,raw.get("event_title"),sid)); verified=str(raw.get("verification_status") or "NOT_VERIFIED")
        if scope=="SITE" and not sid: validations.append(make_validation(company_id,"EVENT",eid,"EVENT_SITE_UNRESOLVED","HIGH",f"event_type={kind}","Resolve to a CONFIRMED canonical site; do not weak-merge."))
        if not locator: validations.append(make_validation(company_id,"EVENT",eid,"TRACEABILITY_GAP","HIGH",f"event_type={kind}; source_locator missing","Add an official primary-source locator."))
        if not start: validations.append(make_validation(company_id,"EVENT",eid,"EVENT_DATE_UNVERIFIED","HIGH",f"event_type={kind}; actual date missing","Verify the actual event/effective date; never infer it from publication/snapshot date."))
        if verified not in {"VERIFIED","SOURCE_VERIFIED"}: validations.append(make_validation(company_id,"EVENT",eid,"EVENT_NOT_VERIFIED","MEDIUM",f"verification_status={verified}","Verify against an official primary source."))
        raw_events.append({"event_id":eid,"company_id":company_id,"canonical_site_id":sid,"event_scope":scope,"event_type":kind,"event_date_start":start,"event_date_end":str(raw.get("event_date_end") or ""),"event_title":str(raw.get("event_title") or ""),"event_description":str(raw.get("event_description") or ""),"source_key":str(raw.get("source_key") or ""),"source_locator":locator,"verification_status":verified,"analysis_role":str(raw.get("analysis_role") or role_for(kind)),"causality_status":"NO_CAUSAL_CLAIM","notes":str(raw.get("notes") or ""),"affected_sources":raw.get("affected_sources") or []})
    dedup={}; order=[]
    for e in raw_events:
        eid=e["event_id"]
        if eid not in dedup: dedup[eid]=e; order.append(eid); continue
        for k,v in e.items():
            if not dedup[eid].get(k) and v not in (None,"",[]): dedup[eid][k]=v
    events=[dedup[x] for x in order]; write_csv(root/"Event_Registry.csv",events,EVENT_FIELDS)

    source_sites=defaultdict(set)
    for x in identities:
        if x.get("match_status")=="CONFIRMED" and x.get("canonical_site_id"): source_sites[x.get("source_key")].add(x.get("canonical_site_id"))
    links=[]
    for e in events:
        explicit=[str(x) for x in e.get("affected_sources",[]) if str(x) in CORE_SOURCES]
        sources=explicit or ([s for s in CORE_SOURCES if e.get("canonical_site_id") in source_sites[s]] if e.get("event_scope")=="SITE" and e.get("canonical_site_id") else CORE_SOURCES)
        ey=event_year(e.get("event_date_start"))
        for source in sources:
            cov=covmap.get(source,{}); cs=int_year(cov.get("collected_start")); baseline="UNKNOWN" if ey is None or cs is None else ("BASELINE_AVAILABLE" if cs<=ey-1 else "BASELINE_MISSING"); lid=stable_id("LNK_",company_id,source,e.get("canonical_site_id"),e["event_id"])
            links.append({"link_id":lid,"company_id":company_id,"source_key":source,"canonical_site_id":e.get("canonical_site_id","") ,"event_id":e["event_id"],"event_type":e["event_type"],"event_date":e.get("event_date_start","") ,"event_year":ey or "UNKNOWN","collected_start":cov.get("collected_start","UNKNOWN"),"collected_end":cov.get("collected_end","UNKNOWN"),"relevance_basis":"EXPLICIT_AFFECTED_SOURCE" if explicit else ("CONFIRMED_SITE_SOURCE_LINK" if e.get("event_scope")=="SITE" else "COMPANY_SCOPE"),"baseline_status":baseline,"comparability_action":action_for(e["event_type"]),"causality_status":"NO_CAUSAL_CLAIM","verification_status":e.get("verification_status","") ,"notes":"Analysis-window candidate only; collected raw data is never truncated."})
            if baseline=="BASELINE_MISSING" and e["event_type"] in {"INTEGRATED_PERMIT","REGULATION_EFFECTIVE_CHANGE","DISCLOSURE_DEFINITION_CHANGE","SITE_IDENTITY_CHANGE","CORPORATE_RESTRUCTURE"}:
                validations.append(make_validation(company_id,"COVERAGE_EVENT",lid,"EVENT_BASELINE_MISSING","HIGH",f"source={source}; event={e['event_id']}; collected_start={cs}; event_year={ey}","Extend collection earlier if public data exists; keep collection and analysis periods separate."))
    write_csv(root/"Coverage_Event_Links.csv",links,LINK_FIELDS)
    by_source=defaultdict(list)
    for x in links: by_source[x["source_key"]].append(x)
    for cov in coverage:
        ls=by_source.get(cov.get("source_key"),[]); actions={x["comparability_action"] for x in ls}
        cov["event_baseline_status"]="NO_EVENT_LINKS" if not ls else ("BASELINE_MISSING" if any(x["baseline_status"]=="BASELINE_MISSING" for x in ls) else ("BASELINE_AVAILABLE" if all(x["baseline_status"]=="BASELINE_AVAILABLE" for x in ls) else "BASELINE_UNKNOWN"))
        old=cov.get("comparability_status","")
        if "SEGMENT_AT_EVENT" in actions: cov["comparability_status"]="SEGMENT_REQUIRED" if old in {"","PENDING"} else old+"|SEGMENT_REQUIRED"
        elif "REVIEW_SEGMENT_AT_EVENT" in actions: cov["comparability_status"]="EVENT_REVIEW" if old in {"","PENDING"} else old+"|EVENT_REVIEW"
    if coverage: write_csv(root/"Coverage_Status.csv",coverage,list(coverage[0]))
    merge_validations(root,validations)
    return {"event_discovery_status":str(evidence.get("discovery_status") or "UNKNOWN"),"events":len(events),"event_links":len(links),"event_validations_added":len({x['validation_id'] for x in validations})}


def analysis_state(identity,coverage,comparability):
    if identity!="CONFIRMED": return "IDENTITY_REVIEW",False
    if coverage not in {"MEETS_MINIMUM","MEETS_MINIMUM_WITH_REVIEW","FULL_HISTORY_CURRENTLY"}: return "COVERAGE_REVIEW",False
    if any(x in str(comparability or "") for x in ["PENDING","REVIEW","TRANSITION","SEGMENT_REQUIRED"]): return "COMPARABILITY_REVIEW",False
    return "READY",True


def build_analysis_index(package_root):
    root=Path(package_root); output=root/"output"; company_id=(read_json(root/"Integration_Summary.json",{}) or {}).get("company_id","")
    identities=read_csv(root/"Source_Identity.csv"); imap={(x.get("source_key",""),x.get("source_site_id","")):x for x in identities}; coverage={x.get("source_key"):x for x in read_csv(root/"Coverage_Status.csv")}
    event_links=defaultdict(list)
    for x in read_csv(root/"Coverage_Event_Links.csv"): event_links[(x.get("source_key",""),x.get("canonical_site_id",""))].append(x.get("link_id",""))
    semantics={"ENVINFO":"SOURCE_NATIVE_VALUES","PRTR":"SOURCE_NATIVE_OFFICIAL_VALUES_NO_RECALC","CHEM_STATS":"SOURCE_NATIVE_SURVEY_ROUND_NO_INTERPOLATION","CLEANSYS_AIR":"PRESERVE_ZERO_NULL","SOOSIRO_WATER":"PRESERVE_ZERO_NULL_DASH_COD_TOC_PROVISIONAL"}; rows=[]
    def add(source,source_id,time_key,granularity,locator,notes=""):
        ident=imap.get((source,str(source_id)),{}); istatus=ident.get("match_status","UNRESOLVED"); sid=ident.get("canonical_site_id","") if istatus=="CONFIRMED" else ""; cov=coverage.get(source,{}); state,eligible=analysis_state(istatus,cov.get("coverage_status","UNKNOWN"),cov.get("comparability_status",""))
        rows.append({"analysis_id":stable_id("ANL_",company_id,source,source_id,time_key,granularity,locator),"company_id":company_id,"canonical_site_id":sid,"source_key":source,"source_site_id":str(source_id),"time_key":str(time_key or "UNKNOWN"),"granularity":granularity,"raw_locator":locator,"identity_status":istatus,"coverage_status":cov.get("coverage_status","UNKNOWN"),"comparability_status":cov.get("comparability_status","UNKNOWN"),"event_link_ids":"|".join(sorted(x for x in event_links.get((source,sid),[]) if x)),"raw_semantics":semantics[source],"analysis_readiness":state,"analysis_eligible":eligible,"notes":notes})
    for i,r in enumerate(read_csv(output/"ENVINFO"/"discovery.csv"),2): add("ENVINFO",r.get("compId"),r.get("year"),"SITE_YEAR",f"output/ENVINFO/discovery.csv#row={i}")
    for i,r in enumerate(read_csv(output/"PRTR"/"discovery.csv"),2): add("PRTR",r.get("entrps_id"),r.get("search_year"),"SITE_YEAR",f"output/PRTR/discovery.csv#row={i}","Official totals/values remain untouched in source artifacts.")
    for i,r in enumerate(read_csv(output/"CHEM_STATS"/"discovery.csv"),2): add("CHEM_STATS",r.get("bplcId"),r.get("search_year") or r.get("reportYear"),"SITE_SURVEY_ROUND",f"output/CHEM_STATS/discovery.csv#row={i}")
    for line,r in read_jsonl(output/"CLEANSYS_AIR"/"annual_rows.jsonl"): add("CLEANSYS_AIR",r.get("source_fact_code") or r.get("fact_code"),r.get("examin_year"),"SITE_YEAR",f"output/CLEANSYS_AIR/annual_rows.jsonl#line={line}")
    for line,r in read_jsonl(output/"SOOSIRO_WATER"/"annual_rows.jsonl"): add("SOOSIRO_WATER",r.get("source_fact_code") or r.get("FACT_CODE"),r.get("YEAR",r.get("year")),"SITE_YEAR",f"output/SOOSIRO_WATER/annual_rows.jsonl#line={line}")
    for line,r in read_jsonl(output/"SOOSIRO_WATER"/"daily_rows.jsonl"): add("SOOSIRO_WATER",r.get("source_fact_code") or r.get("FACT_CODE"),f"{r.get('YEAR','UNKNOWN')}:{r.get('DAY','UNKNOWN')}","SITE_DAY",f"output/SOOSIRO_WATER/daily_rows.jsonl#line={line}","COD and TOC remain separate source-native fields in the referenced row.")
    write_csv(root/"Analysis_Ready_Index.csv",rows,ANALYSIS_FIELDS)
    return {"analysis_index_rows":len(rows),"analysis_ready_rows":sum(1 for x in rows if x["analysis_eligible"] is True)}


def run_event_analysis(package_root,evidence_path=None):
    return {**integrate_events(package_root,evidence_path),**build_analysis_index(package_root)}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--package",default="assembled"); ap.add_argument("--events",default="requests/event_evidence.json"); a=ap.parse_args(); print(json.dumps(run_event_analysis(a.package,a.events if Path(a.events).exists() else None),ensure_ascii=False))

if __name__=="__main__": main()
