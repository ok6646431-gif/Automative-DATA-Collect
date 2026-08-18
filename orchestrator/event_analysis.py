import argparse, csv, json, re
from collections import defaultdict
from pathlib import Path

from postprocess import stable_id

EVENT_FIELDS=[
    "event_id","company_id","canonical_site_id","event_scope","event_type","event_date_start","event_date_end",
    "event_title","event_description","source_key","source_locator","verification_status","analysis_role","causality_status","notes"
]
LINK_FIELDS=[
    "link_id","company_id","source_key","canonical_site_id","event_id","event_type","event_date","event_year",
    "collected_start","collected_end","relevance_basis","baseline_status","comparability_action","causality_status",
    "verification_status","notes"
]
VALIDATION_FIELDS=[
    "validation_id","company_id","object_type","object_key","issue_type","severity","detected_by","evidence",
    "recommended_action","status","resolved_by","resolved_at","notes"
]
ANALYSIS_FIELDS=[
    "analysis_id","company_id","canonical_site_id","source_key","source_site_id","time_key","granularity",
    "raw_locator","identity_status","coverage_status","comparability_status","event_link_ids","raw_semantics",
    "analysis_readiness","analysis_eligible","notes"
]
CORE_SOURCES=["ENVINFO","PRTR","CHEM_STATS","CLEANSYS_AIR","SOOSIRO_WATER"]


def read_json(path,default=None):
    p=Path(path)
    if not p.exists(): return default
    return json.loads(p.read_text(encoding="utf-8"))


def read_csv(path):
    p=Path(path)
    if not p.exists(): return []
    with p.open(encoding="utf-8-sig",newline="") as f: return list(csv.DictReader(f))


def write_csv(path,rows,fields):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)


def read_jsonl(path):
    p=Path(path)
    if not p.exists(): return []
    out=[]
    for line_no,line in enumerate(p.read_text(encoding="utf-8").splitlines(),1):
        if line.strip(): out.append((line_no,json.loads(line)))
    return out


def year_from_date(value):
    m=re.match(r"^\s*(\d{4})",str(value or ""))
    return int(m.group(1)) if m else None


def int_year(value):
    try: return int(str(value)[:4])
    except Exception: return None


def event_role(event_type):
    if event_type=="DISCLOSURE_DEFINITION_CHANGE": return "COMPARABILITY_MARKER"
    if event_type in {"SITE_IDENTITY_CHANGE","CORPORATE_RESTRUCTURE"}: return "IDENTITY_MARKER"
    if event_type in {"INTEGRATED_PERMIT","REGULATION_EFFECTIVE_CHANGE"}: return "BASELINE_MARKER"
    return "CONTEXT_MARKER"


def comparability_action(event_type):
    if event_type=="DISCLOSURE_DEFINITION_CHANGE": return "SEGMENT_AT_EVENT"
    if event_type=="REGULATION_EFFECTIVE_CHANGE": return "REVIEW_SEGMENT_AT_EVENT"
    if event_type in {"SITE_IDENTITY_CHANGE","CORPORATE_RESTRUCTURE"}: return "REVIEW_IDENTITY_MAPPING"
    return "CONTEXT_ONLY"


def validation(company_id,object_type,object_key,issue_type,severity,evidence,action,notes=""):
    vid=stable_id("VAL_",company_id,object_type,object_key,issue_type)
    return {"validation_id":vid,"company_id":company_id,"object_type":object_type,"object_key":object_key,
            "issue_type":issue_type,"severity":severity,"detected_by":"EVENT_ANALYSIS_RULE","evidence":evidence,
            "recommended_action":action,"status":"REVIEW_REQUIRED","resolved_by":"","resolved_at":"","notes":notes}


