import argparse, csv, hashlib, json, shutil
from pathlib import Path

BAD={"REMOTE_HOST_UNREACHABLE","REQUEST_OR_PARSE_FAILED","CONFIG_ERROR"}
SOURCES=["ENVINFO","PRTR","CHEM_STATS","CLEANSYS_AIR","SOOSIRO_WATER"]


def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def sha256(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()


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
        # artifact download may either contain source dirs directly or one nested output dir.
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
            results[s]={"status":"MISSING_STATUS"}; ok=False; continue
        st=read_json(sp); status=st.get("status")
        checks=[]
        if status in BAD: checks.append("terminal_failure")
        if s=="ENVINFO" and status=="DATA_FOUND" and st.get("detail_fail",0)!=0: checks.append("detail_missing")
        if s=="PRTR" and status=="DATA_FOUND" and st.get("detail_fail",0)!=0: checks.append("detail_missing")
        if s=="CHEM_STATS" and status=="DATA_FOUND" and st.get("detail_fail",0)!=0: checks.append("detail_missing")
        zero=[]
        for p in (root/s).rglob("*"):
            if p.is_file() and p.stat().st_size==0: zero.append(str(p.relative_to(root)))
        if zero: checks.append("zero_byte_artifact")
        if checks: ok=False; review.append({"source":s,"issues":checks,"zero_byte":zero})
        results[s]={"status":status,"years":years_from_source(root,s),"checks":checks,**{k:v for k,v in st.items() if k not in {"status"}}}
    return ok,results,review


def artifact_index(root):
    out=[]
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel=p.relative_to(root); source=rel.parts[0] if rel.parts else ""
            out.append({"source":source,"path":str(rel),"bytes":p.stat().st_size,"sha256":sha256(p)})
    return out


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--stable",default="collected/stable"); ap.add_argument("--icis",default="collected/icis"); ap.add_argument("--out",default="assembled")
    args=ap.parse_args(); stable=Path(args.stable); icis=Path(args.icis); out=Path(args.out); output=out/"output"
    if out.exists(): shutil.rmtree(out)
    output.mkdir(parents=True,exist_ok=True)
    for s in ["ENVINFO","CLEANSYS_AIR","SOOSIRO_WATER"]:
        copy_source(stable,output,s) or copy_source(stable/"output",output,s)
    chosen=choose_icis(icis)
    if chosen:
        for s in ["PRTR","CHEM_STATS"]: copy_source(chosen,output,s)
    ok,statuses,review=validate(output)
    idx=artifact_index(output)
    (out/"Master_Manifest.json").write_text(json.dumps({"schema_version":"1.0","validation":"PASS" if ok else "REVIEW_REQUIRED","selected_icis_attempt":str(chosen) if chosen else None,"sources":statuses,"artifact_count":len(idx)},ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"REVIEW_REQUIRED.json").write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding="utf-8")
    with (out/"Artifact_Index.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=["source","path","bytes","sha256"]); w.writeheader(); w.writerows(idx)
    with (out/"Coverage_Matrix.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=["source","status","years","checks"]); w.writeheader()
        for s,r in statuses.items(): w.writerow({"source":s,"status":r.get("status"),"years":"|".join(r.get("years",[])),"checks":"|".join(r.get("checks",[]))})
    print(json.dumps({"validation":"PASS" if ok else "REVIEW_REQUIRED","selected_icis_attempt":str(chosen) if chosen else None,"artifacts":len(idx)},ensure_ascii=False))
    raise SystemExit(0 if ok else 81)

if __name__=="__main__": main()
