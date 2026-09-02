"""Runtime entry point wiring version-tolerant public adapters into G0."""

from __future__ import annotations

import re
import sys
from pathlib import Path

# When invoked as ``python orchestrator/zero_touch_runner.py`` Python places the
# orchestrator directory, not the repository root, on sys.path. Add the root so the
# same imports work in Actions and in ``python -m``/unit-test execution.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator import dart_public_resolver
from orchestrator import g0_evidence_enrichment
from orchestrator import g0_live_adapters
from orchestrator import g0_official_site_recovery
from orchestrator import g0_public_disclosure_enrichment
from orchestrator import g0_report_enrichment
from orchestrator import zero_touch_discovery

zero_touch_discovery.discover_dart_keys = dart_public_resolver.discover_dart_keys
zero_touch_discovery.crawl_official = g0_official_site_recovery.crawl_official
zero_touch_discovery.discover_site_candidates = g0_live_adapters.discover_site_candidates
zero_touch_discovery._extract_rename_date_and_names = g0_live_adapters.extract_rename_date_and_names

_base_discover = zero_touch_discovery.discover


def _enriched_discover(company: str, start_year: int = 2020, max_pages: int = 90):
    discovery, documents, audit = _base_discover(company, start_year=start_year, max_pages=max_pages)
    discovery, documents, audit = g0_evidence_enrichment.enrich_discovery_from_audit(discovery, documents, audit)

    # DART's public former-name popup can legitimately return an empty table.  When an
    # official company history page indicates a rename but does not state predecessor
    # and exact date, use search engines only to locate KRX/DART public disclosures and
    # promote the rename only after the official disclosure states OLD, NEW and date.
    discovery = g0_public_disclosure_enrichment.enrich(discovery, audit)

    # Annual-report coverage is stricter than broad document discovery.  Brochures and
    # generic downloadable PDFs cannot satisfy an annual series; a directly linked
    # same-organization ESG/report host may be crawled only for document evidence.
    documents = g0_report_enrichment.enrich(discovery, documents, audit)
    g0_report_enrichment.refresh_document_unresolved(discovery, documents, audit)

    # Make stale-DART-website recovery explicit in the audit. Search engines, when
    # used, were candidate locators only; the accepted host was re-verified from its
    # own fetched corporate pages by g0_official_site_recovery.
    official_stage = (audit.get("stages") or {}).get("official_site")
    if isinstance(official_stage, dict):
        recovery = dict(g0_official_site_recovery.last_recovery or {})
        official_stage["recovery"] = recovery
        if recovery.get("resolved_url"):
            official_stage["resolved_official_root"] = recovery["resolved_url"]

    # DART establishment date describes legal-entity continuity. A later rename only
    # bounds the spelling of the current legal name; it never creates a new company.
    legal = (((audit.get("stages") or {}).get("legal_identity") or {}).get("resolved") or {})
    established = str(legal.get("establishment_date") or "")
    m = re.search(r"(?:19|20)\d{2}", established)
    if m:
        discovery["legal_entity_active_period"] = {"start_year": int(m.group(0))}

    # Defensive normalization for outputs produced by older adapters during replay.
    for site in discovery.get("domestic_site_candidates", []) or []:
        if site.get("verification_state") in {"VERIFIED", "SOURCE_VERIFIED"}:
            site["identity_status"] = "CONFIRMED"

    # If an official rename boundary was verified, all aliases representing the
    # current identity inherit the same start year. This prevents current English or
    # brand names from being searched before the legal-name change.
    rename_events = [
        x for x in discovery.get("corporate_restructuring_evidence", []) or []
        if isinstance(x, dict) and x.get("event_type") == "rename"
    ]
    if rename_events:
        event = sorted(rename_events, key=lambda x: str(x.get("effective_date") or ""))[-1]
        period = event.get("effective_period") or {}
        rename_year = period.get("start_year")
        if rename_year:
            for alias in discovery.get("company_aliases", []) or []:
                if not isinstance(alias, dict):
                    continue
                if alias.get("alias_type") in {
                    "requested_name", "current_brand_name", "current_alias",
                    "english_legal_name", "current_legal_alias",
                }:
                    alias["active_period"] = {"start_year": int(rename_year)}

    audit["gate_status"] = "PASS" if not discovery.get("unresolved_items") else "REVIEW_REQUIRED"
    return discovery, documents, audit


zero_touch_discovery.discover = _enriched_discover

if __name__ == "__main__":
    raise SystemExit(zero_touch_discovery.main())