def merge_validations(package_root,new_rows):
    package_root=Path(package_root); qpath=package_root/"Validation_Queue.csv"; rpath=package_root/"REVIEW_REQUIRED.json"
    existing=read_csv(qpath); by_id={r.get("validation_id"):r for r in existing if r.get("validation_id")}
    order=[r.get("validation_id") for r in existing if r.get("validation_id")]
    for row in new_rows:
        vid=row["validation_id"]
        if vid in by_id:
            old=by_id[vid]
            # Never erase a human resolution during reruns.
            if old.get("status") in {"RESOLVED","ACCEPTED_RISK","REJECTED"}: continue
            for k,v in row.items():
                if not old.get(k) and v not in {None,""}: old[k]=v
        else:
            by_id[vid]=row; order.append(vid)
    write_csv(qpath,[by_id[x] for x in order],VALIDATION_FIELDS)
    review=read_json(rpath,[]) or []
    rids={x.get("validation_id") for x in review if isinstance(x,dict) and x.get("validation_id")}
    for row in new_rows:
        if row["validation_id"] not in rids:
            review.append(row); rids.add(row["validation_id"])
    rpath.write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding="utf-8")


def resolve_event_site(event,source_identity,confirmed_sites):
    sid=str(event.get("canonical_site_id") or "").strip()
    if sid:
        return sid if sid in confirmed_sites else ""
    ref=event.get("source_site_ref") or {}
    sk=str(ref.get("source_key") or ""); source_id=str(ref.get("source_site_id") or "")
    if not sk or not source_id: return ""
    row=source_identity.get((sk,source_id))
    if row and row.get("match_status")=="CONFIRMED": return row.get("canonical_site_id","")
    return ""


