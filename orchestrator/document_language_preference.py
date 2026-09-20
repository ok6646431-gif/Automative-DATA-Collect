"""Fail-closed Korean-language selection for user-facing annual sustainability reports.

All issuers: a verified KO route must be the primary annual report. An EN or
unclassified candidate is never a substitute for a missing Korean report. Concrete
PDF language must also be checked downstream, because a UI label can be misleading.
Other document types are unaffected.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

STRONG = {"VERIFIED", "SOURCE_VERIFIED"}
ROUTE_FIELDS = (
    "source_url", "source_locator", "expected_extension", "verification_status",
    "notes", "original_filename", "title", "source_report_title", "label",
)
KO_MARKERS = (r"(?:^|[/_.?=&-])(kr|ko|kor)(?:[/_.?=&-]|$)", r"\bkorean\b", r"국문", r"한글", r"한국어")
EN_MARKERS = (r"(?:^|[/_.?=&-])(en|eng)(?:[/_.?=&-]|$)", r"\benglish\b", r"영문", r"영어")


def _signals(value: str) -> tuple[bool, bool]:
    text = str(value or "").casefold()
    return (
        any(re.search(pattern, text, re.I) for pattern in KO_MARKERS),
        any(re.search(pattern, text, re.I) for pattern in EN_MARKERS),
    )


def route_language(route: Dict[str, Any]) -> str:
    # Concrete PDF filenames/URLs override page titles. A Korean page can link to
    # an English PDF, and a language-neutral UUID can have an explicit KOR label.
    concrete = " ".join(str(route.get(field) or "") for field in ("original_filename", "source_url"))
    ko, en = _signals(concrete)
    if ko != en:
        return "KO" if ko else "EN"
    labels = " ".join(str(route.get(field) or "") for field in ("label", "title", "source_report_title"))
    ko, en = _signals(labels)
    if ko != en:
        return "KO" if ko else "EN"
    return "UNKNOWN"


def _year(doc: Dict[str, Any]):
    try:
        return int(doc.get("report_year"))
    except (TypeError, ValueError):
        return None


def _strong(route: Dict[str, Any]) -> bool:
    return str(route.get("verification_status") or "").upper() in STRONG


def _route_from_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {key: doc[key] for key in ROUTE_FIELDS if doc.get(key) not in (None, "")}


def _promote_fallback(doc: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any] | None]:
    item = dict(doc)
    if item.get("document_type") != "SUSTAINABILITY_REPORT" or not _strong(item):
        return item, None
    primary_language = route_language(item)
    fallbacks = [dict(x) for x in item.get("fallback_sources") or [] if isinstance(x, dict)]
    ko_routes = [x for x in fallbacks if _strong(x) and route_language(x) == "KO"]
    if primary_language == "KO":
        item["fallback_sources"] = ko_routes
        item["language_preference"] = "KO_REQUIRED_VERIFIED_ROUTE"
        return item, None
    if ko_routes:
        chosen = ko_routes.pop(0)
        old_url = item.get("source_url")
        for key in ROUTE_FIELDS:
            if key in chosen:
                item[key] = chosen[key]
            elif key in ("notes", "original_filename", "title", "source_report_title", "label"):
                item.pop(key, None)
        item["fallback_sources"] = ko_routes
        item["language_preference"] = "KO_REQUIRED_VERIFIED_ROUTE"
        return item, {"document_id": doc.get("document_id"), "report_year": _year(doc),
                      "old_language": primary_language, "old_url": old_url,
                      "new_url": chosen.get("source_url"), "action": "PROMOTED_KOREAN_PRIMARY_DROPPED_NON_KOREAN_FALLBACKS"}
    # No Korean route is established. Preserve the candidate only as auditable
    # unverified evidence; the document collector must not download/count it.
    item["verification_status"] = "LANGUAGE_REVIEW_REQUIRED"
    item["fallback_sources"] = []
    item["language_preference"] = "KO_REQUIRED_NOT_VERIFIED"
    return item, {"document_id": doc.get("document_id"), "report_year": _year(doc),
                  "old_language": primary_language, "old_url": doc.get("source_url"),
                  "new_url": None, "action": "KOREAN_REPORT_NOT_VERIFIED_BLOCKED"}


def prefer_korean_sustainability(discovery: Dict[str, Any], docs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    staged, changes = [], []
    for doc in docs:
        updated, change = _promote_fallback(doc)
        staged.append(updated)
        if change:
            changes.append(change)
    by_year = {}
    for idx, doc in enumerate(staged):
        if doc.get("document_type") == "SUSTAINABILITY_REPORT" and _year(doc) is not None:
            by_year.setdefault(_year(doc), []).append(idx)
    remove = set()
    for year, indices in by_year.items():
        korean = [i for i in indices if _strong(staged[i]) and route_language(staged[i]) == "KO"]
        if not korean:
            continue
        primary = korean[0]
        for idx in indices:
            if idx == primary:
                continue
            route = staged[idx]
            if _strong(route) and route_language(route) == "KO":
                candidate = _route_from_doc(route)
                fbs = list(staged[primary].get("fallback_sources") or [])
                if candidate.get("source_url") and not any(x.get("source_url") == candidate.get("source_url") for x in fbs):
                    fbs.append(candidate)
                staged[primary]["fallback_sources"] = fbs
            remove.add(idx)
            changes.append({"report_year": year, "old_language": route_language(route),
                            "old_url": route.get("source_url"), "new_url": staged[primary].get("source_url"),
                            "action": "DEDUPED_TO_KOREAN_PRIMARY"})
    out = [doc for idx, doc in enumerate(staged) if idx not in remove]
    missing = sorted({year for year, idxs in by_year.items() if not any(
        idx not in remove and _strong(staged[idx]) and route_language(staged[idx]) == "KO" for idx in idxs)})
    return out, {"status": "REVIEW_REQUIRED" if missing else "APPLIED",
                 "policy": "KO_VERIFIED_ONLY_NEVER_EN_FALLBACK",
                 "korean_route_unverified_years": missing, "changes": changes}
