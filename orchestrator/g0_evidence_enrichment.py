"""Generic evidence enrichment for company-name-only G0 discovery.

This module strengthens two evidence classes that commonly appear on official company
websites but are not always available from DART's company popup:

* an operational site address embedded near plant/yard language; and
* an explicitly stated legal-name change on an official company page.

The rules are deliberately evidence-based and company-agnostic.  A repeated footer
address alone is not enough to become an operational site, and a rename is accepted
only when the official page states a date, a predecessor, and the current name in the
same change context.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from orchestrator import zero_touch_discovery as base


OPERATIONAL_SITE_WORDS = (
    "사업장", "공장", "조선소", "생산야드", "생산 야드", "생산기지", "생산 기지",
    "산단", "산업단지", "plant", "factory", "shipyard", "yard",
)
ADDRESS_CONTEXT_WORDS = ("주소", "위치", "소재지", "location")


def _compact_address(value: str) -> str:
    return re.sub(r"[^0-9가-힣]+", "", value or "")


def _clean_quoted_company_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n'\"‘’“”")
    # Official rename notices often append the English name in parentheses.  The
    # Korean predecessor before the parenthesis is the useful source search alias.
    text = re.sub(r"\s*[\(\[].*$", "", text).strip()
    return text


def discover_site_candidates(
    company: str,
    pages: Sequence[base.Page],
    dart: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    """Resolve one primary operational site without promoting a generic HQ footer.

    Every candidate must come from the DART-anchored official web boundary.  A site
    becomes VERIFIED only when the same address is repeated and at least one occurrence
    is locally associated with operational language, or when DART itself supplies the
    address.  This prevents a corporate contact address from automatically becoming a
    plant for multi-site companies.
    """

    hits: Dict[str, Dict[str, Any]] = {}
    company_norm = base.normalize_name(company)

    for page in pages:
        value = page.text or ""
        for m in base.ADDRESS_RE.finditer(value):
            raw = re.sub(r"\s+", " ", m.group(1)).strip()
            key = _compact_address(raw)
            if not key:
                continue
            start = max(0, m.start() - 700)
            end = min(len(value), m.end() + 350)
            context = value[start:end]
            context_fold = context.casefold()
            page_fold = (page.url + " " + value).casefold()
            operational = sum(1 for w in OPERATIONAL_SITE_WORDS if w in context_fold)
            address_context = sum(1 for w in ADDRESS_CONTEXT_WORDS if w in context_fold)
            company_context = bool(company_norm and company_norm in base.normalize_name(context))
            # Operational evidence is weighted most heavily.  Company/address wording
            # is supporting evidence but cannot by itself turn a footer into a plant.
            local_score = operational * 6 + address_context * 2 + (3 if company_context else 0)
            if any(w in page.url.casefold() for w in ("location", "status", "company", "about")):
                local_score += 1
            entry = hits.setdefault(key, {
                "address": raw, "count": 0, "score": 0, "operational_hits": 0,
                "company_context_hits": 0, "pages": [], "contexts": [],
            })
            entry["count"] += 1
            entry["score"] += local_score
            entry["operational_hits"] += 1 if operational else 0
            entry["company_context_hits"] += 1 if company_context else 0
            if page.url not in entry["pages"]:
                entry["pages"].append(page.url)
            if operational or address_context:
                entry["contexts"].append(context[:900])

    dart_source = str(dart.get("source_url") or "")
    if dart.get("address"):
        raw = re.sub(r"\s+", " ", str(dart["address"])).strip()
        key = _compact_address(raw)
        entry = hits.setdefault(key, {
            "address": raw, "count": 0, "score": 0, "operational_hits": 0,
            "company_context_hits": 0, "pages": [], "contexts": [],
        })
        entry["count"] += 2
        entry["score"] += 20
        entry["operational_hits"] += 1
        if dart_source and dart_source not in entry["pages"]:
            entry["pages"].append(dart_source)

    ranked = sorted(
        hits.values(),
        key=lambda x: (x["operational_hits"], x["score"], x["count"]),
        reverse=True,
    )
    verified = [
        x for x in ranked
        if x["operational_hits"] >= 1
        and (x["count"] >= 2 or dart_source in x["pages"])
        and x["score"] >= 8
    ]

    sites: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    unambiguous = False
    if verified:
        if len(verified) == 1:
            unambiguous = True
        else:
            first, second = verified[0], verified[1]
            # Require a material evidence lead.  Similar-strength operational sites are
            # intentionally left for review rather than guessing one primary site.
            unambiguous = (
                first["operational_hits"] >= second["operational_hits"] + 1
                or first["score"] >= second["score"] + 10
            )

    if verified and unambiguous:
        top = verified[0]
        cid = base._slug(company + " " + top["address"])
        sites.append({
            "candidate_id": cid,
            "site_name_raw": f"{company} 주요 사업장",
            "address_raw": top["address"],
            "business_unit_raw": "official-site primary operational location",
            "source_locator": top["pages"][0],
            "identity_status": "VERIFIED",
            "verification_state": "VERIFIED",
            "discovery_evidence": {
                "official_page_count": len(top["pages"]),
                "address_occurrences": top["count"],
                "operational_context_hits": top["operational_hits"],
            },
        })
        scope = {
            "mode": "SITE_SET",
            "label": f"{company} 주요 사업장",
            "candidate_ids": [cid],
            "raw_collection_policy": "PRESERVE_COMPANY_WIDE",
            "archive_policy": "FILTER_TO_REQUESTED_SCOPE",
            "analysis_policy": "FILTER_TO_REQUESTED_SCOPE",
        }
    else:
        scope = {
            "mode": "COMPANY", "label": company,
            "raw_collection_policy": "PRESERVE_COMPANY_WIDE",
            "archive_policy": "FILTER_TO_REQUESTED_SCOPE",
            "analysis_policy": "FILTER_TO_REQUESTED_SCOPE",
        }
        unresolved.append({
            "code": "SITE_SCOPE_NOT_UNIQUELY_RESOLVED",
            "subject": company,
            "detail": "Company identity is verified, but one primary operational domestic site was not independently resolved from official pages. Company-wide scope is preserved; no site is guessed.",
            "source_locator": dart_source or None,
        })
    return sites, scope, unresolved


def _extract_date(text: str) -> Optional[str]:
    for pat in (
        r"(20\d{2})[.년\-\s]+(\d{1,2})[.월\-\s]+(\d{1,2})일?",
        r"(20\d{2})-(\d{1,2})-(\d{1,2})",
    ):
        m = re.search(pat, text)
        if not m:
            continue
        try:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except (TypeError, ValueError):
            continue
    return None


def _quoted_rename_pair(text: str, current_name: str) -> Optional[str]:
    """Return predecessor from an explicit 'OLD ... 에서 NEW ... 로 변경' statement."""
    current_norm = base.normalize_name(current_name)
    patterns = (
        r"(?:상호|회사명|사명)(?:를|을)?\s*[‘“\"'](?P<old>[^’”\"']{2,180})[’”\"']\s*에서\s*[‘“\"'](?P<new>.{2,220}?)(?:[’”\"']?\s*)(?:으로|로)\s*변경",
        r"[‘“\"'](?P<old>[^’”\"']{2,180})[’”\"']\s*에서\s*[‘“\"'](?P<new>.{2,220}?)(?:[’”\"']?\s*)(?:으로|로)\s*변경",
    )
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.I):
            old = _clean_quoted_company_name(m.group("old"))
            new = _clean_quoted_company_name(m.group("new"))
            if not old or not new:
                continue
            new_norm = base.normalize_name(new)
            if current_norm and (current_norm in new_norm or new_norm in current_norm):
                if base.normalize_name(old) != current_norm:
                    return old
    return None


def extract_rename_date_and_names(
    pages: Sequence[base.Page],
    current_name: str,
    known_history: Sequence[str],
) -> Optional[Dict[str, Any]]:
    """Resolve a bounded rename from official pages, with DART history if available."""

    current_norm = base.normalize_name(current_name)
    history = [
        x for x in known_history
        if base.normalize_name(x) and base.normalize_name(x) != current_norm
    ]
    for page in pages:
        text = page.text or ""
        if not any(w in text for w in ("상호", "사명", "회사명", "명칭")) or "변경" not in text:
            continue
        if current_norm not in base.normalize_name(text):
            continue
        date = _extract_date(text)
        if not date:
            continue
        predecessor = next(
            (h for h in history if base.normalize_name(h) in base.normalize_name(text)),
            None,
        )
        evidence_type = "DART_HISTORY_PLUS_OFFICIAL_PAGE"
        if not predecessor:
            predecessor = _quoted_rename_pair(text, current_name)
            evidence_type = "EXPLICIT_OFFICIAL_RENAME_STATEMENT"
        if predecessor:
            return {
                "date": date,
                "predecessor": predecessor,
                "source_locator": page.url,
                "evidence_type": evidence_type,
            }
    return None


def enrich_discovery_from_audit(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Promote an explicit official rename when DART history itself was unavailable."""

    stage = ((audit.get("stages") or {}).get("name_history") or {})
    rename = stage.get("bounded_rename") or {}
    predecessor = str(rename.get("predecessor") or "").strip()
    date = str(rename.get("date") or "").strip()
    if not predecessor or not re.match(r"^20\d{2}-\d{2}-\d{2}$", date):
        return discovery, documents, audit
    if base.normalize_name(predecessor) == base.normalize_name(discovery.get("current_legal_name")):
        return discovery, documents, audit

    rename_year = int(date[:4])
    start_year = int((((discovery.get("collection_policy") or {}).get("requested_history_window") or {}).get("start_year") or rename_year))
    existing_history = discovery.setdefault("historical_legal_names", [])
    if not any(base.normalize_name(x.get("name")) == base.normalize_name(predecessor) for x in existing_history if isinstance(x, dict)):
        existing_history.append({
            "name": predecessor,
            "alias_type": "former_legal_name",
            "active_period": {"start_year": start_year, "end_year": rename_year},
            "verification_state": "VERIFIED",
            "source_locator": rename.get("source_locator"),
        })

    discovery["current_legal_name_active_period"] = {"start_year": rename_year}
    for alias in discovery.get("company_aliases", []):
        if not isinstance(alias, dict):
            continue
        alias_norm = base.normalize_name(alias.get("name"))
        current_norm = base.normalize_name(discovery.get("current_legal_name"))
        requested_norm = base.normalize_name(discovery.get("requested_company_name"))
        if alias_norm and alias_norm in {current_norm, requested_norm}:
            alias["active_period"] = {"start_year": rename_year}

    restructuring = discovery.setdefault("corporate_restructuring_evidence", [])
    if not any(
        isinstance(x, dict)
        and x.get("event_type") == "rename"
        and x.get("effective_date") == date
        for x in restructuring
    ):
        restructuring.append({
            "event_type": "rename",
            "effective_period": {"start_year": rename_year, "end_year": rename_year},
            "effective_date": date,
            "predecessor": predecessor,
            "successor": discovery.get("current_legal_name"),
            "scope": "same legal entity name change",
            "verification_state": "VERIFIED",
            "source_locator": rename.get("source_locator"),
        })

    # A successfully bounded rename is positive evidence, not a review item.
    discovery["unresolved_items"] = [
        x for x in discovery.get("unresolved_items", [])
        if x.get("code") != "HISTORICAL_NAME_PERIOD_UNRESOLVED"
    ]
    audit["gate_status"] = "PASS" if not discovery.get("unresolved_items") else "REVIEW_REQUIRED"
    return discovery, documents, audit
