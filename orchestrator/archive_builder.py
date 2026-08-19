import csv, hashlib, json, re, shutil
from datetime import datetime, timezone
from pathlib import Path

CONTRACT_PATH = Path(__file__).with_name("archive_contract.json")
CORE_SOURCE_FOLDERS = {
    "CLEANSYS_AIR": "01_TMS/대기_CleanSYS",
    "SOOSIRO_WATER": "01_TMS/수질_SOOSIRO",
    "PRTR": "02_화학물질/PRTR_배출이동량",
    "CHEM_STATS": "02_화학물질/화학물질통계",
    "ENVINFO": "03_환경정보공개시스템",
}
ROOT_INDEX_FILES = [
    "Company_Profile.json", "Company_Discovery_Summary.json", "Master_Manifest.json", "Artifact_Index.csv",
    "Site_Master.csv", "Source_Identity.csv", "Coverage_Status.csv", "Coverage_Matrix.csv", "Validation_Queue.csv",
    "Event_Registry.csv", "Coverage_Event_Links.csv", "Analysis_Ready_Index.csv", "REVIEW_REQUIRED.json"
]
DOCUMENT_FIELDS = [
    "document_id","company_id","canonical_site_id","site_name_raw","source_key","document_type","document_category",
    "importance","title","report_year","coverage_start","coverage_end","publication_date","original_filename",
    "archive_path","source_locator","retrieved_at","bytes","sha256","content_type","verification_status",
    "collection_status","notes"
]
COVERAGE_FIELDS = ["source_key","category","status","years","found_files","failed_files","notes"]


def safe(value):
    text=re.sub(r"[\\/:*?\"<>|\x00-\x1f]+","_",str(value or "")).strip(" ._")
    return text[:160] or "자료"


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


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()


def copy_file(src,dst):
    src=Path(src); dst=Path(dst); dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst); return dst


def unique_copy(src,directory,name=None):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True); src=Path(src)
    target=directory/safe(name or src.name)
    if not target.exists(): return copy_file(src,target)
    if sha256(src)==sha256(target): return target
    suffix=target.suffix; stem=target.stem; n=2
    while True:
        candidate=directory/f"{stem}__{n}{suffix}"
        if not candidate.exists(): return copy_file(src,candidate)
        n+=1


def canonical_envinfo_map(package_root):
    out={}
    for row in read_csv(Path(package_root)/"Source_Identity.csv"):
        if row.get("source_key")=="ENVINFO" and row.get("match_status")=="CONFIRMED":
            out[str(row.get("source_site_id") or "")]=str(row.get("canonical_site_id") or "")
    return out


def source_raw_copy(package_root,archive_root):
    package_root=Path(package_root); output=package_root/"output"
    for source,folder in CORE_SOURCE_FOLDERS.items():
        src=output/source
        if not src.exists(): continue
        dst=archive_root/folder/"원본"
        if dst.exists(): shutil.rmtree(dst)
        shutil.copytree(src,dst)


