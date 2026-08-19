"""Compile validated company Discovery evidence into the existing profile contract.

This module deliberately does no discovery or fuzzy identity resolution.  It only
validates and deterministically transforms evidence supplied by the control plane.
"""

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


SOURCES = ("ENVINFO", "PRTR", "CHEM_STATS", "CLEANSYS_AIR", "SOOSIRO_WATER")
FULL_HISTORY_DEFAULTS = {"ENVINFO", "PRTR", "CHEM_STATS", "CLEANSYS_AIR", "SOOSIRO_WATER"}


class DiscoveryValidationError(ValueError):
    """Raised when the Discovery document cannot be compiled safely."""


def _year(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise DiscoveryValidationError(f"{field} must be a year")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise DiscoveryValidationError(f"{field} must be a year") from exc
    if result < 1000 or result > 9999:
        raise DiscoveryValidationError(f"{field} must be a four-digit year")
    return result


def _unique(items: Iterable[Any]) -> List[Any]:
    result = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def _review(code: str, subject: str, detail: str, source_locator: Any = None) -> Dict[str, Any]:
    return {"status": "REVIEW_REQUIRED", "code": code, "subject": subject,
            "detail": detail, "source_locator": source_locator}


def _range_plan(source: str, raw: Dict[str, Any], minimum: int,
                reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    available = raw.get("available_history") or {}
    requested = raw.get("requested_window") or {}
    a0 = _year(available["start_year"], f"{source}.available_history.start_year") if available.get("start_year") is not None else None
    a1 = _year(available["end_year"], f"{source}.available_history.end_year") if available.get("end_year") is not None else None
    r0 = _year(requested["start_year"], f"{source}.requested_window.start_year") if requested.get("start_year") is not None else None
    r1 = _year(requested["end_year"], f"{source}.requested_window.end_year") if requested.get("end_year") is not None else None
    prefer_full = bool(raw.get("prefer_full_history", source in FULL_HISTORY_DEFAULTS))
    if a0 is not None and a1 is not None and a0 > a1:
        raise DiscoveryValidationError(f"{source} available history is reversed")
    if r0 is not None and r1 is not None and r0 > r1:
        raise DiscoveryValidationError(f"{source} requested window is reversed")
    if prefer_full and a0 is not None and a1 is not None:
        start, end = a0, a1
    elif r1 is not None:
        end = min(r1, a1) if a1 is not None else r1
        desired = end - minimum + 1
        start = min(r0, desired) if r0 is not None else desired
        if a0 is not None:
            start = max(start, a0)
    elif a1 is not None:
        end = a1
        start = a0 if prefer_full and a0 is not None else max(a0 or (end - minimum + 1), end - minimum + 1)
    else:
        raise DiscoveryValidationError(f"{source} needs an available or requested end year; years are never guessed")
    if end - start + 1 < minimum:
        reviews.append(_review("MINIMUM_HISTORY_UNAVAILABLE", source,
                               f"Only {end - start + 1} disclosed years can be selected; policy minimum is {minimum}."))
    plan = {"start_year": start, "end_year": end}
    for key in ("page_size", "max_details", "max_pages", "request_delay_ms"):
        if key in raw:
            plan[key] = raw[key]
    return plan


def _chem_plan(raw: Dict[str, Any], minimum: int, reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    available = sorted({_year(x, "CHEM_STATS.available_survey_rounds") for x in raw.get("available_survey_rounds", [])})
    requested = sorted({_year(x, "CHEM_STATS.requested_survey_rounds") for x in raw.get("requested_survey_rounds", [])})
    prefer_full = bool(raw.get("prefer_full_history", True))

    def meets(values: List[int]) -> bool:
        return len(values) >= 3 and values[-1] - values[0] + 1 >= minimum

    if prefer_full and available:
        years = available
    else:
        years = [x for x in requested if not available or x in available]
        if years and not meets(years):
            older = [x for x in available if x < years[0]]
            newer = [x for x in available if x > years[-1]]
            for value in reversed(older):
                years.insert(0, value)
                if meets(years):
                    break
            if not meets(years):
                for value in newer:
                    years.append(value)
                    if meets(years):
                        break
    if not years:
        raise DiscoveryValidationError("CHEM_STATS needs disclosed survey rounds; annual years are never manufactured")
    if not meets(years):
        reviews.append(_review("SURVEY_ROUND_SPAN_SHORT", "CHEM_STATS",
                               f"Disclosed rounds {years[0]}..{years[-1]} ({len(years)} rounds) do not meet the minimum of 3 rounds spanning {minimum} inclusive calendar years."))
    plan = {"years": years}
    for key in ("max_pages", "request_delay_ms"):
        if key in raw:
            plan[key] = raw[key]
    return plan


def _aliases(discovery: Dict[str, Any], reviews: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    current = discovery["current_legal_name"]
    current_period = discovery.get("current_legal_name_active_period") or {}
    facts = [{"name": current, "alias_type": "current_legal_name",
              "active_period": current_period,
              "verification_state": discovery.get("company_verification_state", "UNVERIFIED"),
              "confidence": discovery.get("confidence")}]
    facts += discovery.get("company_aliases", [])
    facts += discovery.get("historical_legal_names", [])
    aliases = []
    for fact in facts:
        name = fact.get("name") if isinstance(fact, dict) else fact
        if not isinstance(name, str) or not name.strip():
            reviews.append(_review("ALIAS_NAME_UNRESOLVED", "company_alias", "Alias has no usable raw name."))
            continue
        alias_type = fact.get("alias_type", "alias") if isinstance(fact, dict) else "alias"
        period = fact.get("active_period") or {} if isinstance(fact, dict) else {}
        start = period.get("start_year")
        end = period.get("end_year")
        scope = "predecessor" if alias_type in {"merger_predecessor", "spin_off_predecessor"} else ("historical" if alias_type in {"historical_legal_name", "former_legal_name"} else "current")
        entry = {"term": name, "scope": scope,
                 "year_start": _year(start, f"active_period for {name}") if start is not None else 0,
                 "year_end": _year(end, f"active_period for {name}") if end is not None else "auto",
                 "alias_type": alias_type,
                 "verification_state": fact.get("verification_state", "UNVERIFIED") if isinstance(fact, dict) else "UNVERIFIED",
                 "confidence": fact.get("confidence") if isinstance(fact, dict) else None,
                 "source_locator": fact.get("source_locator") if isinstance(fact, dict) else None}
        if scope == "historical" and (start is None or end is None):
            # Preserve the unresolved fact, but never turn an unknown validity
            # period into an unbounded collector search.
            entry["search_enabled"] = False
            reviews.append(_review("HISTORICAL_ALIAS_PERIOD_UNRESOLVED", name,
                                   "Historical alias search period is not fully bounded.", entry["source_locator"]))
        else:
            entry["search_enabled"] = True
        if not any(a["term"] == name and a["year_start"] == entry["year_start"] and a["year_end"] == entry["year_end"] for a in aliases):
            aliases.append(entry)
    return aliases


def compile_discovery(discovery: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return ``(company_profile, discovery_summary)`` without mutating input."""
    discovery = deepcopy(discovery)
    if discovery.get("schema_version") != "1.0":
        raise DiscoveryValidationError("unsupported or missing Discovery schema_version")
    for field in ("request_id", "requested_company_name", "current_legal_name"):
        if not isinstance(discovery.get(field), str) or not discovery[field].strip():
            raise DiscoveryValidationError(f"{field} is required")
    reviews = list(discovery.get("unresolved_items", []))
    reviews = [dict(x, status="REVIEW_REQUIRED") for x in reviews]
    if discovery.get("company_verification_state", "UNVERIFIED") != "VERIFIED":
        reviews.append(_review("COMPANY_IDENTITY_NOT_VERIFIED", discovery["requested_company_name"],
                               "Current legal company identity is not verified."))
    aliases = _aliases(discovery, reviews)
    policy = discovery.get("collection_policy") or {}
    minimum = int(policy.get("minimum_history_years", 5))
    if minimum < 5:
        minimum = 5
    sources = policy.get("sources") or {}
    missing = [x for x in SOURCES if x not in sources]
    if missing:
        raise DiscoveryValidationError(f"collection_policy.sources missing: {', '.join(missing)}")
    source_plan = {
        "ENVINFO": _range_plan("ENVINFO", sources["ENVINFO"], minimum, reviews),
        "PRTR": _range_plan("PRTR", sources["PRTR"], minimum, reviews),
        "CHEM_STATS": _chem_plan(sources["CHEM_STATS"], minimum, reviews),
        "CLEANSYS_AIR": _range_plan("CLEANSYS_AIR", sources["CLEANSYS_AIR"], minimum, reviews),
    }
    water = _range_plan("SOOSIRO_WATER", sources["SOOSIRO_WATER"], minimum, reviews)
    daily = sources["SOOSIRO_WATER"].get("daily_available_years", [])
    source_plan["SOOSIRO_WATER"] = {"annual_years": list(range(water["start_year"], water["end_year"] + 1)),
                                     "daily_years": sorted({_year(x, "SOOSIRO_WATER.daily_available_years") for x in daily})}
    evidence = discovery.get("identity_evidence", [])
    sites = discovery.get("domestic_site_candidates", [])
    for site in sites:
        if site.get("identity_status", "UNRESOLVED") in {"CANDIDATE", "REVIEW_REQUIRED", "UNRESOLVED"}:
            reviews.append(_review("SITE_IDENTITY_UNRESOLVED", site.get("candidate_id", "site_candidate"),
                                   "Discovery did not resolve this site candidate.", site.get("source_locator")))
    exclusion_evidence = discovery.get("related_entity_exclusions", [])
    exclusions = []
    for item in exclusion_evidence:
        if isinstance(item, dict):
            name = item.get("name")
            state = item.get("verification_state", "UNVERIFIED")
            locator = item.get("source_locator")
        else:
            name = item
            state = "UNVERIFIED"
            locator = None
        if not name:
            continue
        if state == "VERIFIED":
            if name not in exclusions:
                exclusions.append(name)
        else:
            reviews.append(_review("RELATED_ENTITY_EXCLUSION_NOT_VERIFIED", str(name),
                                   "Related-entity exclusion is preserved as evidence but is not active until VERIFIED.", locator))
    profile = {
        "profile_version": "2.0", "discovery_schema_version": discovery["schema_version"],
        "request_id": discovery["request_id"], "requested_company_name": discovery["requested_company_name"],
        "company_display_name": discovery["current_legal_name"], "resolution_evidence": evidence,
        "aliases": aliases, "related_entity_exclusions": exclusions,
        "related_entity_exclusion_evidence": exclusion_evidence,
        "site_address_anchors": {}, "site_candidates": sites,
        "corporate_restructuring_evidence": discovery.get("corporate_restructuring_evidence", []),
        "event_evidence_references": discovery.get("event_evidence_references", []),
        "discovery_review_required": reviews, "source_plan": source_plan,
    }
    summary = {
        "summary_schema_version": "1.0", "discovery_schema_version": discovery["schema_version"],
        "request_id": discovery["request_id"],
        "company_resolved": discovery.get("company_verification_state") == "VERIFIED",
        "current_name": discovery["current_legal_name"],
        "current_name_active_period": deepcopy(discovery.get("current_legal_name_active_period") or {}),
        "historical_aliases": [a for a in aliases if a["scope"] != "current"],
        "site_candidates": sites, "related_entity_exclusions": exclusion_evidence,
        "unresolved_discovery_items": reviews,
        "collection_policies_selected": {"minimum_history_years": minimum,
                                          "full_history_sources": sorted([s for s in SOURCES if sources[s].get("prefer_full_history", s in FULL_HISTORY_DEFAULTS)])},
        "derived_collection_windows": source_plan, "review_required_count": len(reviews),
    }
    return profile, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile company Discovery evidence")
    parser.add_argument("discovery")
    parser.add_argument("--out", default="requests/company_profile.json")
    parser.add_argument("--summary", default="Company_Discovery_Summary.json")
    args = parser.parse_args()
    discovery = json.loads(Path(args.discovery).read_text(encoding="utf-8"))
    profile, summary = compile_discovery(discovery)
    for target, payload in ((args.out, profile), (args.summary, summary)):
        path = Path(target); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"request_id": profile["request_id"], "profile": args.out,
                      "summary": args.summary, "review_required_count": summary["review_required_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
