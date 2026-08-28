import argparse, csv, json, shutil
from pathlib import Path

import archive_builder
from archive_builder import build_archive, archive_file_index, write_csv, sha256
from archive_zip_dedup import run as deduplicate_archive_zip
from requested_scope import source_id_scope as requested_source_id_scope
from postprocess import stable_id

VALIDATION_FIELDS=["validation_id","company_id","object_type","object_key","issue_type","severity","detected_by","evidence","recommended_action","status","resolved_by","resolved_at","notes"]


def read_json(path,default=None):
    p=Path(path); return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def read_csv(path):
    p=Path(path)
    if not p.exists() or p.stat().st_size==0: return []
    with p.open(encoding="utf-8-sig",newline="") as f: return list(csv.DictReader(f))


def make_validation(company_id,obj,key,issue,severity,evidence,action,notes=""):
    return {"validation_id":stable_id("VAL_",company_id,obj,key,issue),"company_id":company_id,"object_type":obj,"object_key":key,"issue_type":issue,"severity":severity,"detected_by":"ARCHIVE_STAGE_RULE","evidence":evidence,"recommended_action":action,"status":"REVIEW_REQUIRED","resolved_by":"","resolved_at":"","notes":notes}


def merge_validations(package_root,new_rows):
    root=Path(package_root); q=root/"Validation_Queue.csv"; r=root/"REVIEW_REQUIRED.json"
    existing=read_csv(q); by_id={x.get("validation_id"):x for x in existing if x.get("validation_id")}; order=[x for x in by_id]
    for row in new_rows:
        vid=row["validation_id"]
        if vid in by_id:
            if by_id[vid].get("status") in {"RESOLVED","ACCEPTED_RISK","REJECTED"}: continue
            for k,v in row.items():
                if not by_id[vid].get(k) and v not in (None,""): by_id[vid][k]=v
        else: by_id[vid]=row; order.append(vid)
    with q.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=VALIDATION_FIELDS,extrasaction="ignore"); w.writeheader(); w.writerows([by_id[x] for x in order])
    review=read_json(r,[]) or []; resolved={x.get("validation_id") for x in [by_id.get(k,{}) for k in order] if x.get("status") in {"RESOLVED","ACCEPTED_RISK","REJECTED"}}
    kept=[x for x in review if not isinstance(x,dict) or x.get("validation_id") not in resolved]; seen={x.get("validation_id") for x in kept if isinstance(x,dict)}
    for row in new_rows:
        if row["validation_id"] not in seen and row["validation_id"] not in resolved: kept.append(row); seen.add(row["validation_id"])
    r.write_text(json.dumps(kept,ensure_ascii=False,indent=2),encoding="utf-8")


def find_source(stable,source):
    stable=Path(stable)
    for p in [stable/source,stable/"output"/source]:
        if p.exists(): return p
    return None


def copy_document_lane(package_root,stable,evidence):
    root=Path(package_root); src=find_source(stable,"CORP_DOCS")
    if src:
        dst=root/"output"/"CORP_DOCS"
        if dst.exists(): shutil.rmtree(dst)
        shutil.copytree(src,dst)
    if evidence and Path(evidence).exists(): shutil.copy2(evidence,root/"Document_Evidence.json")