def archive_envinfo(package_root,archive_root,company_id):
    package_root=Path(package_root); env=package_root/"output"/"ENVINFO"; rows=[]; cmap=canonical_envinfo_map(package_root)
    for att in read_csv(env/"attachment_index.csv"):
        src=package_root/str(att.get("stored_path") or "")
        site=safe(att.get("compNm") or att.get("compId") or "미상사업장"); year=safe(att.get("year") or "연도미상")
        archive_path=""
        if att.get("collection_status")=="DOWNLOADED" and src.exists():
            copied=unique_copy(src,archive_root/"03_환경정보공개시스템"/site/year/"첨부파일",att.get("original_filename") or src.name)
            archive_path=str(copied.relative_to(archive_root))
            if att.get("importance")=="CORE":
                core_name=f"{site}_{year}_{att.get('original_filename') or src.name}"
                unique_copy(src,archive_root/"03_환경정보공개시스템"/"핵심자료"/safe(att.get("document_category") or "기타"),core_name)
        rows.append({
            "document_id":f"ENVINFO_{att.get('year')}_{att.get('compId')}_{att.get('file_id')}","company_id":company_id,
            "canonical_site_id":cmap.get(str(att.get("compId") or ""),""),"site_name_raw":att.get("compNm","") ,
            "source_key":"ENVINFO_ATTACHMENT","document_type":"ENVINFO_ATTACHMENT","document_category":att.get("document_category","") ,
            "importance":att.get("importance","UNCLASSIFIED"),"title":att.get("original_filename","") ,"report_year":att.get("year","") ,
            "coverage_start":"","coverage_end":"","publication_date":"","original_filename":att.get("original_filename","") ,
            "archive_path":archive_path,"source_locator":f"https://www.env-info.kr/user/register/viewUserSearch2.do?YEAR={att.get('year','')}&COMP_ID={att.get('compId','')}&OPEN_YN=Y#file_id={att.get('file_id','')}",
            "retrieved_at":"","bytes":att.get("bytes","") ,"sha256":att.get("sha256","") ,"content_type":att.get("content_type","") ,
            "verification_status":"SOURCE_NATIVE","collection_status":att.get("collection_status","") ,
            "notes":f"section={att.get('section_title','')}; {att.get('error','')}".strip("; ")
        })
    discovery=read_csv(env/"discovery.csv")
    detail_dir=env/"raw_detail"
    for d in discovery:
        year=str(d.get("year") or ""); comp=str(d.get("compId") or ""); site=safe(d.get("compNm") or comp)
        matches=list(detail_dir.glob(f"{year}_{safe(comp)}_*.html")) if detail_dir.exists() else []
        if matches:
            unique_copy(matches[0],archive_root/"03_환경정보공개시스템"/site/safe(year or "연도미상"),"상세페이지.html")
    return rows


def archive_corporate_docs(package_root,archive_root,contract,company_id):
    package_root=Path(package_root); source=package_root/"output"/"CORP_DOCS"; rows=[]
    for doc in read_csv(source/"document_index.csv"):
        dtype=str(doc.get("document_type") or "OTHER_OFFICIAL_DOCUMENT")
        target_folder=contract.get("folders",{}).get(dtype,contract.get("folders",{}).get("OTHER_OFFICIAL_DOCUMENT","06_회사환경정책/기타_공식자료"))
        src=package_root/str(doc.get("stored_path") or ""); archive_path=""
        if doc.get("collection_status")=="DOWNLOADED" and src.exists():
            year=safe(doc.get("report_year") or "연도미상")
            copied=unique_copy(src,archive_root/target_folder/year,doc.get("original_filename") or src.name)
            archive_path=str(copied.relative_to(archive_root))
        rows.append({
            "document_id":doc.get("document_id","") ,"company_id":company_id,"canonical_site_id":doc.get("canonical_site_id","") ,
            "site_name_raw":doc.get("site_name_raw","") ,"source_key":"CORP_DOCS","document_type":dtype,"document_category":dtype,
            "importance":doc.get("importance","UNCLASSIFIED"),"title":doc.get("title","") ,"report_year":doc.get("report_year","") ,
            "coverage_start":doc.get("coverage_start","") ,"coverage_end":doc.get("coverage_end","") ,"publication_date":doc.get("publication_date","") ,
            "original_filename":doc.get("original_filename","") ,"archive_path":archive_path,"source_locator":doc.get("source_locator") or doc.get("source_url","") ,
            "retrieved_at":doc.get("retrieved_at","") ,"bytes":doc.get("bytes","") ,"sha256":doc.get("sha256","") ,"content_type":doc.get("content_type","") ,
            "verification_status":doc.get("verification_status","") ,"collection_status":doc.get("collection_status","") ,"notes":doc.get("notes","")
        })
    return rows


