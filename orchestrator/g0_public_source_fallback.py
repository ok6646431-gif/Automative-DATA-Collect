"""Company-agnostic public-source fallback for a blocked G0 document/site gate.

This prepares five independent public registry searches after G0 produced a DART-
verified legal entity but could not promote a fully resolved site or document scope.
It never promotes G0, invents facility identity, or overwrites current requests.

A verified company permits bounded name-based discovery; without a verified site
the collectors must retain source-native facility ambiguity and may return REVIEW.
"""
from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from orchestrator.company_profile_builder import compile_discovery
from orchestrator.g0_site_verification_policy import WEAK_EXTRACTION_CONTRACTS
from orchestrator.request_builder import build

ELIGIBLE_SITE_BLOCKERS = frozenset({
    "SITE_IDENTITY_UNRESOLVED", "SITE_SCOPE_NOT_UNIQUELY_RESOLVED",
})
ALLOWED_DEFERRED_REVIEWS = frozenset({
    "CORPORATE_DOCUMENT_COVERAGE_INCOMPLETE",
    "HISTORICAL_LEGAL_NAME_PREDECESSOR_UNRESOLVED",
})
PUBLIC_SOURCES = ("ENVINFO", "PRTR", "CHEM_STATS", "CLEANSYS_AIR", "SOOSIRO_WATER")


class SourceFallbackIneligible(ValueError):
    """Source-only collection cannot safely bind the requested legal entity."""


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _verified_dart(discovery: dict, audit: dict) -> dict:
    if discovery.get("company_verification_state") != "VERIFIED":
        raise SourceFallbackIneligible("G0 company identity not VERIFIED")
    legal_stage = ((audit.get("stages") or {}).get("legal_identity") or {})
    resolved = legal_stage.get("resolved") or {}
    key = str(resolved.get("select_key") or "").strip()
    legal_name = str(resolved.get("korean_name") or "").strip()
    source_url = str(resolved.get("source_url") or "").strip()
    source = urlparse(source_url)
    if not re.fullmatch(r"\d{6,12}", key):
        raise SourceFallbackIneligible("unique DART select_key missing")
    if source.hostname not in {"englishdart.fss.or.kr", "dart.fss.or.kr"}:
        raise SourceFallbackIneligible("DART legal-entity evidence origin invalid")
    if parse_qs(source.query).get("selectKey", [""])[0] != key:
        raise SourceFallbackIneligible("DART legal-entity locator/key mismatch")
    if not legal_name or legal_name != str(discovery.get("current_legal_name") or "").strip():
        raise SourceFallbackIneligible("DART legal name does not match discovered legal name")
    if not str(resolved.get("website") or "").strip():
        raise SourceFallbackIneligible("DART legal evidence has no website")
    if not str(resolved.get("corporation_registration_number") or resolved.get("tax_id") or "").strip():
        raise SourceFallbackIneligible("DART legal entity has no independent registration identifier")
    verified = [
        item for item in discovery.get("identity_evidence", []) or []
        if isinstance(item, dict)
        and item.get("verification_state") in {"VERIFIED", "SOURCE_VERIFIED"}
        and str(item.get("source_locator") or "") == source_url
    ]
    if not verified:
        raise SourceFallbackIneligible("legal name is not supported by verified DART source evidence")
    return resolved


def _site_is_verified(site: dict) -> bool:
    evidence = site.get("discovery_evidence") or {}
    contract = str(evidence.get("extraction_contract") or "").upper()
    return (
        site.get("verification_state") in {"VERIFIED", "SOURCE_VERIFIED"}
        and site.get("identity_status") == "CONFIRMED"
        and contract not in WEAK_EXTRACTION_CONTRACTS
        and bool(str(site.get("source_locator") or "").strip())
    )


