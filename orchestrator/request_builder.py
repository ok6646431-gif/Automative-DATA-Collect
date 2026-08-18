import argparse, json
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def year_end_value(x, fallback):
    return fallback if x in (None, "auto") else int(x)


def alias_overlap(alias, start, end):
    a0=int(alias.get("year_start", 0))
    a1=year_end_value(alias.get("year_end", "auto"), end)
    return max(a0,start) <= min(a1,end)


def aliases_for(profile, start, end, include_predecessor=True):
    out=[]
    for a in profile.get("aliases", []):
        if not include_predecessor and a.get("scope") == "predecessor":
            continue
        if alias_overlap(a,start,end):
            out.append(a)
    if not out:
        out=[{"term": profile["company_display_name"], "scope":"current", "year_start":start, "year_end":end}]
    return out


def terms_by_year(profile, years, include_predecessor=True):
    """Compile bounded aliases for collectors that query individual periods."""
    return {str(year): [a["term"] for a in aliases_for(profile, year, year, include_predecessor)]
            for year in years}


def build(profile):
    plan=profile["source_plan"]
    company=profile["company_display_name"]
    req={"request_id":profile["request_id"],"company_display_name":company,"profile_version":profile.get("profile_version","1.0"),"sources":{}}

    p=plan["ENVINFO"]; s=int(p["start_year"]); e=int(p["end_year"])
    terms=[]
    for a in aliases_for(profile,s,e):
        if a["term"] not in terms: terms.append(a["term"])
    req["sources"]["ENVINFO"]={"start_year":s,"end_year":e,"search_terms":terms,"search_terms_by_year":terms_by_year(profile,range(s,e+1)),"page_size":int(p.get("page_size",200)),"collect_details":True,"max_details":int(p.get("max_details",500)),"request_delay_ms":int(p.get("request_delay_ms",80))}

    p=plan["PRTR"]; s=int(p["start_year"]); e=int(p["end_year"]); specs=[]
    for a in aliases_for(profile,s,e):
        ys=max(s,int(a.get("year_start",s))); ye=min(e,year_end_value(a.get("year_end","auto"),e))
        specs.append({"term":a["term"],"year_start":ys,"year_end":ye})
    req["sources"]["PRTR"]={"start_year":s,"end_year":e,"max_pages":int(p.get("max_pages",50)),"request_delay_ms":int(p.get("request_delay_ms",80)),"collect_details":True,"search_terms":specs,"site_address_anchors":profile.get("site_address_anchors",{})}

    p=plan["CHEM_STATS"]; years=[int(x) for x in p["years"]]; s=min(years); e=max(years)
    terms=[]
    for a in aliases_for(profile,s,e):
        if a["term"] not in terms: terms.append(a["term"])
    req["sources"]["CHEM_STATS"]={"years":years,"search_terms":terms,"search_terms_by_year":terms_by_year(profile,years),"max_pages":int(p.get("max_pages",50)),"request_delay_ms":int(p.get("request_delay_ms",80)),"collect_details":True}

    p=plan["CLEANSYS_AIR"]; s=int(p["start_year"]); e=int(p["end_year"])
    terms=[]
    for a in aliases_for(profile,s,e,include_predecessor=False):
        if a["term"] not in terms: terms.append(a["term"])
    req["sources"]["CLEANSYS_AIR"]={"search_terms":terms,"search_terms_by_year":terms_by_year(profile,range(s,e+1),include_predecessor=False),"start_year":s,"end_year":e}

    p=plan["SOOSIRO_WATER"]; annual=[int(x) for x in p["annual_years"]]; daily=[int(x) for x in p.get("daily_years",[])]
    s=min(annual); e=max(annual); terms=[]
    for a in aliases_for(profile,s,e,include_predecessor=False):
        if a["term"] not in terms: terms.append(a["term"])
    req["sources"]["SOOSIRO_WATER"]={"search_terms":terms,"search_terms_by_year":terms_by_year(profile,sorted(set(annual+daily)),include_predecessor=False),"annual_years":annual,"daily_years":daily}
    return req


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("profile"); ap.add_argument("--out",default="requests/current.generated.json")
    args=ap.parse_args(); profile=load(args.profile); req=build(profile)
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    Path(args.out).write_text(json.dumps(req,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"request_id":req["request_id"],"company":req["company_display_name"],"output":args.out},ensure_ascii=False))

if __name__=="__main__": main()
