import json, time
from pathlib import Path

import requests

TARGETS = {
    "ENV_INFO": "https://www.env-info.kr/member/open/companyTotalInfoSearch.do",
    "PRTR": "https://icis.mcee.go.kr/prtr/prtrInfo/entrpsSearch.do",
    "CHEM_STATS": "https://icis.mcee.go.kr/pageLink.do",
    "CLEANSYS": "https://cleansys.or.kr/",
    "SOOSIRO": "https://www.soosiro.or.kr/index.do",
}

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"

results = {}
for key, url in TARGETS.items():
    t0 = time.time()
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=(5, 8), allow_redirects=True)
        results[key] = {
            "reachable": True,
            "status_code": r.status_code,
            "elapsed_sec": round(time.time() - t0, 3),
            "final_url": r.url,
            "bytes": len(r.content),
        }
    except Exception as e:
        results[key] = {
            "reachable": False,
            "elapsed_sec": round(time.time() - t0, 3),
            "error_type": type(e).__name__,
            "error": str(e),
        }

out = Path("output")
out.mkdir(exist_ok=True)
(out / "network_probe.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False))
