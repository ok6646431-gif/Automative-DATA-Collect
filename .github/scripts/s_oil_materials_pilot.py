#!/usr/bin/env python3
"""S-OIL evidence-first independent official ESG reports / five public source collector.

User delivery: only actual PDF and XLSX are placed under deliverables; JSON is
internal QA and must NEVER be called a complete user archive.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, re, time, zipfile
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from orchestrator.company_profile_builder import compile_discovery
from orchestrator.request_builder import build

ROOT=Path("soiloil_2026")
REPORT_PAGE="https://www.s-oil.com/sustainability/Report.aspx"
DART="https://englishdart.fss.or.kr/dsbc001/selectPopup.ax?selectKey=00138279"
SITES="https://www.s-oil.com/etc/Map.aspx"
UA="Mozilla/5.0 (compatible; CorporateEnvironmentalEvidenceArchive/1.0; public reports)"
PUBLIC=("ENVINFO","PRTR","CHEM_STATS","CLEANSYS_AIR","SOOSIRO_WATER")

def save(obj,path):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()
def discovery():
    return {
      "schema_version":"1.0","request_id":"soiloil-official-five-source-20261013",
      "requested_company_name":"에쓰오일","current_legal_name":"S-Oil(주)",
      "company_verification_state":"VERIFIED","confidence":"HIGH",
      "requested_scope":{"mode":"COMPANY","label":"S-OIL 법인 및 울산 온산공장 공공자료",
                         "raw_collection_policy":"PRESERVE_COMPANY_WIDE"},
      "company_aliases":[
         {"name":"에쓰-오일 주식회사","alias_type":"legal_name","verification_state":"VERIFIED",
          "source_locator":"https://www.s-oil.com/common/page/FileDownload.aspx?FileName=639130708098893248.pdf&PIndex=16&PathType=BOARD&TFileName=MSDS.pdf"},
         {"name":"에쓰오일","alias_type":"requested_name","verification_state":"VERIFIED",
          "source_locator":REPORT_PAGE},
         {"name":"S-OIL","alias_type":"requested_name","verification_state":"VERIFIED",
          "source_locator":REPORT_PAGE},
      ],
      "identity_evidence":[
         {"source_locator":DART,"source_value_raw":"S-Oil(주), DART 00138279; 법인등록번호 110111-0189955",
          "verification_state":"VERIFIED","confidence":"HIGH"},
         {"source_locator":SITES,"source_value_raw":"S-OIL 온산공장 68 Onsan-ro Ulsan",
          "verification_state":"VERIFIED","confidence":"HIGH"},
      ],
      "domestic_site_candidates":[
         {"candidate_id":"s-oil-onsan-plant","site_name_raw":"온산공장",
          "address_raw":"울산광역시 울주군 온산읍 온산로 68",
          "source_locator":SITES,"identity_status":"CONFIRMED","verification_state":"VERIFIED",
          "discovery_evidence":{"extraction_contract":"STRUCTURED_OFFICIAL_LOCATION_PAGE",
          "evidence_type":"FIRST_PARTY_SITE_ADDRESS"}},
         {"candidate_id":"s-oil-seoul-office","site_name_raw":"본사",
          "address_raw":"서울특별시 마포구 백범로 192",
          "source_locator":SITES,"identity_status":"CONFIRMED","verification_state":"VERIFIED",
          "discovery_evidence":{"extraction_contract":"STRUCTURED_OFFICIAL_LOCATION_PAGE",
          "evidence_type":"FIRST_PARTY_SITE_ADDRESS"}},
      ],
      "related_entity_exclusions":[
         {"name":"에쓰오일토탈에너지스윤활유","verification_state":"VERIFIED",
          "source_locator":"https://www.s-oil.com/sustainability/Report.aspx"}
      ],
      "unresolved_items":[],"event_evidence_references":[],
      "collection_policy":{"minimum_history_years":5,
        "requested_history_window":{"start_year":2020,"end_year":2025},
        "sources":{
          "ENVINFO":{"requested_window":{"start_year":2020,"end_year":2024},
                     "prefer_full_history":False,"max_details":500},
          "PRTR":{"requested_window":{"start_year":2020,"end_year":2024},
                  "prefer_full_history":False},
          "CHEM_STATS":{"available_survey_rounds":[2020,2022,2024],
                        "requested_survey_rounds":[2020,2022,2024],
                        "prefer_full_history":True},
          "CLEANSYS_AIR":{"requested_window":{"start_year":2020,"end_year":2025},
                          "prefer_full_history":False},
          "SOOSIRO_WATER":{"requested_window":{"start_year":2020,"end_year":2025},
                          "daily_available_years":[2024],"prefer_full_history":False},
        }
      }
    }

def setup():
    d=discovery()
    p,summary=compile_discovery(d)
    if summary.get("review_required_count"):raise SystemExit("Source discovery blocked: "+json.dumps(summary,ensure_ascii=False))
    p["requested_scope"]=d["requested_scope"]
    r=build(p)
    if set(r["sources"])!=set(PUBLIC):raise SystemExit("five-source request incomplete")
    sites=r["sources"]["ENVINFO"]["identity_gate"]["verified_sites"]
    if not any(x["site_name"]=="온산공장" and x["address"]=="울산광역시 울주군 온산읍 온산로 68" for x in sites):
        raise SystemExit("Onsan site identity failed")
    save(d,ROOT/"internal"/"discovery.json")
    save(p,ROOT/"internal"/"profile.json")
    save(r,ROOT/"internal"/"request.json")
    print(json.dumps({"legal_entity":d["current_legal_name"],
                      "sites":sites,"sources":list(r["sources"])},ensure_ascii=False),flush=True)

def request_page(session,url,timeout=40):
    for attempt in range(2):
        try:
            r=session.get(url,timeout=(8,timeout),stream=True)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt==1:raise
            time.sleep(1)
def reports():
    root=ROOT/"사람용_보고서"
    root.mkdir(parents=True,exist_ok=True)
    s=requests.Session();s.headers.update({"User-Agent":UA})
    listing=request_page(s,REPORT_PAGE)
    soup=BeautifulSoup(listing.content,"html.parser")
    matches={}
    for a in soup.select("a[href]"):
        href=a.get("href","")
        if "FileDownload.aspx" not in href:continue
        area=a.parent.get_text(" ",strip=True)
        snippet=area+" "+a.get_text(" ",strip=True)
        parent=a
        for _ in range(3):
            if parent.parent:parent=parent.parent;snippet+=" "+parent.get_text(" ",strip=True)[:110]
        year=re.search(r"20(?:2[0-5])\b",snippet)
        if year:
            y=year.group()
            if y not in matches:matches[y]=urljoin(REPORT_PAGE,href)
    print("REPORT_LINKS",json.dumps(matches,ensure_ascii=False),flush=True)
    # Capture a full six-year set only from the official year-index.
    manifest=[]
    for y in map(str,range(2025,2019,-1)):
        url=matches.get(y)
        rec={"year":y,"official_catalog":REPORT_PAGE,"source_url":url or "",
             "status":"NOT_YET_CAPTURED","bytes":0,"sha256":"","pages":0}
        if not url:
            rec["status"]="LINK_NOT_RESOLVED"
        else:
            path=root/f"S-OIL_{y}_ESG_지속가능경영보고서_공식.pdf"
            try:
                resp=request_page(s,url,timeout=110)
                h=hashlib.sha256();size=0
                with path.open("wb") as f:
                    for b in resp.iter_content(chunk_size=1024*1024):
                        if not b:continue
                        f.write(b);h.update(b);size+=len(b)
                if size<1000 or path.open("rb").read(5)!=b"%PDF-":
                    raise ValueError("Not a PDF or only an error page")
                from pypdf import PdfReader
                pdf=PdfReader(path)
                if len(pdf.pages)<1:raise ValueError("PDF has no pages")
                rec.update(status="PDF_VERIFIED",bytes=size,sha256=h.hexdigest(),
                           pages=len(pdf.pages),file=path.name)
            except Exception as exc:
                path.unlink(missing_ok=True)
                rec.update(status="FETCH_OR_PDF_VALIDATION_FAILED",
                           error=f"{type(exc).__name__}: {exc}"[:300])
        manifest.append(rec)
        print("REPORT",json.dumps(rec,ensure_ascii=False),flush=True)
    save({"official_source":REPORT_PAGE,"reports":manifest,
          "completed_reports":sum(x["status"]=="PDF_VERIFIED" for x in manifest)},
          ROOT/"internal"/"reports_manifest.json")
    # The readable report ZIP contains original PDFs exclusively, not JSON.
    z=ROOT/"S-OIL_2020-2025_공식보고서_원본PDF.zip"
    with zipfile.ZipFile(z,"w",compression=zipfile.ZIP_STORED) as out:
        for p in sorted(root.glob("*.pdf")):
            out.write(p,"지속가능경영보고서/"+p.name)
    print("USER_REPORT_ZIP",z,z.stat().st_size,flush=True)
    if not list(root.glob("*.pdf")):raise SystemExit("No readable official PDF collected")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("operation",choices=("setup","reports"))
    args=p.parse_args()
    if args.operation=="setup":setup()
    elif args.operation=="reports":reports()

if __name__=="__main__":main()
