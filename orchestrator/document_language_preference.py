"""Fail-closed Korean-language selection for user-facing annual sustainability reports.

All issuers: a verified KO route must be the primary annual report. An EN or
unclassified candidate is never a substitute for a missing Korean report. Concrete
PDF language must also be checked downstream, because a UI label can be misleading.
Other document types are unaffected.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse, urlunparse

from orchestrator import zero_touch_discovery as base

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
    # verification_status is the source/evidence contract and must remain inside
    # its schema enum. Language readiness is tracked separately below.
    item["verification_status"] = "UNVERIFIED"
    item["fallback_sources"] = []
    item["language_preference"] = "KO_REQUIRED_NOT_VERIFIED"
    return item, {"document_id": doc.get("document_id"), "report_year": _year(doc),
                  "old_language": primary_language, "old_url": doc.get("source_url"),
                  "new_url": None, "action": "KOREAN_REPORT_NOT_VERIFIED_BLOCKED"}


_ENGLISH_PATH_TOKEN = re.compile(r"(?i)(?P<prefix>^|[/_.-])(?P<token>eng|en)(?=(?:[/_.-]|$))")


def _korean_sibling_candidates(url: str) -> List[str]:
    """Derive same-host Korean PDF siblings only from explicit EN path tokens.

    This is deliberately narrow: it never searches another host, changes a report
    year, or guesses a filename that has no explicit language token. Candidate URLs
    are evidence only until their response bytes verify as PDF.
    """
    parsed = urlparse(str(url or ""))
    path = parsed.path or ""
    if not parsed.scheme.startswith("http") or not parsed.netloc or not path.lower().endswith(".pdf"):
        return []
    if not _ENGLISH_PATH_TOKEN.search(path):
        return []
    out: List[str] = []
    for replacement in ("kor", "kr"):
        candidate_path = _ENGLISH_PATH_TOKEN.sub(
            lambda m: f"{m.group('prefix')}{replacement}", path, count=1
        )
        candidate = urlunparse(parsed._replace(path=candidate_path))
        if candidate != url and candidate not in out:
            out.append(candidate)
    return out


def _verified_pdf(http: Any, url: str, source_locator: str = "") -> Tuple[bool, str]:
    headers = {"Range": "bytes=0-15", "Accept-Encoding": "identity"}
    if source_locator:
        headers["Referer"] = source_locator
    response = http.get(url, headers=headers, stream=True)
    if not response or int(getattr(response, "status_code", 599) or 599) >= 400:
        return False, ""
    try:
        head = next(response.iter_content(chunk_size=16), b"")
        ctype = str(response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        ok = head.startswith(b"%PDF") or ctype == "application/pdf"
        return ok, str(getattr(response, "url", "") or url)
    except Exception:
        return False, ""
    finally:
        try:
            response.close()
        except Exception:
            pass


def recover_verified_korean_siblings(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
    *,
    http: Any = None,
) -> Dict[str, Any]:
    """Promote a byte-verified same-host Korean sibling of a strong English PDF.

    A strongly verified English annual PDF may expose a deterministic language
    sibling such as *_eng.pdf -> *_kor.pdf. We construct only bounded same-host
    candidates and promote one only after verifying real PDF bytes. English routes
    are not retained as user-facing fallbacks.
    """
    client = http or base.Http(timeout=(5, 15))
    attempted: List[Dict[str, Any]] = []
    recovered: List[Dict[str, Any]] = []
    out_docs: List[Dict[str, Any]] = []

    for raw in documents.get("documents", []) or []:
        if not isinstance(raw, dict):
            out_docs.append(raw)
            continue
        doc = dict(raw)
        if doc.get("document_type") != "SUSTAINABILITY_REPORT" or not _strong(doc):
            out_docs.append(doc)
            continue

        routes = [doc, *[x for x in (doc.get("fallback_sources") or []) if isinstance(x, dict)]]
        if any(_strong(route) and route_language(route) == "KO" for route in routes):
            out_docs.append(doc)
            continue

        source_url = str(doc.get("source_url") or "")
        candidates = _korean_sibling_candidates(source_url)
        if not candidates:
            out_docs.append(doc)
            continue

        chosen = ""
        for candidate in candidates:
            ok, final_url = _verified_pdf(client, candidate, str(doc.get("source_locator") or ""))
            attempted.append({
                "document_id": doc.get("document_id"),
                "report_year": _year(doc),
                "source_url": source_url,
                "candidate_url": candidate,
                "verified_pdf": bool(ok),
            })
            if ok:
                chosen = final_url or candidate
                break

        if not chosen:
            out_docs.append(doc)
            continue

        old_url = source_url
        doc["source_url"] = chosen
        doc["expected_extension"] = "pdf"
        doc["verification_status"] = "SOURCE_VERIFIED"
        doc["language_preference"] = "KO_REQUIRED_VERIFIED_ROUTE"
        doc["fallback_sources"] = [
            dict(route) for route in (doc.get("fallback_sources") or [])
            if isinstance(route, dict) and _strong(route) and route_language(route) == "KO"
        ]
        note = "Korean route recovered from byte-verified same-host language sibling of an already verified annual PDF."
        doc["notes"] = "; ".join(x for x in (str(doc.get("notes") or "").strip(), note) if x)
        recovered.append({
            "document_id": doc.get("document_id"),
            "report_year": _year(doc),
            "old_url": old_url,
            "new_url": chosen,
            "action": "PROMOTED_BYTE_VERIFIED_KOREAN_LANGUAGE_SIBLING",
        })
        out_docs.append(doc)

    documents = dict(documents)
    documents["documents"] = out_docs
    audit.setdefault("stages", {})["korean_sibling_route_recovery"] = {
        "policy": "SAME_HOST_EXPLICIT_LANGUAGE_TOKEN_AND_PDF_BYTES_REQUIRED",
        "attempted": attempted,
        "recovered": recovered,
        "recovered_years": sorted({
            int(x["report_year"]) for x in recovered if x.get("report_year") is not None
        }),
    }
    if http is None and getattr(client, "audit", None):
        audit.setdefault("http_attempts", []).extend(client.audit)
    return documents


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
