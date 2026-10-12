"""Classify unresolved report *searches* without asserting nonpublication.

Only the final, bounded first-party discovery pass may classify ordinary missing
annual report years as NOT_FOUND_IN_BOUNDED_SCOPE. Positive evidence that a
document exists, a failed PDF fetch, an incomplete official-site crawl, or a
conflicted legal entity must stay blocking.
"""
from __future__ import annotations

from urllib.parse import urlparse


def _host(value: str) -> str:
    return str(urlparse(str(value or "")).hostname or "").casefold().removeprefix("www.")


def normalize(discovery: dict, documents: dict, audit: dict) -> dict:
    stages = audit.get("stages") or {}
    official = stages.get("official_site") or {}
    document_stage = stages.get("corporate_documents") or {}
    fresh = stages.get("fresh_process_document_recovery") or {}
    target = str(official.get("resolved_official_root") or official.get("dart_website") or "")
    allowed_host = _host(target if "://" in target else "https://" + target)
    pages = official.get("page_urls") or []
    checked = official.get("pages_crawled")
    gaps = documents.get("gaps") or []
    summary = {"policy": "BOUNDED_FIRST_PARTY_REPORT_NONFIND", "converted_years": []}
    stages["bounded_document_discovery_policy"] = summary

    # This is a bounded discovery classification, not an optional shortcut
    # around recovery, official-site failure, or legal entity validation.
    if (not allowed_host or not isinstance(pages, list)
            or len(pages) < 2 or not isinstance(checked, int)
            or checked != len(pages)
            or not fresh or fresh.get("status") not in {"RECOVERED", "NO_POSITIVE_RECOVERY"}):
        summary["status"] = "NOT_ENOUGH_DISCOVERY_EVIDENCE"
        return documents
    if str(discovery.get("company_verification_state") or "") != "VERIFIED":
        summary["status"] = "COMPANY_NOT_VERIFIED"
        return documents
    if any(not _host(p) or (
        _host(p) != allowed_host and not _host(p).endswith("." + allowed_host)
    ) for p in pages):
        summary["status"] = "OUT_OF_SCOPE_OFFICIAL_PAGES"
        return documents
    if any(str(item.get("status") or "") == "BUDGET_EXHAUSTED"
           for item in audit.get("http_attempts") or [] if isinstance(item, dict)):
        summary["status"] = "NETWORK_BUDGET_EXHAUSTED"
        return documents

    # A site displaying a year-specific report but failing to expose the
    # actual asset is a known missing document, not a harmless nonfind.
    # A verified report-index page can identify report editions which the
    # bounded link parser could not resolve. Keep those misses for review.
    if document_stage.get("report_index_pages"):
        summary["status"] = "REPORT_INDEX_REQUIRES_EXPLICIT_YEAR_COVERAGE"
        return documents
    positive_years = set()
    for row in [*(document_stage.get("report_candidates") or []),
                *(document_stage.get("unverified_report_links") or [])]:
        try:
            positive_years.add(int(row.get("year")))
        except (TypeError, ValueError):
            pass

    unresolved = []
    for gap in gaps:
        if not isinstance(gap, dict) or not gap.get("blocking"):
            continue
        reason = str(gap.get("reason") or "")
        status = str(gap.get("status") or "")
        try:
            year = int(gap.get("year"))
        except (TypeError, ValueError):
            year = None
        if (gap.get("document_type") == "SUSTAINABILITY_REPORT"
                and status == "DISCOVERY_GAP"
                and "No verified annual report file was discovered within the bounded official-site crawl" in reason
                and year is not None and year not in positive_years):
            unresolved.append(gap)
        else:
            summary["status"] = "POSITIVE_DOCUMENT_EVIDENCE_OR_UNRESOLVED_SCOPE"
            return documents

    # A complete, verified annual series must stay unqualified PASS; do
    # not manufacture a limitation when no uncertain gap remains.
    if not unresolved:
        summary["status"] = "NO_UNRESOLVED_REPORT_NONFINDS"
        return documents

    # Classify only after every known positive report target was recovered.
    for gap in unresolved:
        gap["status"] = "NOT_FOUND_IN_BOUNDED_SCOPE"
        gap["blocking"] = False
        gap["severity"] = "LIMITATION"
        gap["verification_status"] = "UNVERIFIED"
        gap["reason"] = (
            "The documented bounded first-party search did not locate a verified "
            "annual document for this year; this does not establish nonpublication."
        )
        summary["converted_years"].append(int(gap["year"]))

    documents["discovery_scope"] = {
        **(documents.get("discovery_scope") or {}),
        "official_pages_checked": checked,
        "official_page_urls": pages,
        "official_root": target,
        "publication_certainty": "UNKNOWN_FOR_UNFOUND_YEARS",
        "search_coverage": "BOUNDED_FIRST_PARTY_ONLY",
    }
    documents["discovery_status"] = "COMPLETE_FOR_BOUNDED_OFFICIAL_DISCOVERY"
    summary["status"] = "BOUNDED_NONFINDS_CLASSIFIED"
    return documents