def integrate_events(package_root,evidence_path=None):
    root=Path(package_root)
    summary=read_json(root/"Integration_Summary.json",{}) or {}; company_id=summary.get("company_id","")
    sites=read_csv(root/"Site_Master.csv"); confirmed_sites={r["canonical_site_id"] for r in sites if r.get("identity_status")=="CONFIRMED"}
    identities=read_csv(root/"Source_Identity.csv")
    source_identity={(r.get("source_key",""),r.get("source_site_id","")):r for r in identities}
    coverage=read_csv(root/"Coverage_Status.csv")
    coverage_by_source={r.get("source_key"):r for r in coverage}
    evidence=read_json(evidence_path,{}) if evidence_path and Path(evidence_path).exists() else None
    validations=[]; events=[]
    if evidence is None:
        validations.append(validation(company_id,"EVENT_DISCOVERY",company_id,"EVENT_DISCOVERY_NOT_RUN","MEDIUM",
            "No event_evidence input was supplied for this run.","Run official-source event discovery; absence of a search is not evidence of no event."))
        evidence={"discovery_status":"NOT_RUN","events":[],"gaps":[]}
    for gap in evidence.get("gaps",[]) or []:
        key=str(gap.get("gap_id") or gap.get("source_key") or gap.get("query") or "UNKNOWN_GAP")
        validations.append(validation(company_id,"EVENT_DISCOVERY",key,"EVENT_DISCOVERY_GAP",str(gap.get("severity") or "MEDIUM"),
            json.dumps(gap,ensure_ascii=False),"Resolve the source/auth/search gap or retain it explicitly; do not convert it to 'no event'."))
    for raw in evidence.get("events",[]) or []:
        et=str(raw.get("event_type") or "UNKNOWN_EVENT"); locator=str(raw.get("source_locator") or "").strip()
        date_start=str(raw.get("event_date_start") or "").strip(); date_end=str(raw.get("event_date_end") or "").strip()
        sid=resolve_event_site(raw,source_identity,confirmed_sites)
        scope=str(raw.get("event_scope") or ("SITE" if raw.get("canonical_site_id") or raw.get("source_site_ref") else "COMPANY"))
        event_id=str(raw.get("event_id") or stable_id("EVT_",company_id,et,date_start,locator,raw.get("event_title"),sid))
        verified=str(raw.get("verification_status") or "NOT_VERIFIED")
        notes=str(raw.get("notes") or "")
        if scope=="SITE" and not sid:
            validations.append(validation(company_id,"EVENT",event_id,"EVENT_SITE_UNRESOLVED","HIGH",
                f"event_type={et}; supplied site reference could not resolve to a CONFIRMED canonical site",
                "Resolve the official source site to a confirmed canonical_site_id; do not weak-merge."))
        if not locator:
            validations.append(validation(company_id,"EVENT",event_id,"TRACEABILITY_GAP","HIGH",
                f"event_type={et}; source_locator missing","Add an official source locator before treating the event as verified."))
        if not date_start:
            validations.append(validation(company_id,"EVENT",event_id,"EVENT_DATE_UNVERIFIED","HIGH",
                f"event_type={et}; actual event/effective date missing","Verify the actual effective/event date; do not infer it from publication or snapshot date."))
        if verified not in {"VERIFIED","SOURCE_VERIFIED"}:
            validations.append(validation(company_id,"EVENT",event_id,"EVENT_NOT_VERIFIED","MEDIUM",
                f"verification_status={verified}","Verify the event against an official primary source before analytical use."))
        events.append({"event_id":event_id,"company_id":company_id,"canonical_site_id":sid,"event_scope":scope,"event_type":et,
            "event_date_start":date_start,"event_date_end":date_end,"event_title":str(raw.get("event_title") or ""),
            "event_description":str(raw.get("event_description") or ""),"source_key":str(raw.get("source_key") or ""),
            "source_locator":locator,"verification_status":verified,"analysis_role":str(raw.get("analysis_role") or event_role(et)),
            "causality_status":"NO_CAUSAL_CLAIM","notes":notes,
            "affected_sources":raw.get("affected_sources") or []})
    # event_id dedupe: retain first row and only fill blanks from later evidence.
    dedup={}; order=[]
    for e in events:
        eid=e["event_id"]
        if eid not in dedup: dedup[eid]=e; order.append(eid)
        else:
            for k,v in e.items():
                if not dedup[eid].get(k) and v not in {None,"",[]}: dedup[eid][k]=v
    events=[dedup[x] for x in order]
    write_csv(root/"Event_Registry.csv",events,EVENT_FIELDS)

    links=[]; baseline_validations=[]
    source_sites=defaultdict(set)
    for r in identities:
        if r.get("canonical_site_id") and r.get("match_status")=="CONFIRMED": source_sites[r.get("source_key")].add(r.get("canonical_site_id"))
    for e in events:
        affected=[str(x) for x in (e.get("affected_sources") or []) if str(x) in CORE_SOURCES]
        if affected: link_sources=affected
        elif e["event_scope"]=="SITE" and e.get("canonical_site_id"):
            link_sources=[s for s in CORE_SOURCES if e["canonical_site_id"] in source_sites[s]]
        else: link_sources=list(CORE_SOURCES)
        event_year=year_from_date(e.get("event_date_start"))
        for s in link_sources:
            c=coverage_by_source.get(s,{})
            cs=int_year(c.get("collected_start")); ce=int_year(c.get("collected_end"))
            if event_year is None or cs is None: baseline="UNKNOWN"
            elif cs <= event_year-1: baseline="BASELINE_AVAILABLE"
            else: baseline="BASELINE_MISSING"
            action=comparability_action(e["event_type"])
            lid=stable_id("LNK_",company_id,s,e.get("canonical_site_id"),e["event_id"])
            links.append({"link_id":lid,"company_id":company_id,"source_key":s,"canonical_site_id":e.get("canonical_site_id","") ,
                "event_id":e["event_id"],"event_type":e["event_type"],"event_date":e.get("event_date_start","") ,
                "event_year":event_year or "UNKNOWN","collected_start":c.get("collected_start","UNKNOWN"),"collected_end":c.get("collected_end","UNKNOWN"),
                "relevance_basis":"EXPLICIT_AFFECTED_SOURCE" if affected else ("CONFIRMED_SITE_SOURCE_LINK" if e["event_scope"]=="SITE" else "COMPANY_SCOPE"),
                "baseline_status":baseline,"comparability_action":action,"causality_status":"NO_CAUSAL_CLAIM",
                "verification_status":e.get("verification_status","") ,"notes":"Event link proposes an analysis window only; it never truncates collected raw data."})
            if baseline=="BASELINE_MISSING" and e["event_type"] in {"INTEGRATED_PERMIT","REGULATION_EFFECTIVE_CHANGE","DISCLOSURE_DEFINITION_CHANGE","SITE_IDENTITY_CHANGE","CORPORATE_RESTRUCTURE"}:
                baseline_validations.append(validation(company_id,"COVERAGE_EVENT",lid,"EVENT_BASELINE_MISSING","HIGH",
                    f"source={s}; event={e['event_id']}; collected_start={cs}; event_year={event_year}",
                    "Extend the collection window earlier if public data exists; keep collection period distinct from analysis period."))
    write_csv(root/"Coverage_Event_Links.csv",links,LINK_FIELDS)
    validations.extend(baseline_validations)

    links_by_source=defaultdict(list)
    for l in links: links_by_source[l["source_key"]].append(l)
    for c in coverage:
        ls=links_by_source.get(c.get("source_key"),[])
        if not ls: c["event_baseline_status"]="NO_EVENT_LINKS"
        elif any(x["baseline_status"]=="BASELINE_MISSING" for x in ls): c["event_baseline_status"]="BASELINE_MISSING"
        elif all(x["baseline_status"]=="BASELINE_AVAILABLE" for x in ls): c["event_baseline_status"]="BASELINE_AVAILABLE"
        else: c["event_baseline_status"]="BASELINE_UNKNOWN"
        actions={x["comparability_action"] for x in ls}
        if "SEGMENT_AT_EVENT" in actions:
            old=c.get("comparability_status","")
            c["comparability_status"]="SEGMENT_REQUIRED" if old in {"","PENDING"} else old+"|SEGMENT_REQUIRED"
        elif "REVIEW_SEGMENT_AT_EVENT" in actions:
            old=c.get("comparability_status","")
            c["comparability_status"]="EVENT_REVIEW" if old in {"","PENDING"} else old+"|EVENT_REVIEW"
    if coverage:
        write_csv(root/"Coverage_Status.csv",coverage,list(coverage[0].keys()))
    merge_validations(root,validations)
    return {"event_discovery_status":str(evidence.get("discovery_status") or "UNKNOWN"),"events":len(events),"event_links":len(links),"event_validations_added":len({v['validation_id'] for v in validations})}


