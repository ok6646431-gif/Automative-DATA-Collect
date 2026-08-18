import json, sys
from pathlib import Path

import requests

BASE = "https://www.soosiro.or.kr"
ANNUAL = BASE + "/open/web/annual/listJson"
FACTS = BASE + "/open/web/annual/factListJson"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"


def dump(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(req_path):
    req = json.loads(Path(req_path).read_text(encoding="utf-8"))
    cfg = req.get("sources", {}).get("SOOSIRO_WATER", {})
    term = cfg.get("search_term", "엘지화학")
    year = int(cfg.get("proof_year", 2025))
    out = Path("output/SOOSIRO_WATER")
    out.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": UA,
        "Referer": BASE + "/open/web/annual?pMENU_NO=410",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json,text/plain,*/*",
    }
    status = {"source_key": "SOOSIRO_WATER", "status": "RUNNING", "proof_year": year, "search_term": term}
    try:
        rf = requests.post(FACTS, data={"pDoCode": ""}, headers=headers, timeout=(5, 12))
        rf.raise_for_status()
        dump(out / "fact_list_raw.json", rf.text)

        ra = requests.post(ANNUAL, data={
            "pSYear": str(year), "pEYear": str(year), "pDoCode": "", "pFactCode": "", "pSearchWord": term
        }, headers=headers, timeout=(5, 12))
        ra.raise_for_status()
        dump(out / f"annual_{year}_{term}_raw.json", ra.text)

        body = ra.text
        matches = body.count(term)
        # Preserve raw response. This proof only establishes source-native reachability/data exposure.
        status.update({
            "status": "DATA_FOUND" if matches else "RESPONSE_OK_NO_TERM_MATCH",
            "http_status": ra.status_code,
            "response_bytes": len(ra.content),
            "term_occurrences": matches,
            "fact_list_bytes": len(rf.content),
        })
    except Exception as e:
        status.update({"status": "REQUEST_OR_PARSE_FAILED", "error": f"{type(e).__name__}: {e}"})
    (out / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return 0 if status["status"] not in {"REQUEST_OR_PARSE_FAILED"} else 31


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "requests/current.json"))
