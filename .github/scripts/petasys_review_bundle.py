#!/usr/bin/env python3
"""One-off human-review archival capture of publicly available ISU PETASYS ESG sources.
Not part of the general-purpose collection pipeline. Do not claim that sources omitted
from this bundle were queried, nor that an online document is unpublished if it fails.
"""
from __future__ import annotations
import csv
import hashlib
import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

ROOT = Path("review_bundle/ISU_PETASYS")
ROOT.mkdir(parents=True, exist_ok=True)
(RAW := ROOT / "원본_HTML").mkdir(exist_ok=True)
(DOCS := ROOT / "지속가능경영보고서_PDF").mkdir(exist_ok=True)
(PAGES := ROOT / "읽기용_웹페이지").mkdir(exist_ok=True)
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; CorporateESGResearch/1.0)", "Accept": "*/*"})
results = []

PDFS = {
  "2024": "https://www.petasys.com/kor/csr/report_2024.pdf",
  "2023": "https://www.petasys.com/kor/csr/report_2023.pdf",
  "2021": "https://www.petasys.com/kor/csr/report_2021.pdf",
  "2019": "https://www.petasys.com/kor/csr/report_2019.pdf",
  "2017": "https://www.petasys.com/kor/csr/report_2017.pdf",
  "2015": "https://www.petasys.com/kor/csr/report_2015.pdf",
}
HTML_PAGES = {
  "ESG_보고서_목록": "https://www.petasys.com/kor/csr/report.jsp",
  "ESG_환경안전보건_2021-2025": "https://www.petasys.com/kor/csr/performances03.jsp",
  "ESH_방침": "https://www.petasys.com/kor/company/esh.jsp",
  "ESG_전략체계": "https://www.petasys.com/kor/csr/overview.jsp",
  "국내사업장": "https://www.petasys.com/kor/company/domesticbusiness.jsp",
  "ESG_환경자료_방침": "https://www.petasys.com/kor/csr/policy.jsp",
}
ONLINE = {
 "2025": "https://esg.petasys.com:8080/p/2025sr",
 "2026": "https://esg.petasys.com:8080/p/2026sr",
}

def record(kind, title, url, status, path="", detail=""):
    results.append({"구분": kind, "자료명": title, "원문 URL": url, "판정": status, "파일":path,"참고":detail})
    print(kind, title, status, path, detail[:130], flush=True)

def get(url, *, online=False):
    for attempt in range(2):
        try:
            response=session.get(url, timeout=((5,12) if not online else (4,8)), stream=True)
            if response.status_code>=400:
                raise ValueError("HTTP "+str(response.status_code))
            return response
        except Exception as e:
            error=f"{type(e).__name__}: {e}"
            if attempt==0: time.sleep(0.8)
    raise RuntimeError(error)

def clean_text(page_html):
    soup=BeautifulSoup(page_html, "html.parser")
    for selector in ["script","style","noscript","svg","header","footer","nav"]:
        for tag in soup.select(selector): tag.decompose()
    # Retain the site's text and table values; do not erase content due to an
    # unreliable CSS selector. The original bytes remain available separately.
    s=soup.body or soup
    lines=[re.sub(r"\s+"," ",x).strip() for x in s.stripped_strings]
    out=[]
    for x in lines:
        if x and (not out or out[-1]!=x):out.append(x)
    return "\n".join(out),soup

def html_view(name, url, text, tables):
    pre="<h1>"+html.escape(name)+"</h1><p><a href='"+html.escape(url,quote=True)+"'>공식 원문 열기</a></p>"
    pre+="<p>이 문서는 공식 홈페이지 HTML 원문에서 추출한 텍스트와 표입니다. 표의 적용 범위와 연도는 원본을 확인하세요.</p>"
    pre+="<h2>공식 페이지의 표</h2>"
    for t in tables:
        pre+="<div class='scroll'>"+str(t)+"</div>"
    pre+="<h2>공식 페이지의 텍스트</h2><pre>"+html.escape(text)+"</pre>"
    return "<!doctype html><html lang='ko'><meta charset='utf-8'><title>"+html.escape(name)+"</title><style>body{font-family:Arial,'Malgun Gothic',sans-serif;max-width:1100px;margin:35px auto;padding:0 20px;line-height:1.75;color:#172333}table{border-collapse:collapse;margin:20px 0;font-size:14px}td,th{border:1px solid #b8c4cf;padding:7px}th{background:#edf3f8}pre{white-space:pre-wrap;font-family:inherit}.scroll{overflow:auto}a{color:#145db6}</style>"+pre+"</html>"

def save_table_csv(soup):
    candidates=[]
    for table in soup.find_all("table"):
        rows=[]
        for tr in table.find_all("tr"):
            cells=[re.sub(r"\s+"," ",v.get_text(" ",strip=True)).strip() for v in tr.find_all(["th","td"])]
            if cells: rows.append(cells)
        combined=" ".join(" ".join(row) for row in rows)
        if len(rows)>=5 and ("2025" in combined and ("Scope1" in combined or "온실가스" in combined)):
            candidates.append(rows)
    if not candidates:return False
    rows=max(candidates,key=lambda x:len(x))
    target=ROOT/"환경성과_원문표_2021-2025.csv"
    with target.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f);w.writerows(rows)
    record("환경성과 CSV","2021~2025년 원문 표",HTML_PAGES["ESG_환경안전보건_2021-2025"],"확보",target.relative_to(ROOT).as_posix(),f"{len(rows)}행")
    return True

for year,url in PDFS.items():
    name=f"이수페타시스_지속가능경영보고서_{year}.pdf"
    target=DOCS/name
    try:
        r=get(url)
        h=hashlib.sha256()
        size=0
        with target.open("wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk:
                    f.write(chunk);h.update(chunk);size+=len(chunk)
        r.close()
        with target.open("rb") as f:magic=f.read(5)
        if magic!=b"%PDF-" or size<2048: raise ValueError("not a valid nonempty PDF")
        record("공식 PDF",str(year)+"년 보고서",url,"확보",target.relative_to(ROOT).as_posix(),f"{size} bytes SHA256 {h.hexdigest()}")
    except Exception as e:
        if target.exists():target.unlink()
        record("공식 PDF",str(year)+"년 보고서",url,"다운로드 실패",detail=f"{type(e).__name__}: {str(e)[:240]}")

for name,url in HTML_PAGES.items():
    try:
        r=get(url)
        payload=r.content
        r.close()
        path=RAW/(name+".html")
        path.write_bytes(payload)
        encoding=r.encoding or r.apparent_encoding or "utf-8"
        try:source=payload.decode(encoding,errors="replace")
        except LookupError:source=payload.decode("utf-8",errors="replace")
        text,soup=clean_text(source)
        tables=[x for x in soup.select("table") if len(x.find_all("tr"))>1]
        out=PAGES/(name+".html")
        out.write_text(html_view(name,url,text,tables),encoding="utf-8")
        record("공식 웹페이지",name,url,"확보",out.relative_to(ROOT).as_posix(),f"원본={path.relative_to(ROOT)}; 텍스트 {len(text)}자")
        if name=="ESG_환경안전보건_2021-2025":
            if not save_table_csv(soup):
                record("환경성과 CSV","공식 원문 성과표",url,"표 추출 미완료",detail="원본 HTML 및 텍스트 페이지는 보존됨")
    except Exception as e:
        record("공식 웹페이지",name,url,"접근 실패",detail=f"{type(e).__name__}: {str(e)[:220]}")

for year,url in ONLINE.items():
    try:
        r=get(url,online=True)
        data=r.content
        r.close()
        if not data or b"<" not in data[:1024]:raise ValueError("not verified HTML content")
        path=RAW/(f"온라인보고서_{year}.html")
        path.write_bytes(data)
        txt,soup=clean_text(data.decode(r.encoding or "utf-8",errors="replace"))
        out=PAGES/(f"온라인보고서_{year}.html")
        out.write_text(html_view(f"지속가능경영 온라인 보고서 {year}",url,txt,
                                 [x for x in soup.select("table") if len(x.find_all("tr"))>1]),encoding="utf-8")
        record("온라인 보고서",year,url,"HTML 확보(동적 내용 별도 검증 필요)",out.relative_to(ROOT).as_posix(),f"{len(data)} bytes")
    except Exception as e:
        record("온라인 보고서",year,url,"접근 실패(미발간 아님)",detail=f"{type(e).__name__}: {str(e)[:220]}")

# This one-off review bundle deliberately does not masquerade as the six-lane
# audited ENVINFO, PRTR, CHEM_STATS, CLEANSYS or SOOSIRO collectors.
for lane in ["ENVINFO","PRTR","CHEM_STATS","CLEANSYS_AIR","SOOSIRO_WATER"]:
    record("공공자료원",lane,"","미수집",detail="이번 공식 홈페이지 원문 보관함 수집 범위 밖. 수집 성공/자료 없음으로 판정하지 않음.")

with (ROOT/"자료수집_목록.csv").open("w",encoding="utf-8-sig",newline="") as f:
    writer=csv.DictWriter(f,fieldnames=["구분","자료명","원문 URL","판정","파일","참고"])
    writer.writeheader();writer.writerows(results)
items=[]
for item in results:
    status=html.escape(item["판정"])
    name=html.escape(item["자료명"])
    url=item["원문 URL"]
    source=("<a href='"+html.escape(url,quote=True)+"'>공식 출처</a>") if url else "—"
    if item["파일"]:
        path=html.escape(item["파일"],quote=True)
        local="<a href='"+path+"'>보관된 자료 열기</a>"
    else:local="—"
    items.append(f"<tr><td>{html.escape(item['구분'])}</td><td>{name}</td><td>{status}</td><td>{local}</td><td>{source}</td></tr>")
intro="""<p>자료 수집일: 2026-10-12. 이 보관함은 직접 확인하려는 사용자를 위한 <b>공식 홈페이지 원문 수집본</b>입니다. 기업의 공개 내용과 분석 의견을 혼합하지 않았습니다.</p>
<p><b>주의:</b> 2025~2026년 온라인 보고서는 PDF 미발행 여부로 판단하지 않습니다. 접속에 실패하면 그대로 표시합니다. 공공자료원 5개 수집은 별도 절차가 필요합니다.</p>
<p><b>원문 표</b>: 환경성과_원문표_2021-2025.csv를 Excel에서 열 수 있습니다. PDF는 원본 그대로 보관하고 SHA-256을 목록에 남겼습니다.</p>"""
main="<!doctype html><html lang='ko'><meta charset='utf-8'><title>이수페타시스 공식 환경자료 보관함</title><style>body{max-width:1200px;margin:35px auto;padding:0 20px;font-family:Arial,'Malgun Gothic',sans-serif;line-height:1.65;color:#172333}table{width:100%;border-collapse:collapse;font-size:14px}th,td{border-bottom:1px solid #ccd5df;padding:10px;text-align:left}th{background:#eef3f8}a{color:#145db6}p{margin-bottom:16px}</style><h1>이수페타시스 공식 환경자료 보관함</h1>"+intro+"<table><thead><tr><th>구분</th><th>자료명</th><th>상태</th><th>보관 자료</th><th>출처</th></tr></thead><tbody>"+"".join(items)+"</tbody></table></html>"
(ROOT/"00_자료목록_먼저열기.html").write_text(main,encoding="utf-8")
(ROOT/"README_안내.txt").write_text("이수페타시스 환경자료 보관함\n\n1. 00_자료목록_먼저열기.html 을 브라우저에서 엽니다.\n2. 2021~2025 연도별 공개 성과는 환경성과_원문표_2021-2025.csv 를 엽니다.\n3. 보고서 PDF는 지속가능경영보고서_PDF 폴더에서 확인합니다.\n4. 2025/2026 온라인 보고서의 접근 실패는 미발간 증거가 아닙니다.\n5. 공공자료원(ENVINFO, PRTR, CHEM_STATS, CLEANSYS, SOOSIRO)은 이 보관함에 포함되지 않았습니다.\n",encoding="utf-8")
summary={"collection_date":"2026-10-12","company":"이수페타시스","results":results}
(ROOT/"_audit.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print("BUNDLE COMPLETE",json.dumps({x:sum(r["판정"].startswith(x) for r in results) for x in ("확보","접근 실패","다운로드 실패","미수집")},ensure_ascii=False),flush=True)
