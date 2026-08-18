import json, time
from pathlib import Path

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
OUT = Path("output/network_probe.json")
OUT.parent.mkdir(exist_ok=True)


def probe(url, timeout=(2.5,4), verify=True):
    t=time.time()
    try:
        r=requests.get(url,headers={"User-Agent":UA},timeout=timeout,allow_redirects=True,verify=verify)
        return {"reachable":True,"status_code":r.status_code,"elapsed_sec":round(time.time()-t,3),"final_url":r.url,"bytes":len(r.content)}
    except Exception as e:
        return {"reachable":False,"elapsed_sec":round(time.time()-t,3),"error_type":type(e).__name__,"error":str(e)}

results={}
results["ENV_INFO"]=probe("https://www.env-info.kr/member/open/companyTotalInfoSearch.do")
icis=probe("https://icis.mcee.go.kr/prtr/prtrInfo/entrpsSearch.do",timeout=(2,3))
results["PRTR"]=icis
results["CHEM_STATS"]={**icis,"shared_host_probe":True}
results["CLEANSYS"]=probe("https://cleansys.or.kr/index.do")
results["SOOSIRO"]=probe("https://www.soosiro.or.kr/index.do")
OUT.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(results,ensure_ascii=False))
