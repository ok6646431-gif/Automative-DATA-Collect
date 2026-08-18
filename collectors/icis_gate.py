import json, sys
from pathlib import Path

bad={"REMOTE_HOST_UNREACHABLE","REQUEST_OR_PARSE_FAILED","CONFIG_ERROR"}
problems=[]
for p in [Path("output/PRTR/status.json"),Path("output/CHEM_STATS/status.json")]:
    if not p.exists():
        problems.append(f"missing:{p}"); continue
    d=json.loads(p.read_text(encoding="utf-8"))
    if d.get("status") in bad: problems.append(f"{d.get('source_key')}:{d.get('status')}")
print(json.dumps({"icis_gate":"PASS" if not problems else "RETRY_REQUIRED","problems":problems},ensure_ascii=False))
sys.exit(1 if problems else 0)
