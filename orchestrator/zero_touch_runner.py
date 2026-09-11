"""Runtime entry point wiring version-tolerant public adapters into G0.

The runner also owns the live-network safety boundary.  All G0 Http instances share
one process-wide wall-clock budget so a slow corporate site or report archive cannot
consume the entire GitHub Actions job.  When the budget is exhausted, later requests
fail closed and the existing discovery/gap policies decide what can be promoted.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator import dart_public_resolver
from orchestrator import g0_authority_site_recovery
from orchestrator import g0_data_attr_report_recovery
from orchestrator import g0_domestic_site_catalog_enrichment
from orchestrator import g0_entity_continuity_policy
from orchestrator import g0_entity_window_normalization
from orchestrator import g0_evidence_enrichment
from orchestrator import g0_first_publication_recovery
from orchestrator import g0_generic_js_report_recovery
from orchestrator import g0_kind_disclosure_recovery
from orchestrator import g0_live_adapters
from orchestrator import g0_official_site_recovery
from orchestrator import g0_plain_href_report_recovery
from orchestrator import g0_promotion_policy
from orchestrator import g0_public_disclosure_enrichment
from orchestrator import g0_rename_chronology_recovery
from orchestrator import g0_report_catalog_policy
from orchestrator import g0_report_enrichment
from orchestrator import g0_report_entity_policy
from orchestrator import g0_report_finalizer
from orchestrator import g0_scripted_report_enrichment
from orchestrator import g0_scripted_report_navigation
from orchestrator import g0_staged_official_recovery
from orchestrator import zero_touch_discovery


# One live G0 process may instantiate several Http clients across legal identity,
# official-site recovery and report enrichment.  They all consume the same budget.
G0_NETWORK_BUDGET_SECONDS = 480
G0_DEFAULT_HTTP_TIMEOUT = (4, 8)
_G0_NETWORK_DEADLINE = time.monotonic() + G0_NETWORK_BUDGET_SECONDS
_ORIGINAL_HTTP = zero_touch_discovery.Http


class _BudgetedHttp(_ORIGINAL_HTTP):
    def __init__(self, timeout=G0_DEFAULT_HTTP_TIMEOUT):
        super().__init__(timeout=timeout)
        self._budget_notice_emitted = False

    def _runtime_budget_exhausted(self) -> bool:
        exhausted = time.monotonic() >= _G0_NETWORK_DEADLINE
        if exhausted and not self._budget_notice_emitted:
            self.audit.append({
                "method": "RUNTIME_GUARD",
                "status": "BUDGET_EXHAUSTED",
                "budget_seconds": G0_NETWORK_BUDGET_SECONDS,
            })
            self._budget_notice_emitted = True
        return exhausted

    def get(self, url: str, **kwargs):
        if self._runtime_budget_exhausted():
            return None
        return super().get(url, **kwargs)

    def post(self, url: str, **kwargs):
        if self._runtime_budget_exhausted():
            return None
        return super().post(url, **kwargs)


zero_touch_discovery.Http = _BudgetedHttp

# Corporate sites commonly publish domestic plants under a broader "global network"
# navigation hub. Treat that navigation wording as a location signal while the existing
# Korean road-address and operational-site parsers still decide which entries are
# domestic sites. This widens navigation discovery without weakening site verification.
def _extend_tokens(values, *items):
    return tuple(dict.fromkeys((*values, *items)))


g0_domestic_site_catalog_enrichment.LOCATION_URL_HINTS = _extend_tokens(
    g0_domestic_site_catalog_enrichment.LOCATION_URL_HINTS,
    "global", "network",
)
g0_domestic_site_catalog_enrichment.LOCATION_WORDS = _extend_tokens(
    g0_domestic_site_catalog_enrichment.LOCATION_WORDS,
    "글로벌네트워크", "글로벌 네트워크", "global network",
)
g0_domestic_site_catalog_enrichment.STRONG_LOCATION_WORDS = _extend_tokens(
    g0_domestic_site_catalog_enrichment.STRONG_LOCATION_WORDS,
    "글로벌네트워크", "글로벌 네트워크", "global network",
)


def _robust_official_domain_links(http, domain, terms):
    """Locate first-party URLs in modern search markup without trusting search text.

    Search engines are used only as locators.  Their direct, redirect, cite, data-URL
    and displayed-text forms are parsed by the same hardened routine already used for
    official-site recovery.  Every returned URL is then restricted back to the
    requested official domain (or its subdomains); downstream code still has to fetch
    and verify the target itself before using any evidence from it.
    """
    raw_domain = str(domain or "").strip()
    if not raw_domain:
        return []
    domain_host = zero_touch_discovery._host(
        raw_domain if "://" in raw_domain else "https://" + raw_domain
    )
    if not domain_host:
        return []
    query = f"site:{domain_host} {terms}"
    search_urls = (
        "https://www.google.com/search?q=" + zero_touch_discovery.quote(query) + "&num=20",
        "https://www.bing.com/search?q=" + zero_touch_discovery.quote(query) + "&count=20",
        "https://html.duckduckgo.com/html/?q=" + zero_touch_discovery.quote(query),
    )
    found = []
    for search_url in search_urls:
        r = http.get(search_url)
        if not r or r.status_code >= 400:
            continue
        for candidate in g0_official_site_recovery._search_result_links(search_url, r.text):
            candidate_host = zero_touch_discovery._host(candidate)
            if candidate_host == domain_host or candidate_host.endswith("." + domain_host):
                if candidate not in found:
                    found.append(candidate.split("#", 1)[0])
        if found:
            break
    return found


# Use one robust, fail-closed search-result parser across official-site and report
# discovery instead of maintaining a weaker report-specific parser.
zero_touch_discovery.search_official_domain_links = _robust_official_domain_links
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
    pages, links = g0_staged_official_recovery.crawl_official(
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

    # Bounded parsers get first use of the live-network budget.  They inspect already
    # verified report-index pages and can resolve arbitrary static JS/data-attribute
    # controls without crawling the wider corporate site.  Broad navigation remains a
    # fallback, followed by a second generic pass for any new report pages it reveals.
    documents = g0_generic_js_report_recovery.enrich(discovery, documents, audit)
    documents = g0_data_attr_report_recovery.enrich(discovery, documents, audit)
    documents = g0_plain_href_report_recovery.enrich(discovery, documents, audit)
    documents = g0_scripted_report_enrichment.enrich(discovery, documents, audit)
    documents = g0_scripted_report_navigation.enrich(discovery, documents, audit)
    documents = g0_generic_js_report_recovery.enrich(discovery, documents, audit)
    documents = g0_report_entity_policy.normalize(discovery, documents, audit)
    documents = g0_report_finalizer.finalize(discovery, documents, audit)
    documents = g0_report_catalog_policy.normalize_verified_catalog_gaps(
        discovery, documents, audit
    )
    documents = g0_first_publication_recovery.recover(discovery, documents, audit)
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
    discovery = g0_entity_continuity_policy.normalize(discovery, audit)
    discovery, documents, audit = g0_promotion_policy.apply(discovery, documents, audit)

    # Fresh Discovery owns document identity/coverage, but a stronger transport route
    # already byte-verified for the same DART-anchored legal entity must not disappear
    # merely because a later crawl rediscovers a weaker company-hosted URL.
    try:
        from orchestrator.document_route_merge import merge_document_routes
        existing_company_path = ROOT / 'requests/company_discovery.json'
        existing_documents_path = ROOT / 'requests/document_evidence.json'
        if existing_company_path.exists() and existing_documents_path.exists():
            existing_company = json.loads(existing_company_path.read_text(encoding='utf-8'))
            existing_documents = json.loads(existing_documents_path.read_text(encoding='utf-8'))
            before = [str(x.get('source_url') or '') for x in documents.get('documents', []) or [] if isinstance(x, dict)]
            documents = merge_document_routes(existing_company, existing_documents, discovery, documents)
            after = [str(x.get('source_url') or '') for x in documents.get('documents', []) or [] if isinstance(x, dict)]
            audit.setdefault('stages', {})['document_route_merge'] = {
                'status': 'APPLIED',
                'primary_routes_changed': sum(1 for a, b in zip(before, after) if a != b),
            }
    except Exception as exc:
        audit.setdefault('stages', {})['document_route_merge'] = {
            'status': 'SKIPPED_ERROR',
            'error': f'{type(exc).__name__}: {exc}',
        }
    return discovery, documents, audit


zero_touch_discovery.discover = _enriched_discover

if __name__ == "__main__":
    raise SystemExit(zero_touch_discovery.main())
