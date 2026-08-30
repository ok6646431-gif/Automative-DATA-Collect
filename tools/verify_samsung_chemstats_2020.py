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


def main():
    out = Path("verification/samsung_chemstats_2020")
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent":UA,"X-Requested-With":"XMLHttpRequest","Accept":"application/json,text/javascript,*/*;q=0.01","Referer":BASE+"/pageLink.do"})
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
            for row in rows:
                hits.append({
                    "bplcId":str(get_ci(row,"bplcId","")),
                    "bplcNm":str(get_ci(row,"bplcNm","")),
                    "locplcAdres":str(get_ci(row,"locplcAdres","")),
                    "reportYear":str(get_ci(row,"reportYear","")),
                })
            term_hits.append({"term":term,"rows":hits})

        params={"searchAdres1Text":"","streNo":"","searchMttrWord":"","searchYear":"2020","searchCategory":"","searchAdres2":"","bplcNm":"","irsttList":"","pageNo":"1","bplcId":target["bplcId"],"indutyCode2":"","indutyCode3":"","searchAdres2Text":"","mttrGroup":"","indutyCode4":""}
        d=session.get(DETAIL,params=params,headers={"Referer":BASE+"/pageLink.do"},timeout=(8,25))
        d.raise_for_status()
        text=BeautifulSoup(d.text,"html.parser").get_text(" ",strip=True)
        detail_2020=("2020" in text and "화학물질 통계조사표" in text)
        id_present=target["bplcId"] in d.text
        expected_present=target["expected"] in text
        result={
            **target,
            "discovery_terms":term_hits,
            "discovery_hit_count":sum(len(x["rows"]) for x in term_hits),
            "detail_http":d.status_code,
            "detail_id_present":id_present,
            "detail_expected_name_present":expected_present,
            "detail_mentions_2020_statistics":detail_2020,
            "detail_text_prefix":text[:1000],
        }
        results.append(result)
        (out/f"{target['site']}_{target['bplcId']}_2020.html").write_text(d.text,encoding="utf-8")

    summary={
        "year":2020,
        "source":"ICIS_CHEM_STATS",
        "targets":results,
        "no_2020_public_record_confirmed":[r["site"] for r in results if r["discovery_hit_count"]==0 and not r["detail_mentions_2020_statistics"]],
        "needs_review":[r["site"] for r in results if r["discovery_hit_count"]>0 or r["detail_mentions_2020_statistics"]],
    }
    (out/"result.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))

if __name__ == "__main__":
    main()