def document_reviews(package_root):
    root=Path(package_root); summary=read_json(root/"Integration_Summary.json",{}) or {}; company_id=str(summary.get("company_id") or "")
    vals=[]; env=read_json(root/"output"/"ENVINFO"/"status.json",{}) or {}; docs=read_json(root/"output"/"CORP_DOCS"/"status.json",{}) or {}
    if int(env.get("attachment_fail") or 0)>0:
        vals.append(make_validation(company_id,"ENVINFO_ATTACHMENT","ENVINFO","ENVINFO_ATTACHMENT_DOWNLOAD_INCOMPLETE","HIGH",f"discovered={env.get('attachments_discovered',0)}; downloaded={env.get('attachment_ok',0)}; failed={env.get('attachment_fail',0)}","Retry failed public attachments; retain successful raw files and attachment index."))
    dstatus=str(docs.get("status") or "MISSING_STATUS")
    if dstatus in {"MISSING_STATUS","NOT_RUN"}:
        vals.append(make_validation(company_id,"DOCUMENT_DISCOVERY","CORP_DOCS","DOCUMENT_DISCOVERY_NOT_RUN","MEDIUM",f"status={dstatus}","Run official-source document discovery before declaring the human archive complete."))
    elif dstatus=="INVALID_SCOPE":
        vals.append(make_validation(company_id,"DOCUMENT_DISCOVERY","CORP_DOCS","DOCUMENT_EVIDENCE_SCOPE_MISMATCH","HIGH",f"expected={docs.get('request_id','')}; supplied={docs.get('supplied_request_id','')}","Supply document evidence with the same request_id as the current company run; do not apply stale documents."))
    if int(docs.get("failed") or 0)>0:
        vals.append(make_validation(company_id,"DOCUMENT_DOWNLOAD","CORP_DOCS","DOCUMENT_DOWNLOAD_INCOMPLETE","HIGH",f"declared={docs.get('documents_declared',0)}; downloaded={docs.get('downloaded',0)}; failed={docs.get('failed',0)}","Retry failed official documents or retain the access gap explicitly."))
    if int(docs.get("gaps") or 0)>0:
        vals.append(make_validation(company_id,"DOCUMENT_DISCOVERY","CORP_DOCS","DOCUMENT_DISCOVERY_GAP","MEDIUM",f"gaps={docs.get('gaps',0)}","Review unresolved official-source document coverage; a search gap is not evidence of no document."))
    index=read_csv(root/"output"/"CORP_DOCS"/"document_index.csv")
    skipped=sum(1 for x in index if str(x.get("collection_status") or "").startswith("SKIPPED_"))
    if skipped:
        vals.append(make_validation(company_id,"DOCUMENT_EVIDENCE","CORP_DOCS","DOCUMENT_EVIDENCE_SKIPPED","MEDIUM",f"skipped_documents={skipped}","Verify or safely reclassify skipped document evidence; executable/script payloads remain prohibited."))
    return vals,docs,env


def write_artifact_index(path,rows):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["source","path","bytes","sha256"]); w.writeheader(); w.writerows(rows)


def append_artifact_rows(package_root):
    root=Path(package_root); p=root/"Artifact_Index.csv"; rows=read_csv(p); seen={x.get("path") for x in rows}
    for candidate in [root/"Document_Evidence.json",root/"Requested_Scope.json",root/"Analysis_Scope.csv"]:
        if candidate.exists():
            rel=str(candidate.relative_to(root))
            if rel not in seen: rows.append({"source":"DOCUMENT" if candidate.name=="Document_Evidence.json" else "INTEGRATION","path":rel,"bytes":candidate.stat().st_size,"sha256":sha256(candidate)}); seen.add(rel)
    source=root/"output"/"CORP_DOCS"
    if source.exists():
        for file in sorted(source.rglob("*")):
            if file.is_file():
                rel=str(file.relative_to(root))
                if rel not in seen: rows.append({"source":"CORP_DOCS","path":rel,"bytes":file.stat().st_size,"sha256":sha256(file)}); seen.add(rel)
    write_artifact_index(p,rows)
    return len(rows)


def add_archive_zip_to_artifact_index(package_root,zip_path):
    root=Path(package_root).resolve(); p=root/"Artifact_Index.csv"; rows=read_csv(p); rel=str(Path(zip_path).resolve().relative_to(root)); rows=[x for x in rows if x.get("path")!=rel]
    rows.append({"source":"HUMAN_ARCHIVE","path":rel,"bytes":Path(zip_path).stat().st_size,"sha256":sha256(zip_path)})
    write_artifact_index(p,rows)
    return len(rows)


