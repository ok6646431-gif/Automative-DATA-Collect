"""Promote complete multi-site scope from an explicit official domestic-site page."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from orchestrator import g0_domestic_site_catalog as catalog
from orchestrator import zero_touch_discovery as base


URL_HINTS = ("site", "location", "plant", "factory", "dome", "domestic", "company")


def enrich(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    stages = audit.get("stages") or {}
    official = stages.get("official_site") or {}
    root = str(official.get("resolved_official_root") or "")
    if not root:
        stages["domestic_site_catalog_enrichment"] = {"status": "NOT_APPLICABLE_NO_OFFICIAL_ROOT"}
        return discovery, documents, audit

    urls: List[str] = []
    corp_docs = stages.get("corporate_documents") or {}
    for value in list(corp_docs.get("report_index_pages") or []) + list(official.get("sample_pages") or []):
        url = str(value or "")
        low = url.casefold()
        if url and base._same_org_host(root, url) and any(hint in low for hint in URL_HINTS):
            if url not in urls:
                urls.append(url)

    http = base.Http(timeout=(5, 15))
    fetched: List[base.Page] = []
    for url in urls[:16]:
        r = http.get(url)
        if not r or r.status_code >= 400:
            continue
        fetched.append(base.Page(r.url, base._soup_text(r.text), r.text, r.status_code))
        result = catalog.discover(
            str(discovery.get("current_legal_name") or discovery.get("requested_company_name") or ""),
            fetched,
        )
        if not result:
            continue
        sites, scope, unresolved = result
        discovery["domestic_site_candidates"] = sites
        discovery["requested_scope"] = scope
        discovery["unresolved_items"] = [
            x for x in (discovery.get("unresolved_items") or [])
            if x.get("code") != "SITE_SCOPE_NOT_UNIQUELY_RESOLVED"
        ] + unresolved
        stages["site_scope"] = {
            "sites": sites,
            "requested_scope": scope,
            "unresolved": unresolved,
            "recovered_from": "EXPLICIT_DOMESTIC_SITE_CATALOG",
        }
        stages["domestic_site_catalog_enrichment"] = {
            "status": "RECOVERED",
            "catalog_url": fetched[-1].url,
            "site_count": len(sites),
        }
        audit.setdefault("http_attempts", []).extend(http.audit)
        return discovery, documents, audit

    stages["domestic_site_catalog_enrichment"] = {
        "status": "NO_MULTI_SITE_CATALOG_RESOLVED",
        "urls_checked": urls[:16],
    }
    audit.setdefault("http_attempts", []).extend(http.audit)
    return discovery, documents, audit
