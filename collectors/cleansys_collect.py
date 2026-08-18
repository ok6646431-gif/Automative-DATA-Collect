import json, re, sys, warnings
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning

BASE = "https://cleansys.or.kr"
INDEX = BASE + "/index.do"
ANNUAL = BASE + "/apiService/selectAnnualResult.do"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"


def main(req_path):
    req = json.loads(Path(req_path).read_text(encoding="utf-8"))
    cfg = req.get("sources", {}).get("CLEANSYS_AIR", {})
    terms = cfg.get("search_terms", ["엘지화학", "LG화학"])
    out = Path("output/CLEANSYS_AIR")
    out.mkdir(parents=True, exist_ok=True)
    status = {"source_key": "CLEANSYS_AIR", "status": "RUNNING", "tls_mode": "VERIFY_FIRST_THEN_SOURCE_EXCEPTION"}

    # Official host currently presents a certificate chain that GitHub Ubuntu cannot validate.
    # Try normal verification first. Only this known source gets a logged fallback; raw artifacts are preserved.
    verify = True
    tls_error = None
    try:
        r = requests.get(INDEX, headers={"User-Agent": UA}, timeout=(5, 10), verify=True)
        r.raise_for_status()
    except requests.exceptions.SSLError as e:
        tls_error = str(e)
        verify = False
        warnings.simplefilter("ignore", InsecureRequestWarning)
        r = requests.get(INDEX, headers={"User-Agent": UA}, timeout=(5, 10), verify=False)
        r.raise_for_status()
    except Exception as e:
        status.update({"status": "REQUEST_OR_PARSE_FAILED", "error": f"{type(e).__name__}: {e}"})
        (out/"status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(status, ensure_ascii=False)); return 41

    (out/"index_raw.html").write_text(r.text, encoding="utf-8")
    soup = BeautifulSoup(r.text, "html.parser")
    candidates = []
    for opt in soup.find_all("option"):
        name = opt.get_text(" ", strip=True)
        fact = (opt.get("value") or "").strip()
        if fact and any(t.lower() in name.lower() for t in terms):
            candidates.append({"fact_code": fact, "company_name_raw": name})

    annual_results = []
    headers = {"User-Agent": UA, "Referer": BASE + "/statAnnual.do", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Accept": "application/json,text/plain,*/*"}
    for c in candidates[:20]:
        try:
            ra = requests.post(ANNUAL, data={
                "s_year": str(cfg.get("start_year", 2015)), "e_year": str(cfg.get("end_year", 2025)),
                "selectArea": "", "selectComp": "", "selectCompDrop": c["fact_code"], "selectOrder": "", "type": "json"
            }, headers=headers, timeout=(5, 12), verify=verify)
            ra.raise_for_status()
            safe = re.sub(r"[^0-9A-Za-z가-힣]+", "_", c["company_name_raw"]).strip("_")
            (out/f"annual_{c['fact_code']}_{safe}_raw.json").write_text(ra.text, encoding="utf-8")
            annual_results.append({**c, "http_status": ra.status_code, "response_bytes": len(ra.content)})
        except Exception as e:
            annual_results.append({**c, "error": f"{type(e).__name__}: {e}"})

    (out/"candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    status.update({
        "status": "DATA_FOUND" if candidates else "RESPONSE_OK_NO_TERM_MATCH",
        "candidate_count": len(candidates),
        "annual_attempt_count": len(annual_results),
        "tls_verification": verify,
        "tls_verification_exception": tls_error,
        "annual_results": annual_results,
    })
    (out/"status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "requests/current.json"))
