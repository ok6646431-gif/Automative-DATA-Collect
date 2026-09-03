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
from orchestrator import g0_evidence_enrichment
from orchestrator import g0_kind_disclosure_recovery
from orchestrator import g0_live_adapters
from orchestrator import g0_official_site_recovery
from orchestrator import g0_public_disclosure_enrichment
from orchestrator import g0_rename_chronology_recovery
from orchestrator import g0_report_catalog_policy
from orchestrator import g0_report_enrichment
from orchestrator import g0_scripted_report_enrichment
from orchestrator import g0_scripted_report_navigation
from orchestrator import zero_touch_discovery

zero_touch_discovery.discover_dart_keys = dart_public_resolver.discover_dart_keys


def _official_rename_signals(pages, company):
    """Record bounded first-party evidence that the current company says it was renamed.

    This is only a gate signal, never predecessor evidence. It prevents a current name
    from being silently projected backwards when a first-party history page explicitly
    says a rename occurred but no predecessor/effective chain has been verified.
    """
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
    pages, links = g0_official_site_recovery.crawl_official(
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
    """Publish the recovered official root before downstream enrichment uses it."""
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

    # If DART's website field is stale, recover the current first-party homepage from a
    # recent KIND periodic filing before any search-engine-dependent enrichment. The
    # listed-company code and the explicit homepage field in the filing are the trust
    # anchors; the recovered site itself must still be reachable before promotion.
    discovery, documents, audit = g0_authority_site_recovery.enrich(
        discovery, documents, audit
    )

    discovery, documents, audit = g0_evidence_enrichment.enrich_discovery_from_audit(
        discovery, documents, audit
    )

    # Direct official disclosure recovery is the primary path for listed companies.
    # DART already supplies a verified six-digit company/stock code, so KIND can be
    # queried deterministically without a search engine. Only when that path cannot
    # resolve a verified rename chain do we pay the cost of the older locator-based
    # public-disclosure and chronology fallbacks.
    discovery = g0_kind_disclosure_recovery.enrich(discovery, audit)
    if not _has_verified_rename(discovery):
        discovery = g0_public_disclosure_enrichment.enrich(discovery, audit)
    if not _has_verified_rename(discovery):
        discovery = g0_rename_chronology_recovery.enrich(discovery, audit)

    # Strict annual-report classification rejects brochures and generic PDFs. The
    # first scripted adapter handles opaque download tokens on pages reached normally;
    # the navigation fallback recovers report index pages hidden behind semantic DOM or
    # JavaScript navigation on the already trusted report host.
    documents = g0_report_enrichment.enrich(discovery, documents, audit)
    documents = g0_scripted_report_enrichment.enrich(discovery, documents, audit)
    documents = g0_scripted_report_navigation.enrich(discovery, documents, audit)
    # A requested history window does not imply that every issuer published one report
    # every year. If a verified first-party report catalog itself shows an interior year
    # missing between published years, preserve that absence as NOT_PUBLISHED rather
    # than blocking the zero-touch gate as a false collection failure.
    documents = g0_report_catalog_policy.normalize_verified_catalog_gaps(
        discovery, documents, audit
    )
    g0_report_enrichment.refresh_document_unresolved(discovery, documents, audit)

    # DART establishment date describes legal-entity continuity, not the spelling of
    # the current legal name. A verified rename below overwrites the current-name
    # active period with the true rename boundary.
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
            discovery["current_legal_name_active_period"] = {"start_year": int(rename_year)}
            for alias in discovery.get("company_aliases", []) or []:
                if not isinstance(alias, dict):
                    continue
                if alias.get("alias_type") in {
                    "requested_name", "current_brand_name", "current_alias",
                    "english_legal_name", "current_legal_alias",
                }:
                    alias["active_period"] = {"start_year": int(rename_year)}

    # Run this once more after every enrichment so an unresolved first-party rename
    # signal can never be hidden by otherwise successful site/document discovery.
    g0_kind_disclosure_recovery.enforce_historical_continuity_gate(discovery, audit)
    audit["gate_status"] = "PASS" if not discovery.get("unresolved_items") else "REVIEW_REQUIRED"
    return discovery, documents, audit


zero_touch_discovery.discover = _enriched_discover

if __name__ == "__main__":
    raise SystemExit(zero_touch_discovery.main())
