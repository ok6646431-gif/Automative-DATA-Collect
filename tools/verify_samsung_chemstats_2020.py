import hashlib
import json
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://icis.mcee.go.kr"
DISCOVERY = BASE + "/iprtr/cdrInfoDetailListJson.do"
DETAIL = BASE + "/iprtr/cdrInfoView.do"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"

TARGETS = [
    {"site":"기흥","bplcId":"AAE034N","expected":"기흥사업장","terms":["삼성전자 기흥","삼성전자 기흥사업장","삼성전자 주식회사 기흥사업장","삼성전자(주)기흥사업장"]},
    {"site":"화성","bplcId":"AAE035N","expected":"화성사업장","terms":["삼성전자 화성","삼성전자 화성사업장","삼성전자 주식회사 화성사업장","삼성전자(주)화성사업장"]},
    {"site":"온양","bplcId":"AAN509N","expected":"삼성전자","terms":["삼성전자 온양","삼성전자 온양사업장","삼성전자 아산","삼성전자 배방"]},
    {"site":"천안","bplcId":"ABB482N","expected":"천안사업장","terms":["삼성전자 천안","삼성전자 천안사업장","삼성전자(주) 천안사업장"]},
    {"site":"평택","bplcId":"ABC056N","expected":"삼성전자","terms":["삼성전자 평택","삼성전자 평택사업장","삼성전자 고덕","삼성전자(주) 평택사업장"]},
]


def walk(obj):
    if isinstance(obj, dict):
        if any(str(k).lower() == "bplcid" for k in obj):
            yield obj
        for value in obj.values():
            yield from walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk(value)


def get_ci(row, name, default=""):
    name = name.lower()
    for key, value in row.items():
        if str(key).lower() == name:
            return value
    return default


def detail_params(year, bplc_id):
    return {"searchAdres1Text":"","streNo":"","searchMttrWord":"","searchYear":str(year),"searchCategory":"","searchAdres2":"","bplcNm":"","irsttList":"","pageNo":"1","bplcId":str(bplc_id),"indutyCode2":"","indutyCode3":"","searchAdres2Text":"","mttrGroup":"","indutyCode4":""}


def detail_signature(html, bplc_id):
    soup=BeautifulSoup(html,"html.parser")
    tables=soup.find_all("table")
    product_rows=0
    chemical_rows=0
    product_names=[]
    if len(tables) >= 3:
        trs=tables[2].find_all("tr")
        for tr in trs:
            cells=[x.get_text(" ",strip=True) for x in tr.find_all(["th","td"])]
            if cells and cells[0] not in {"제품명칭","제품 구성"} and len(cells)>=2:
                product_rows += 1
                product_names.append(cells[0])
    if len(tables) >= 4:
        trs=tables[3].find_all("tr")
        for tr in trs:
            cells=[x.get_text(" ",strip=True) for x in tr.find_all(["th","td"])]
            if cells and len(cells)>=2 and cells[0] not in {"물질명칭","인체등유해성물질"}:
                chemical_rows += 1
    normalized="|".join(product_names[:40])
    return {
        "id_present": str(bplc_id) in html,
        "html_bytes": len(html.encode("utf-8")),
        "table_count": len(tables),
        "product_rows": product_rows,
        "chemical_rows": chemical_rows,
        "product_signature": hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else "",
        "sample_products": product_names[:5],
    }


def fetch_detail(session, bplc_id, year=2020):
    d=session.get(DETAIL,params=detail_params(year,bplc_id),headers={"Referer":BASE+"/pageLink.do"},timeout=(8,25))
    d.raise_for_status()
    return d, detail_signature(d.text,bplc_id)


def main():
    out = Path("verification/samsung_chemstats_2020")
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent":UA,"X-Requested-With":"XMLHttpRequest","Accept":"application/json,text/javascript,*/*;q=0.01","Referer":BASE+"/pageLink.do"})

    # Negative control: an invented facility ID must not return a populated record.
    control_id="ZZZ999N"
    control_response, control_sig=fetch_detail(session,control_id,2020)
    (out/f"CONTROL_{control_id}_2020.html").write_text(control_response.text,encoding="utf-8")

    # Positive control: this Samsung Gumi facility is present in the normal 2020 discovery result.
    positive_id="AAM029N"
    positive_response, positive_sig=fetch_detail(session,positive_id,2020)
    (out/f"CONTROL_{positive_id}_2020.html").write_text(positive_response.text,encoding="utf-8")

    results=[]
    for target in TARGETS:
        term_hits=[]
        for term in target["terms"]:
            r=session.post(DISCOVERY,data={"searchYear":"2020","bplcNm":term,"pageNo":"1"},timeout=(8,25))
            r.raise_for_status()
            try:
                rows=list(walk(r.json()))
            except Exception:
                rows=[]
            hits=[]
            for item in rows:
                hits.append({
                    "bplcId":str(get_ci(item,"bplcId","")),
                    "bplcNm":str(get_ci(item,"bplcNm","")),
                    "locplcAdres":str(get_ci(item,"locplcAdres","")),
                    "reportYear":str(get_ci(item,"reportYear","")),
                })
            term_hits.append({"term":term,"rows":hits})

        d,sig=fetch_detail(session,target["bplcId"],2020)
        text=BeautifulSoup(d.text,"html.parser").get_text(" ",strip=True)
        record_populated=(
            sig["id_present"]
            and sig["product_rows"] > control_sig["product_rows"]
            and sig["chemical_rows"] > control_sig["chemical_rows"]
            and sig["product_signature"]
            and sig["product_signature"] != control_sig["product_signature"]
        )
        result={
            **target,
            "discovery_terms":term_hits,
            "discovery_hit_count":sum(len(x["rows"]) for x in term_hits),
            "detail_http":d.status_code,
            "detail_expected_name_present":target["expected"] in text,
            "detail_signature":sig,
            "direct_id_record_populated":bool(record_populated),
        }
        results.append(result)
        (out/f"{target['site']}_{target['bplcId']}_2020.html").write_text(d.text,encoding="utf-8")

    confirmed=[r["site"] for r in results if r["direct_id_record_populated"]]
    unresolved=[r["site"] for r in results if not r["direct_id_record_populated"]]
    summary={
        "year":2020,
        "source":"ICIS_CHEM_STATS",
        "method":"name variants + known later-year bplcId direct lookup + negative/positive controls",
        "negative_control":{"bplcId":control_id,**control_sig},
        "positive_control":{"bplcId":positive_id,**positive_sig},
        "targets":results,
        "direct_id_2020_record_confirmed":confirmed,
        "unresolved":unresolved,
        "interpretation":"A site is confirmed only when the known source-native facility ID returns populated product and chemical tables distinct from an invented-ID negative control.",
    }
    (out/"result.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))

if __name__ == "__main__":
    main()
