"""User-facing language preference for verified annual sustainability reports.

For Korean issuers, prefer an equally verified Korean annual report over an English
route for the same report year. Language preference never weakens year/entity
verification: it only arbitrates among already verified routes and keeps superseded
routes as fallbacks for provenance/retry.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

STRONG={"VERIFIED","SOURCE_VERIFIED"}


def _text(route: Dict[str, Any]) -> str:
    return " ".join(str(route.get(k) or "") for k in (
        "source_url","source_locator","original_filename","title","source_report_title","label","notes"
    )).casefold()


def route_language(route: Dict[str, Any]) -> str:
    text=_text(route)
    # Strong filename/path/label signals only. Do not classify a Korean UI title by
    # Hangul presence alone because the linked document can still be English.
    ko_patterns=(
        r"(?:^|[/_.?=&-])(kr|ko|kor)(?:[/_.?=&-]|$)",
        r"\bkorean\b", r"국문", r"한글", r"한국어",
    )
    en_patterns=(
        r"(?:^|[/_.?=&-])(en|eng)(?:[/_.?=&-]|$)",
        r"\benglish\b", r"영문", r"영어",
    )
    ko=any(re.search(p,text,re.I) for p in ko_patterns)
    en=any(re.search(p,text,re.I) for p in en_patterns)
    if ko and not en: return "KO"
    if en and not ko: return "EN"
    return "UNKNOWN"


def _korean_issuer(discovery: Dict[str, Any]) -> bool:
    value=" ".join(str(discovery.get(k) or "") for k in ("current_legal_name","requested_company_name"))
    return bool(re.search(r"[가-힣]",value))


def _year(doc: Dict[str, Any]):
    try: return int(doc.get("report_year"))
    except (TypeError,ValueError): return None


def _strong(route: Dict[str, Any]) -> bool:
    return str(route.get("verification_status") or "").upper() in STRONG


def _route_from_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k:doc.get(k) for k in (
        "source_url","source_locator","expected_extension","verification_status","notes",
        "original_filename","title","source_report_title","label"
    ) if doc.get(k) not in (None,"")}


def _promote_fallback(doc: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any] | None]:
    if doc.get("document_type")!="SUSTAINABILITY_REPORT" or not _strong(doc):
        return dict(doc),None
    current_lang=route_language(doc)
    fallbacks=[dict(x) for x in (doc.get("fallback_sources") or []) if isinstance(x,dict)]
    candidates=[x for x in fallbacks if _strong(x) and route_language(x)=="KO"]
    if not candidates or current_lang=="KO":
        return dict(doc),None
    chosen=candidates[0]
    item=dict(doc)
    old=_route_from_doc(doc)
    for key in ("source_url","source_locator","expected_extension","verification_status","notes","original_filename","title","source_report_title","label"):
        if key in chosen:
            item[key]=chosen.get(key)
    remaining=[x for x in fallbacks if str(x.get("source_url") or "")!=str(chosen.get("source_url") or "")]
    if old.get("source_url") and not any(str(x.get("source_url") or "")==str(old.get("source_url") or "") for x in remaining):
        old["source_role"]="LANGUAGE_FALLBACK"
        remaining.append(old)
    item["fallback_sources"]=remaining
    item["language_preference"]="KO_PREFERRED"
    return item,{"document_id":doc.get("document_id"),"report_year":_year(doc),"old_language":current_lang,"old_url":doc.get("source_url"),"new_url":chosen.get("source_url"),"action":"PROMOTED_KOREAN_FALLBACK"}


def prefer_korean_sustainability(discovery: Dict[str, Any], docs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not _korean_issuer(discovery):
        return list(docs),{"status":"NOT_APPLICABLE_NON_KOREAN_ISSUER","changes":[]}
    staged=[]; changes=[]
    for doc in docs:
        item,change=_promote_fallback(doc)
        staged.append(item)
        if change: changes.append(change)

    # If discovery produced two verified annual records for one year, keep the Korean
    # record as the user-facing primary and retain the other route as a fallback.
    by_year={}
    for i,doc in enumerate(staged):
        if doc.get("document_type")!="SUSTAINABILITY_REPORT" or not _strong(doc): continue
        year=_year(doc)
        if year is not None: by_year.setdefault(year,[]).append(i)
    remove=set()
    for year,idxs in by_year.items():
        ko=[i for i in idxs if route_language(staged[i])=="KO"]
        if not ko: continue
        primary=ko[0]
        for i in idxs:
            if i==primary or route_language(staged[i])=="KO": continue
            old=_route_from_doc(staged[i])
            fbs=list(staged[primary].get("fallback_sources") or [])
            if old.get("source_url") and not any(str(x.get("source_url") or "")==str(old.get("source_url") or "") for x in fbs if isinstance(x,dict)):
                old["source_role"]="LANGUAGE_FALLBACK"
                fbs.append(old)
            staged[primary]["fallback_sources"]=fbs
            staged[primary]["language_preference"]="KO_PREFERRED"
            remove.add(i)
            changes.append({"report_year":year,"old_language":route_language(staged[i]),"old_url":staged[i].get("source_url"),"new_url":staged[primary].get("source_url"),"action":"DEDUPED_TO_KOREAN_PRIMARY"})
    out=[doc for i,doc in enumerate(staged) if i not in remove]
    return out,{"status":"APPLIED","policy":"KO_VERIFIED_FIRST_EN_FALLBACK","changes":changes}