def analysis_state(identity_status,coverage_status,comparability_status):
    if identity_status!="CONFIRMED": return "IDENTITY_REVIEW",False
    if coverage_status not in {"MEETS_MINIMUM","MEETS_MINIMUM_WITH_REVIEW","FULL_HISTORY_CURRENTLY"}: return "COVERAGE_REVIEW",False
    comp=str(comparability_status or "")
    if any(x in comp for x in ["PENDING","REVIEW","TRANSITION","SEGMENT_REQUIRED"]): return "COMPARABILITY_REVIEW",False
    return "READY",True


def build_analysis_index(package_root):
    root=Path(package_root); output=root/"output"
    company_id=(read_json(root/"Integration_Summary.json",{}) or {}).get("company_id","")
    identities=read_csv(root/"Source_Identity.csv")
    imap={(r.get("source_key",""),r.get("source_site_id","")):r for r in identities}
    coverage={r.get("source_key"):r for r in read_csv(root/"Coverage_Status.csv")}
    event_links=defaultdict(list)
    for r in read_csv(root/"Coverage_Event_Links.csv"):
        event_links[(r.get("source_key",""),r.get("canonical_site_id",""))].append(r.get("link_id",""))
    semantics={
        "ENVINFO":"SOURCE_NATIVE_VALUES",
        "PRTR":"SOURCE_NATIVE_OFFICIAL_VALUES_NO_RECALC",
        "CHEM_STATS":"SOURCE_NATIVE_SURVEY_ROUND_NO_INTERPOLATION",
        "CLEANSYS_AIR":"PRESERVE_ZERO_NULL",
        "SOOSIRO_WATER":"PRESERVE_ZERO_NULL_DASH_COD_TOC_PROVISIONAL"
    }
    rows=[]
    def add(source,source_id,time_key,granularity,locator,notes=""):
        ident=imap.get((source,str(source_id)),{}); identity_status=ident.get("match_status","UNRESOLVED")
        sid=ident.get("canonical_site_id","") if identity_status=="CONFIRMED" else ""
        cov=coverage.get(source,{})
        state,eligible=analysis_state(identity_status,cov.get("coverage_status","UNKNOWN"),cov.get("comparability_status",""))
        aid=stable_id("ANL_",company_id,source,source_id,time_key,granularity,locator)
        rows.append({"analysis_id":aid,"company_id":company_id,"canonical_site_id":sid,"source_key":source,"source_site_id":str(source_id),
            "time_key":str(time_key or "UNKNOWN"),"granularity":granularity,"raw_locator":locator,"identity_status":identity_status,
            "coverage_status":cov.get("coverage_status","UNKNOWN"),"comparability_status":cov.get("comparability_status","UNKNOWN"),
            "event_link_ids":"|".join(sorted(x for x in event_links.get((source,sid),[]) if x)),"raw_semantics":semantics[source],
            "analysis_readiness":state,"analysis_eligible":eligible,"notes":notes})
    for i,r in enumerate(read_csv(output/"ENVINFO"/"discovery.csv"),2):
        add("ENVINFO",r.get("compId"),r.get("year"),"SITE_YEAR",f"output/ENVINFO/discovery.csv#row={i}")
    for i,r in enumerate(read_csv(output/"PRTR"/"discovery.csv"),2):
        add("PRTR",r.get("entrps_id"),r.get("search_year"),"SITE_YEAR",f"output/PRTR/discovery.csv#row={i}","Official totals/values remain in source artifacts; index does not recalculate them.")
    for i,r in enumerate(read_csv(output/"CHEM_STATS"/"discovery.csv"),2):
        add("CHEM_STATS",r.get("bplcId"),r.get("search_year") or r.get("reportYear"),"SITE_SURVEY_ROUND",f"output/CHEM_STATS/discovery.csv#row={i}")
    for line,r in read_jsonl(output/"CLEANSYS_AIR"/"annual_rows.jsonl"):
        add("CLEANSYS_AIR",r.get("source_fact_code") or r.get("fact_code"),r.get("examin_year"),"SITE_YEAR",f"output/CLEANSYS_AIR/annual_rows.jsonl#line={line}")
    for line,r in read_jsonl(output/"SOOSIRO_WATER"/"annual_rows.jsonl"):
        add("SOOSIRO_WATER",r.get("source_fact_code") or r.get("FACT_CODE"),r.get("YEAR",r.get("year")),"SITE_YEAR",f"output/SOOSIRO_WATER/annual_rows.jsonl#line={line}")
    for line,r in read_jsonl(output/"SOOSIRO_WATER"/"daily_rows.jsonl"):
        tk=f"{r.get('YEAR','UNKNOWN')}:{r.get('DAY','UNKNOWN')}"
        add("SOOSIRO_WATER",r.get("source_fact_code") or r.get("FACT_CODE"),tk,"SITE_DAY",f"output/SOOSIRO_WATER/daily_rows.jsonl#line={line}","COD and TOC remain separate source-native fields in the referenced raw row.")
    write_csv(root/"Analysis_Ready_Index.csv",rows,ANALYSIS_FIELDS)
    return {"analysis_index_rows":len(rows),"analysis_ready_rows":sum(str(r["analysis_eligible"]).lower()=="true" or r["analysis_eligible"] is True for r in rows)}


def run_event_analysis(package_root,evidence_path=None):
    e=integrate_events(package_root,evidence_path); a=build_analysis_index(package_root); return {**e,**a}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--package",default="assembled"); ap.add_argument("--events",default="requests/event_evidence.json")
    args=ap.parse_args(); event_path=args.events if Path(args.events).exists() else None
    print(json.dumps(run_event_analysis(args.package,event_path),ensure_ascii=False))

if __name__=="__main__": main()
