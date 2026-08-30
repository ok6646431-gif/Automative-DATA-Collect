from pathlib import Path

p=Path('orchestrator/postprocess.py')
s=p.read_text(encoding='utf-8')
old='''        if bid: out.append({"source_key":"CHEM_STATS","source_site_id":bid,"source_site_name_raw":r.get("bplcNm","") ,"source_address_raw":r.get("locplcAdres","") ,"years":[r.get("search_year") or r.get("reportYear")],"raw_ref":"CHEM_STATS/discovery.csv"})'''
new='''        if bid: out.append({"source_key":"CHEM_STATS","source_site_id":bid,"source_site_name_raw":r.get("bplcNm") or r.get("identity_anchor_bplcNm","") ,"source_address_raw":r.get("locplcAdres") or r.get("identity_anchor_locplcAdres","") ,"years":[r.get("search_year") or r.get("reportYear")],"raw_ref":"CHEM_STATS/discovery.csv"})'''
if old not in s:
    raise SystemExit('CHEM_STATS candidate line not found')
p.write_text(s.replace(old,new,1),encoding='utf-8')
