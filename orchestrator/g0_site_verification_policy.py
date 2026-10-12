"""Fail closed on facility identity inferred only from flattened webpage proximity.

First-party provenance verifies that a page belongs to the company, not that a
particular arbitrary text fragment is a correctly paired site name and address.
The G0 site gate must use the per-candidate extraction contract when deciding
whether verified facility identifiers can be passed to downstream collectors.
"""
from __future__ import annotations

from typing import Any, Dict

WEAK_EXTRACTION_CONTRACTS = frozenset({
    "FLATTENED_TEXT_FALLBACK",
    "LOCATION_PAGE_NEAREST_OPERATIONAL_NAME",
})


def normalize(discovery: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
    pending = []
    for site in discovery.get("domestic_site_candidates", []) or []:
        if not isinstance(site, dict):
            continue
        evidence = site.get("discovery_evidence") or {}
        contract = str(evidence.get("extraction_contract") or "").upper()
        if contract not in WEAK_EXTRACTION_CONTRACTS:
            continue
        # The textual match can be used as a search hint but is not a verified
        # name/address pairing. Never feed it to the verified-sites allowlist.
        site["identity_status"] = "CANDIDATE"
        site["verification_state"] = "UNVERIFIED"
        pending.append({
            "candidate_id": str(site.get("candidate_id") or ""),
            "name": str(site.get("site_name_raw") or ""),
            "address": str(site.get("address_raw") or ""),
            "extraction_contract": contract,
            "source_locator": site.get("source_locator"),
        })

    if pending:
        unresolved = discovery.setdefault("unresolved_items", [])
        existing = {
            (str(x.get("code")), str(x.get("subject")))
            for x in unresolved if isinstance(x, dict)
        }
        for item in pending:
            key = ("SITE_IDENTITY_UNRESOLVED", item["candidate_id"])
            if key not in existing:
                unresolved.append({
                    "code": key[0],
                    "subject": key[1],
                    "detail": (
                        "Text-proximity site name/address pairing is a candidate, not "
                        "verified facility identity; independent structured or "
                        "source-native evidence required"
                    ),
                    "source_locator": item["source_locator"],
                })
    audit.setdefault("stages", {})["site_verification_policy"] = {
        "status": "REVIEW_REQUIRED" if pending else "PASS",
        "downgraded_candidate_count": len(pending),
        "downgraded_candidates": pending,
        "rule": "Weak flattened-text or nearest-name extraction cannot establish a verified facility",
    }
    return discovery