def archive_coverage(package_root,document_rows):
    rows=[]
    for c in read_csv(Path(package_root)/"Coverage_Status.csv"):
        rows.append({"source_key":c.get("source_key","") ,"category":"STRUCTURED_SOURCE","status":c.get("coverage_status","") ,
                     "years":"|".join(x for x in [c.get("collected_start",""),c.get("collected_end","")] if x),"found_files":"","failed_files":"","notes":c.get("next_action","")})
    by={}
    for d in document_rows:
        key=d.get("document_type") or d.get("source_key")
        x=by.setdefault(key,{"years":set(),"found":0,"failed":0})
        if d.get("report_year"): x["years"].add(str(d.get("report_year")))
        if d.get("collection_status")=="DOWNLOADED": x["found"]+=1
        elif d.get("collection_status") not in {"","DISCOVERED"}: x["failed"]+=1
    for key,x in sorted(by.items()):
        rows.append({"source_key":key,"category":"DOCUMENT","status":"FOUND" if x["found"] else "NOT_ACQUIRED","years":"|".join(sorted(x["years"])),"found_files":x["found"],"failed_files":x["failed"],"notes":"Document coverage records observed evidence only; absence is not proof that no public document exists."})
    return rows


def copy_index_files(package_root,archive_root):
    index=archive_root/"00_자료목록"; index.mkdir(parents=True,exist_ok=True)
    for name in ROOT_INDEX_FILES:
        p=Path(package_root)/name
        if p.exists(): copy_file(p,index/name)


def archive_file_index(archive_root):
    rows=[]
    for p in sorted(Path(archive_root).rglob("*")):
        if p.is_file() and p.name not in {"Archive_File_Index.csv"}:
            rows.append({"path":str(p.relative_to(archive_root)),"bytes":p.stat().st_size,"sha256":sha256(p)})
    return rows


def build_archive(package_root,contract_path=CONTRACT_PATH):
    package_root=Path(package_root); contract=read_json(contract_path,{}) or {}; profile=read_json(package_root/"Company_Profile.json",{}) or {}
    company_name=str(profile.get("company_display_name") or profile.get("company_input") or "기업"); company_id=str(profile.get("company_id") or (read_json(package_root/"Integration_Summary.json",{}) or {}).get("company_id") or "")
    base=package_root/"Human_Archive"; archive_root=base/(safe(company_name)+"_환경자료")
    if base.exists(): shutil.rmtree(base)
    archive_root.mkdir(parents=True,exist_ok=True)
    source_raw_copy(package_root,archive_root)
    documents=[]; documents.extend(archive_envinfo(package_root,archive_root,company_id)); documents.extend(archive_corporate_docs(package_root,archive_root,contract,company_id))
    copy_index_files(package_root,archive_root)
    write_csv(archive_root/"00_자료목록"/"Document_Index.csv",documents,DOCUMENT_FIELDS)
    coverage=archive_coverage(package_root,documents); write_csv(archive_root/"00_자료목록"/"Source_Coverage.csv",coverage,COVERAGE_FIELDS)
    manifest={
        "schema_version":"1.0","company_id":company_id,"company_display_name":company_name,"created_at":datetime.now(timezone.utc).isoformat(),
        "archive_root":archive_root.name,"document_rows":len(documents),"downloaded_documents":sum(1 for d in documents if d.get("collection_status")=="DOWNLOADED"),
        "core_documents":sum(1 for d in documents if d.get("importance")=="CORE" and d.get("collection_status")=="DOWNLOADED"),
        "coverage_rows":len(coverage),"principles":contract.get("principles",[])
    }
    (archive_root/"00_자료목록"/"Archive_Manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    file_rows=archive_file_index(archive_root); write_csv(archive_root/"00_자료목록"/"Archive_File_Index.csv",file_rows,["path","bytes","sha256"])
    zip_base=package_root/"Human_Archive"
    zip_path=Path(shutil.make_archive(str(zip_base),"zip",root_dir=base,base_dir=archive_root.name))
    summary={**manifest,"archive_files":len(file_rows),"zip_path":str(zip_path.relative_to(package_root)),"zip_bytes":zip_path.stat().st_size,"zip_sha256":sha256(zip_path)}
    (package_root/"Archive_Summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    return summary


if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("package_root",nargs="?",default="assembled"); args=ap.parse_args()
    print(json.dumps(build_archive(args.package_root),ensure_ascii=False,indent=2))