def refresh_manifest(package_root,docs,env,artifact_count):
    root=Path(package_root); manifest=read_json(root/"Master_Manifest.json",{}) or {}; review=read_json(root/"REVIEW_REQUIRED.json",[]) or []
    # Preserve the schema version written by package_run.py. Archive stage only adds
    # document_lane/envinfo_attachments/human_archive fields on top; it must never regress
    # the package schema to an older version.
    manifest.setdefault("schema_version","1.6")
    manifest["review_count"]=len(review); manifest["validation"]="REVIEW_REQUIRED" if review else "PASS"; manifest["artifact_count"]=artifact_count
    manifest["document_lane"]={"status":docs.get("status","NOT_RUN"),"documents_declared":docs.get("documents_declared",0),"downloaded":docs.get("downloaded",0),"failed":docs.get("failed",0),"skipped":docs.get("skipped",0),"gaps":docs.get("gaps",0)}
    manifest["envinfo_attachments"]={"discovered":env.get("attachments_discovered",0),"downloaded":env.get("attachment_ok",0),"failed":env.get("attachment_fail",0),"bytes":env.get("attachment_bytes",0)}
    manifest["human_archive"]={"status":"BUILDING","summary_file":"Archive_Summary.json","zip_file":"Human_Archive.zip"}
    root.joinpath("Master_Manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    integ=read_json(root/"Integration_Summary.json",{}) or {}; integ["validation_queue"]=len(read_csv(root/"Validation_Queue.csv")); root.joinpath("Integration_Summary.json").write_text(json.dumps(integ,ensure_ascii=False,indent=2),encoding="utf-8")
    return manifest


def finalize_archive_manifest(package_root,manifest,archive_summary):
    root=Path(package_root).resolve()
    stable={k:v for k,v in archive_summary.items() if k not in {"zip_sha256","zip_bytes"}}
    stable["status"]="PASS"; stable["summary_file"]="Archive_Summary.json"; stable["zip_file"]="Human_Archive.zip"
    manifest["human_archive"]=stable
    root.joinpath("Master_Manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    archive=root/"Human_Archive"/archive_summary["archive_root"]; idx=archive/"00_자료목록"
    shutil.copy2(root/"Master_Manifest.json",idx/"Master_Manifest.json")
    # build_archive() copied the pre-finalization BUILDING snapshot into the system raw
    # control-plane folder. Keep both manifest copies inside the same final zip aligned.
    system_manifest=archive/"90_시스템원본"/"control_plane"/"Master_Manifest.json"
    if system_manifest.parent.exists():
        shutil.copy2(root/"Master_Manifest.json",system_manifest)
    for extra in [root/"Requested_Scope.json",root/"Analysis_Scope.csv"]:
        if extra.exists(): shutil.copy2(extra,idx/extra.name)
    file_rows=archive_file_index(archive); write_csv(idx/"Archive_File_Index.csv",file_rows,["path","bytes","sha256"])
    zip_path=root/"Human_Archive.zip"
    if zip_path.exists(): zip_path.unlink()
    zip_path=Path(shutil.make_archive(str(root/"Human_Archive"),"zip",root_dir=root/"Human_Archive",base_dir=archive.name)).resolve()
    final={**archive_summary,"archive_files":len(file_rows),"zip_path":str(zip_path.relative_to(root)),"zip_bytes":zip_path.stat().st_size,"zip_sha256":sha256(zip_path)}
    root.joinpath("Archive_Summary.json").write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding="utf-8")
    return final


def run(package_root,stable,evidence=None):
    root=Path(package_root).resolve(); copy_document_lane(root,stable,evidence)
    vals,docs,env=document_reviews(root); merge_validations(root,vals)
    count=append_artifact_rows(root); manifest=refresh_manifest(root,docs,env,count)
    # Archive v2 must use the exact same requested-scope resolver as Analysis.
    # This only affects human-facing copies; the source package remains legal-entity-wide.
    archive_builder.source_id_scope=requested_source_id_scope
    summary=build_archive(root); final=finalize_archive_manifest(root,manifest,summary)
    # Human Archive keeps user-facing files directly accessible, while identical binary
    # copies under 90_시스템원본 are replaced by a SHA-256 reference table. The complete
    # raw package remains in the enterprise-env-final/stable-source artifacts.
    deduplicate_archive_zip(root)
    final=read_json(root/"Archive_Summary.json",final) or final
    artifact_count=add_archive_zip_to_artifact_index(root,root/final["zip_path"])
    manifest=read_json(root/"Master_Manifest.json",{}) or {}; manifest["artifact_count"]=artifact_count
    root.joinpath("Master_Manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    # Final GitHub artifact keeps the validated core package plus one compact Human_Archive.zip.
    # The expanded human folder is intentionally removed to avoid duplicate delivery copies.
    shutil.rmtree(root/"Human_Archive",ignore_errors=True)
    print(json.dumps({"archive_health":"PASS","archive":final,"validations_added":len(vals)},ensure_ascii=False))
    return final


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--package",default="assembled"); ap.add_argument("--stable",default="collected/stable"); ap.add_argument("--documents",default="requests/document_evidence.json"); args=ap.parse_args()
    run(args.package,args.stable,args.documents if Path(args.documents).exists() else None)


if __name__=="__main__": main()
