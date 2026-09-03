"""Runtime entry point wiring version-tolerant public adapters into G0."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator import dart_public_resolver
from orchestrator import g0_evidence_enrichment
from orchestrator import g0_live_adapters
from orchestrator import g0_official_site_recovery
from orchestrator import g0_public_disclosure_enrichment
from orchestrator import g0_rename_chronology_recovery
from orchestrator import g0_report_enrichment
from orchestrator import g0_scripted_report_enrichment
from orchestrator import g0_scripted_report_navigation
from orchestrator import zero_touch_discovery

zero_touch_discovery.discover_dart_keys = dart_public_resolver.discover_dart_keys
zero_touch_discovery.crawl_official = g0_official_site_recovery.crawl_official
zero_touch_discovery.discover_site_candidates = g0_live_adapters.discover_site_candidates
zero_touch_discovery._extract_rename_date_and_names = g0_live_adapters.extract_rename_date_and_names

_base_discover = zero_touch_discovery.discover


def _attach_official_recovery(audit):
    """Publish the recovered official root before downstream enrichment uses it."""
    official_stage = (audit.get("stages") or {}).get("official_site")
    if not isinstance(official_stage, dict):
        return
    recovery = dict(g0_official_site_recovery.last_recovery or {})
    official_stage["recovery"] = recovery
    if recovery.get("resolved_url"):
        official_stage["resolved_official_root"] = recovery["resolved_url"]


def _enriched_discover(company: str, start_year: int = 2020, max_pages: int = 90):
    discovery, documents, audit = _base_discover(company, start_year=start_year, max_pages=max_pages)
    _attach_official_recovery(audit)

    discovery, documents, audit = g0_evidence_enrichment.enrich_discovery_from_audit(
        discovery, documents, audit
    )

    # First try explicit public-disclosure rename prose.  Then recover the common
    # chronology form (dated resulting legal names), repairing legacy HTML encodings
    # before parsing.  Both remain fail-closed and official-source-only at promotion.
    discovery = g0_public_disclosure_enrichment.enrich(discovery, audit)
    discovery = g0_rename_chronology_recovery.enrich(discovery, audit)

    # Strict annual-report classification rejects brochures and generic PDFs.  The
    # first scripted adapter handles opaque download tokens on pages reached normally;
    # the navigation fallback recovers report index pages hidden behind semantic DOM or
    # JavaScript navigation on the already trusted report host.
    documents = g0_report_enrichment.enrich(discovery, documents, audit)
    documents = g0_scripted_report_enrichment.enrich(discovery, documents, audit)
    documents = g0_scripted_report_navigation.enrich(discovery, documents, audit)
    g0_report_enrichment.refresh_document_unresolved(discovery, documents, audit)

    # DART establishment date describes legal-entity continuity.  A later rename only
    # bounds the spelling of the current legal name; it never creates a new company.
    legal = (((audit.get("stages") or {}).get("legal_identity") or {}).get("resolved") or {})
    established = str(legal.get("establishment_date") or "")
    m = re.search(r"(?:19|20)\d{2}", established)
    if m:
        discovery["legal_entity_active_period"] = {"start_year": int(m.group(0))}

    for site in discovery.get("domestic_site_candidates", []) or []:
        if site.get("verification_state") in {"VERIFIED", "SOURCE_VERIFIED"}:
            site["identity_status"] = "CONFIRMED"

    # If a rename boundary was verified, all aliases representing the current identity
    # inherit the same start year so current names are never searched before the rename.
    rename_events = [
        x for x in discovery.get("corporate_restructuring_evidence", []) or []
        if isinstance(x, dict) and x.get("event_type") == "rename"
    ]
    if rename_events:
        event = sorted(rename_events, key=lambda x: str(x.get("effective_date") or ""))[-1]
        rename_year = (event.get("effective_period") or {}).get("start_year")
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