def build_source_only(discovery: dict, audit: dict) -> tuple[dict, dict, dict]:
    legal = _verified_dart(discovery, audit)
    promotion = ((audit.get("stages") or {}).get("promotion_policy") or {})
    if not promotion or audit.get("gate_status") != "REVIEW_REQUIRED":
        raise SourceFallbackIneligible("fallback applies only to reviewed G0 with recorded promotion policy")
    blocked = promotion.get("blocking_unresolved_items")
    if not isinstance(blocked, list):
        raise SourceFallbackIneligible("promotion blocking review contract missing")
    original_blockers = discovery.get("unresolved_items") or []
    if original_blockers != blocked:
        raise SourceFallbackIneligible("G0 company/promotion review items differ")
    if any(not isinstance(item, dict) or item.get("code") not in ELIGIBLE_SITE_BLOCKERS
           for item in blocked):
        raise SourceFallbackIneligible("non-site identity/continuity blocker prevents fallback")
    deferred = promotion.get("deferred_review_items") or []
    if any(not isinstance(item, dict) or item.get("code") not in ALLOWED_DEFERRED_REVIEWS
           for item in deferred):
        raise SourceFallbackIneligible("unclassified deferred discovery issue")

    # Fail closed on unverified or text-proximity sites. The company-wide name search
    # can discover source-native site identifiers, but no G0 candidate is promoted.
    source_discovery = deepcopy(discovery)
    original_sites = [s for s in source_discovery.get("domestic_site_candidates", [])
                      if isinstance(s, dict)]
    verified_sites = [s for s in original_sites if _site_is_verified(s)]
    source_discovery["domestic_site_candidates"] = verified_sites
    source_discovery["requested_scope"] = {
        "mode": "COMPANY",
        "label": str(discovery.get("current_legal_name")) + " verified legal entity only",
        "raw_collection_policy": "PRESERVE_COMPANY_WIDE",
    }
    # Identity blockers have already been classified above. This projection is a
    # *separate* collection request; it never changes the G0 audit or approval.
    source_discovery["unresolved_items"] = []

    profile, summary = compile_discovery(source_discovery)
    profile["requested_scope"] = source_discovery["requested_scope"]
    request = build(profile)
    if tuple(request.get("sources", {}).keys()) != PUBLIC_SOURCES:
        raise SourceFallbackIneligible("five-source request contract incomplete")
    for key in PUBLIC_SOURCES:
        gate = request["sources"][key].get("identity_gate")
        if not gate or gate.get("enabled") is not True:
            raise SourceFallbackIneligible("source identity gate missing: " + key)
        if str(legal["korean_name"]) not in (gate.get("current_entity_names") or []):
            raise SourceFallbackIneligible("DART legal entity absent from source gate")
        if not verified_sites and gate.get("verified_sites"):
            raise SourceFallbackIneligible("unverified site was promoted into a source identity gate")
    if summary.get("review_required_count"):
        # Collection is still possible only for independent source discovery, but
        # report anything the period/alias compiler could not fully validate.
        unexpected = [
            row for row in summary.get("unresolved_discovery_items", []) or []
            if row.get("code") not in {
                "MINIMUM_HISTORY_UNAVAILABLE", "SURVEY_ROUND_SPAN_SHORT",
                "HISTORICAL_ALIAS_PERIOD_UNRESOLVED",
            }
        ]
        if unexpected:
            raise SourceFallbackIneligible("source-only profile contains unresolved identity/scope: " +
                                           json.dumps(unexpected, ensure_ascii=False)[:1200])

    evidence = {
        "status": "COMPANY_VERIFIED_PUBLIC_DISCOVERY_ONLY",
        "source_g0_gate": audit.get("gate_status"),
        "request_id": discovery.get("request_id"),
        "legal_name": legal.get("korean_name"),
        "dart_select_key": legal.get("select_key"),
        "dart_source_url": legal.get("source_url"),
        "verified_site_count": len(verified_sites),
        "unverified_site_candidates_excluded": len(original_sites) - len(verified_sites),
        "g0_blocking_site_reviews": blocked,
        "g0_deferred_reviews": deferred,
        "discovery_limitations": summary.get("unresolved_discovery_items", []),
        "publication_or_tms_applicability_verified": False,
        "notes": [
            "G0 remains REVIEW_REQUIRED and is not promoted.",
            "Name-only public queries do not establish facility applicability or zero emissions.",
            "Missing facility identity cannot be reported as a verified TMS registry no-match.",
        ],
    }
    return profile, request, evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    root = Path(args.discovery_dir)
    target = Path(args.out_dir)
    profile, request, evidence = build_source_only(
        _json(root / "company_discovery.json"),
        _json(root / "Discovery_Audit.json"),
    )
    _write(target / "profile.json", profile)
    _write(target / "request.json", request)
    _write(target / "identity_evidence.json", evidence)
    print(json.dumps({
        "status": evidence["status"], "request_id": evidence["request_id"],
        "legal_name": evidence["legal_name"],
        "verified_sites": evidence["verified_site_count"],
        "excluded_sites": evidence["unverified_site_candidates_excluded"],
        "sources": list(request["sources"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
