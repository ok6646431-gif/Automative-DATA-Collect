import argparse, json, re
from pathlib import Path


LEGAL_QUERY_ALIAS_TYPES={
    "current_legal_name",
    "former_legal_name",
    "historical_legal_name",
    "legal_name",
}


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
        if a.get("search_enabled", True) is False:
            continue
        if not include_predecessor and a.get("scope") == "predecessor":
            continue
        if alias_overlap(a,start,end):
            out.append(a)
    if not out:
        out=[{"term": profile["company_display_name"], "scope":"current", "year_start":start, "year_end":end}]
    return out


def query_terms_for_alias(alias):
    """Return bounded source-query spellings without inventing new identity facts.

    Korean public systems commonly vary only the legal-form rendering of the same
    verified legal name: ``주식회사 A``, ``A 주식회사``, ``A(주)``, ``A㈜`` or the
    bare legal-name stem.  Expand those spellings only for aliases explicitly typed
    as legal names. Brand/request aliases and English aliases are left untouched.
    """
    term=str(alias.get("term") or "").strip()
    if not term:
        return []
    out=[term]
    alias_type=str(alias.get("alias_type") or "")
    if alias_type not in LEGAL_QUERY_ALIAS_TYPES or not re.search(r"[가-힣]", term):
        return out

    base=term
    base=re.sub(r"^\s*주식회사\s+", "", base)
    base=re.sub(r"\s+주식회사\s*$", "", base)
    base=re.sub(r"\s*(?:\(주\)|㈜)\s*$", "", base).strip()
    if not base:
        return out
    for variant in (base, f"{base}(주)", f"{base}㈜", f"주식회사 {base}", f"{base} 주식회사"):
        if variant not in out:
            out.append(variant)
    return out


def _query_terms(aliases):
    out=[]
    for alias in aliases:
        for term in query_terms_for_alias(alias):
            if term not in out:
                out.append(term)
    return out


def terms_by_year(profile, years, include_predecessor=True):
    """Compile bounded aliases and legal-form variants for individual periods."""
    return {str(year): _query_terms(aliases_for(profile, year, year, include_predecessor))
            for year in years}


def verified_site_addresses(profile):
    """Return only first-party verified site addresses for source discovery hints.

    These are discovery anchors, not canonical mappings.  Collectors may use them to
    locate source-native facility names, while downstream identity rules still decide
    whether a source facility can be linked to a canonical site.
    """
    out=[]
    for site in profile.get("site_candidates",[]) or []:
        if not isinstance(site,dict): continue
        if site.get("verification_state") not in {"VERIFIED","SOURCE_VERIFIED"}: continue
        if site.get("identity_status") != "CONFIRMED": continue
        address=str(site.get("address_raw") or "").strip()
        if address and address not in out: out.append(address)
    return out


def build(profile):
    plan=profile["source_plan"]
    company=profile["company_display_name"]
    # These names have already passed the Discovery compiler's VERIFIED gate.
    # Collectors use them only to reject known separate legal entities; they are
    # not fuzzy identity rules and never create canonical site mappings.
    exclusions=list(profile.get("related_entity_exclusions",[]) or [])
    site_addresses=verified_site_addresses(profile)
    req={"request_id":profile["request_id"],"company_display_name":company,"profile_version":profile.get("profile_version","1.0"),"related_entity_exclusions":exclusions,"sources":{}}

    p=plan["ENVINFO"]; s=int(p["start_year"]); e=int(p["end_year"])
    terms=_query_terms(aliases_for(profile,s,e))
    req["sources"]["ENVINFO"]={"start_year":s,"end_year":e,"search_terms":terms,"search_terms_by_year":terms_by_year(profile,range(s,e+1)),"exclude_terms":exclusions,"page_size":int(p.get("page_size",200)),"collect_details":True,"collect_attachments":bool(p.get("collect_attachments",True)),"max_details":int(p.get("max_details",500)),"request_delay_ms":int(p.get("request_delay_ms",80))}

    p=plan["PRTR"]; s=int(p["start_year"]); e=int(p["end_year"]); specs=[]
    seen_specs=set()
    for a in aliases_for(profile,s,e):
        ys=max(s,int(a.get("year_start",s))); ye=min(e,year_end_value(a.get("year_end","auto"),e))
        for term in query_terms_for_alias(a):
            key=(term,ys,ye)
            if key in seen_specs: continue
            seen_specs.add(key)
            specs.append({"term":term,"year_start":ys,"year_end":ye})
    req["sources"]["PRTR"]={"start_year":s,"end_year":e,"max_pages":int(p.get("max_pages",50)),"request_delay_ms":int(p.get("request_delay_ms",80)),"collect_details":True,"search_terms":specs,"exclude_terms":exclusions,"site_address_anchors":profile.get("site_address_anchors",{})}

    p=plan["CHEM_STATS"]; years=[int(x) for x in p["years"]]; s=min(years); e=max(years)
    terms=_query_terms(aliases_for(profile,s,e))
    req["sources"]["CHEM_STATS"]={"years":years,"search_terms":terms,"search_terms_by_year":terms_by_year(profile,years),"exclude_terms":exclusions,"max_pages":int(p.get("max_pages",50)),"request_delay_ms":int(p.get("request_delay_ms",80)),"collect_details":True}

    p=plan["CLEANSYS_AIR"]; s=int(p["start_year"]); e=int(p["end_year"])
    terms=_query_terms(aliases_for(profile,s,e,include_predecessor=False))
    req["sources"]["CLEANSYS_AIR"]={"search_terms":terms,"search_terms_by_year":terms_by_year(profile,range(s,e+1),include_predecessor=False),"exclude_terms":exclusions,"site_addresses":site_addresses,"start_year":s,"end_year":e}

    p=plan["SOOSIRO_WATER"]; annual=[int(x) for x in p["annual_years"]]; daily=[int(x) for x in p.get("daily_years",[])]
    s=min(annual); e=max(annual)
    terms=_query_terms(aliases_for(profile,s,e,include_predecessor=False))
    req["sources"]["SOOSIRO_WATER"]={"search_terms":terms,"search_terms_by_year":terms_by_year(profile,sorted(set(annual+daily)),include_predecessor=False),"exclude_terms":exclusions,"site_addresses":site_addresses,"annual_years":annual,"daily_years":daily}
    return req


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("profile"); ap.add_argument("--out",default="requests/current.generated.json")
    args=ap.parse_args(); profile=load(args.profile); req=build(profile)
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    Path(args.out).write_text(json.dumps(req,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"request_id":req["request_id"],"company":req["company_display_name"],"output":args.out},ensure_ascii=False))

if __name__=="__main__": main()
