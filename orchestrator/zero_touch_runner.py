"""Runtime entry point wiring version-tolerant public adapters into G0."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator import dart_public_resolver
from orchestrator import g0_authority_site_recovery
from orchestrator import g0_data_attr_report_recovery
from orchestrator import g0_domestic_site_catalog_enrichment
from orchestrator import g0_entity_window_normalization
from orchestrator import g0_evidence_enrichment
from orchestrator import g0_generic_js_report_recovery
from orchestrator import g0_kind_disclosure_recovery
from orchestrator import g0_live_adapters
from orchestrator import g0_official_site_recovery
from orchestrator import g0_public_disclosure_enrichment
from orchestrator import g0_rename_chronology_recovery
from orchestrator import g0_report_catalog_policy
from orchestrator import g0_report_enrichment
from orchestrator import g0_scripted_report_enrichment
from orchestrator import g0_scripted_report_navigation
from orchestrator import g0_thin_shell_recovery
from orchestrator import zero_touch_discovery

zero_touch_discovery.discover_dart_keys = dart_public_resolver.discover_dart_keys


def _official_rename_signals(pages, company):
    out = []
    company_norm = zero_touch_discovery.normalize_name(company)
    phrase_re = re.compile(r"(?:상호\s*(?:가|를|을)?\s*변경|상호변경|사명\s*(?:이|을|를)?\s*변경)")
    year_re = re.compile(r"(?:19|20)\d{2}")
    for page in pages or []:
        text = re.sub(r"\s+", " ", str(getattr(page, "text", "") or ""))
        for match in phrase_re.finditer(text):
            context = text[max(0, match.start() - 500): match.end() + 700]
            if company_norm and company_norm not in zero_touch_discovery.normalize_name(context):
                continue
            years = [int(x) for x in year_re.findall(context)]
            item = {
                "year": years[-1] if years else None,
                "url": str(getattr(page, "url", "") or ""),
                "context": context[:900],
            }
            if item not in out:
                out.append(item)
    return out[:20]


def _crawl_official_with_continuity_signal(http, start_url, company, max_pages=90):
    pages, links = g0_thin_shell_recovery.crawl_official(
        http, start_url, company, max_pages=max_pages
    )
    g0_official_site_recovery.last_recovery["rename_signals"] = _official_rename_signals(
        pages, company
    )
    return pages, links


zero_touch_discovery.crawl_official = _crawl_official_with_continuity_signal
zero_touch_discovery.discover_site_candidates = g0_live_adapters.discover_site_candidates
zero_touch_discovery._extract_rename_date_and_names = g0_live_adapters.extract_rename_date_and_names

_base_discover = zero_touch_discovery.discover


def _attach_official_recovery(audit):
    official_stage = (audit.get("stages") or {}).get("official_site")
    if not isinstance(official_stage, dict):
        return
    recovery = dict(g0_official_site_recovery.last_recovery or {})
    official_stage["recovery"] = recovery
    if recovery.get("resolved_url"):
        official_stage["resolved_official_root"] = recovery["resolved_url"]


def _has_verified_rename(discovery):
    return any(
        isinstance(x, dict)
        and x.get("event_type") == "rename"
        and x.get("verification_state") == "VERIFIED"
        for x in discovery.get("corporate_restructuring_evidence", []) or []
    )


def _enriched_discover(company: str, start_year: int = 2020, max_pages: int = 90):
    discovery, documents, audit = _base_discover(company, start_year=start_year, max_pages=max_pages)
    _attach_official_recovery(audit)

    discovery, documents, audit = g0_authority_site_recovery.enrich(
        discovery, documents, audit
    )
    discovery, documents, audit = g0_domestic_site_catalog_enrichment.enrich(
        discovery, documents, audit
    )

    discovery, documents, audit = g0_evidence_enrichment.enrich_discovery_from_audit(
        discovery, documents, audit
    )

    discovery = g0_kind_disclosure_recovery.enrich(discovery, audit)
    if not _has_verified_rename(discovery):
        discovery = g0_public_disclosure_enrichment.enrich(discovery, audit)
    if not _has_verified_rename(discovery):
        discovery = g0_rename_chronology_recovery.enrich(discovery, audit)

    documents = g0_report_enrichment.enrich(discovery, documents, audit)
    documents = g0_scripted_report_enrichment.enrich(discovery, documents, audit)
    documents = g0_scripted_report_navigation.enrich(discovery, documents, audit)
    documents = g0_generic_js_report_recovery.enrich(discovery, documents, audit)
    # Some first-party report libraries bind a shared click handler to a CSS class and
    # derive the PDF viewer URL from data-* metadata instead of placing a function call
    # on each link. Reconstruct only a statically inspectable same-host handler and
    # require real PDF bytes before promotion.
    documents = g0_data_attr_report_recovery.enrich(discovery, documents, audit)
    documents = g0_report_catalog_policy.normalize_verified_catalog_gaps(
        discovery, documents, audit
    )
    documents = g0_entity_window_normalization.normalize(discovery, documents, audit)
    g0_report_enrichment.refresh_document_unresolved(discovery, documents, audit)

    legal = (((audit.get("stages") or {}).get("legal_identity") or {}).get("resolved") or {})
    established = str(legal.get("establishment_date") or "")
    m = re.search(r"(?:19|20)\d{2}", established)
    if m:
        discovery["legal_entity_active_period"] = {"start_year": int(m.group(0))}

    for site in discovery.get("domestic_site_candidates", []) or []:
        if site.get("verification_state") in {"VERIFIED", "SOURCE_VERIFIED"}:
            site["identity_status"] = "CONFIRMED"

    rename_events = [
        x for x in discovery.get("corporate_restructuring_evidence", []) or []
        if isinstance(x, dict) and x.get("event_type") == "rename"
    ]
    if rename_events:
        event = sorted(rename_events, key=lambda x: str(x.get("effective_date") or ""))[-1]
        rename_year = (event.get("effective_period") or {}).get("start_year")
        if rename_year:
            discovery["current_legal_name_active_period"] = {"start_year": int(rename_year)}
            for alias in discovery.get("company_aliases", []) or []:
                if not isinstance(alias, dict):
                    continue
                if alias.get("alias_type") in {
                    "requested_name", "current_brand_name", "current_alias",
                    "english_legal_name", "current_legal_alias",
                }:
                    alias["active_period"] = {"start_year": int(rename_year)}

    g0_kind_disclosure_recovery.enforce_historical_continuity_gate(discovery, audit)
    audit["gate_status"] = "PASS" if not discovery.get("unresolved_items") else "REVIEW_REQUIRED"
    return discovery, documents, audit


zero_touch_discovery.discover = _enriched_discover

if __name__ == "__main__":
    raise SystemExit(zero_touch_discovery.main())
