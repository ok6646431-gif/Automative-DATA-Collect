import json, re, sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://www.env-info.kr/member/open/companyTotalInfoSearch.do"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"


def main():
    out = Path("output/ENVINFO")
    out.mkdir(parents=True, exist_ok=True)
    status = {"source_key": "ENVINFO", "status": "RUNNING"}
    try:
        r = requests.get(URL, headers={"User-Agent": UA}, timeout=(5, 12))
        r.raise_for_status()
        (out/"search_page_raw.html").write_text(r.text, encoding="utf-8")
        soup = BeautifulSoup(r.text, "html.parser")
        forms=[]
        for f in soup.find_all("form"):
            forms.append({
                "id": f.get("id"), "name": f.get("name"), "method": f.get("method"), "action": f.get("action"),
                "inputs": [{"name":x.get("name"),"id":x.get("id"),"type":x.get("type"),"value":x.get("value"),"placeholder":x.get("placeholder")} for x in f.find_all("input")],
                "selects": [{"name":x.get("name"),"id":x.get("id")} for x in f.find_all("select")],
            })
        scripts=[]
        for s in soup.find_all("script"):
            txt=s.get_text("\n", strip=False)
            if txt and re.search(r"viewSearch2|companyTotal|search|ajax|COMP_ID|fnSearch", txt, re.I):
                scripts.append(txt[:30000])
        structure={"forms":forms,"interesting_scripts":scripts,"script_src":[s.get("src") for s in soup.find_all("script") if s.get("src")],"bytes":len(r.content)}
        (out/"search_structure.json").write_text(json.dumps(structure, ensure_ascii=False, indent=2), encoding="utf-8")
        status.update({"status":"PAGE_CAPTURED","http_status":r.status_code,"bytes":len(r.content),"form_count":len(forms),"interesting_script_count":len(scripts)})
    except Exception as e:
        status.update({"status":"REQUEST_OR_PARSE_FAILED","error":f"{type(e).__name__}: {e}"})
    (out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(status,ensure_ascii=False))
    return 0 if status["status"] != "REQUEST_OR_PARSE_FAILED" else 51


if __name__ == "__main__":
    sys.exit(main())
