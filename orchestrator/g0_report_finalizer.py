"""Final arbitration for annual-report representation after all G0 recovery stages.

Earlier stages intentionally inspect broad page context. A full annual-report PDF can
therefore be demoted to a summary when the surrounding report page contains a section
named "Highlight". The same broad context can also give a PDF a misleading annual year.
This finalizer treats concrete verified route evidence as stronger than broad context,
but fails closed when the route itself explicitly carries a conflicting year.

When a verified digital/HTML representation and a verified full-report PDF exist for the
same year, the concrete PDF wins annual coverage. The digital record is omitted from the
annual document set to avoid duplicate same-year coverage; its landing page remains the
PDF source locator and is still available in discovery audit evidence.

The rule is company-agnostic and conservative. It never promotes a URL whose filename
itself says highlight/summary/brief, never overrides an explicit issuer conflict, and
never silently accepts an annual route whose explicit year excludes the claimed year.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple
from urllib.parse import unquote, urlparse

from orchestrator import g0_report_entity_policy as entity_policy
from orchestrator.document_year_guard import route_year_conflicts, strong_route_matches_year
from orchestrator.document_language_preference import prefer_korean_sustainability


def _pdf_filename(url: str) -> str:
    try:
        return unquote(urlparse(str(url or "")).path.rsplit("/", 1)[-1])
    except Exception:
        return str(url or "")


def _pdf_basename(url: str) -> str:
    return _pdf_filename(url).casefold()


def _explicit_full_report_pdf(doc: Dict[str, Any]) -> bool:
    url = str(doc.get("source_url") or "")
    basename = _pdf_basename(url)
    expected = str(doc.get("expected_extension") or "").casefold()
    if expected != "pdf" and not basename.endswith(".pdf"):
        return False
    if any(token.casefold() in basename for token in entity_policy.SUMMARY_TOKENS):
        return False
    marker_value = basename.replace("-", " ").replace("_", " ")
    return (
        "report" in marker_value
        or "보고서" in marker_value
        or any(marker.casefold().replace("_", " ").replace("-", " ") in marker_value
               for marker in entity_policy.REPORT_MARKERS)
    )


def _concrete_pdf_title(doc: Dict[str, Any]) -> str:
    """Prefer a readable filename title only when it independently carries the year."""
    if not _explicit_full_report_pdf(doc):
        return ""
    try:
        year = int(doc.get("report_year"))
    except (TypeError, ValueError):
        return ""
    filename = _pdf_filename(str(doc.get("source_url") or ""))
    if str(year) not in filename:
        return ""
    stem = re.sub(r"(?i)\.pdf$", "", filename)
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


def _year(doc: Dict[str, Any]) -> int | None:
    try:
        return int(doc.get("report_year"))
    except (TypeError, ValueError):
        return None


def _repair_or_reject_route_year_conflict(doc: Dict[str, Any]) -> Tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    """Replace a conflicting primary only with a strong explicitly matching fallback."""
    year = _year(doc)
    if year is None or not route_year_conflicts(doc, year):
        return dict(doc), None

    conflict = {
        "document_id": doc.get("document_id"),
        "report_year": year,
        "rejected_source_url": doc.get("source_url"),
        "reason": "EXPLICIT_PRIMARY_ROUTE_YEAR_CONFLICT",
        "action": "REJECTED",
    }
    for fallback in doc.get("fallback_sources", []) or []:
        if not isinstance(fallback, dict) or not strong_route_matches_year(fallback, year):
            continue
        repaired = dict(doc)
        for field in ("source_url", "source_locator", "expected_extension", "verification_status", "notes"):
            if field in fallback:
                repaired[field] = fallback.get(field)
            elif field in {"source_locator", "expected_extension", "notes"}:
                repaired.pop(field, None)
        repaired["fallback_sources"] = [
            dict(item) for item in (doc.get("fallback_sources", []) or [])
            if isinstance(item, dict)
            and str(item.get("source_url") or "") != str(fallback.get("source_url") or "")
            and not route_year_conflicts(item, year)
        ]
        repaired["route_merge_status"] = "REPLACED_EXPLICIT_YEAR_CONFLICT_PRIMARY"
        conflict["action"] = "REPLACED_WITH_MATCHING_VERIFIED_FALLBACK"
        conflict["replacement_source_url"] = fallback.get("source_url")
        return repaired, conflict
    return None, conflict


def _sanitize_route_year_conflicts(docs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    out: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    for doc in docs:
        if doc.get("document_type") not in {"SUSTAINABILITY_REPORT", "SUSTAINABILITY_REPORT_SUMMARY"}:
            out.append(doc)
            continue
        repaired, conflict = _repair_or_reject_route_year_conflict(doc)
        if conflict:
            conflicts.append(conflict)
        if repaired is not None:
            out.append(repaired)
    return out, conflicts


def _promotable_pdf_years(discovery: Dict[str, Any], docs: List[Dict[str, Any]]) -> set[int]:
    """Years with an explicit full-report PDF currently mislabeled as summary."""
    years: set[int] = set()
    for doc in docs:
        if doc.get("document_type") != "SUSTAINABILITY_REPORT_SUMMARY":
            continue
        year = _year(doc)
        if year is None or not _explicit_full_report_pdf(doc):
            continue
        alignment, _ = entity_policy.entity_alignment(
            discovery, str(doc.get("title") or ""), str(doc.get("source_url") or "")
        )
        if alignment != "CONFLICT":
            years.add(year)
    return years


def _verified_annual_pdf_years(docs: List[Dict[str, Any]]) -> set[int]:
    """Years already represented by a verified annual PDF, including opaque endpoints."""
    years: set[int] = set()
    for doc in docs:
        if doc.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        if str(doc.get("representation") or "").upper() == "DIGITAL_REPORT":
            continue
        year = _year(doc)
        if year is None:
            continue
        expected = str(doc.get("expected_extension") or "").casefold()
        basename = _pdf_basename(str(doc.get("source_url") or ""))
        if expected != "pdf" and not basename.endswith(".pdf"):
            continue
        if str(doc.get("verification_status") or "").upper() not in {"VERIFIED", "SOURCE_VERIFIED"}:
            continue
        years.add(year)
    return years


def finalize(discovery: Dict[str, Any], documents: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
    raw_docs = list(documents.get("documents", []) or [])
    docs, route_year_conflicts_found = _sanitize_route_year_conflicts(raw_docs)
    pdf_override_years = _promotable_pdf_years(discovery, docs)
    verified_annual_pdf_years = _verified_annual_pdf_years(docs)
    pdf_preferred_years = pdf_override_years | verified_annual_pdf_years

    existing_full_years = {
        int(d.get("report_year"))
        for d in docs
        if d.get("document_type") == "SUSTAINABILITY_REPORT"
        and d.get("report_year")
        and str(d.get("representation") or "").upper() != "DIGITAL_REPORT"
    }

    promoted: List[Dict[str, Any]] = []
    normalized_titles: List[Dict[str, Any]] = []
    superseded_digital: List[Dict[str, Any]] = []
    out: List[Dict[str, Any]] = []
    for doc in docs:
        if doc.get("document_type") == "SUSTAINABILITY_REPORT":
            year = _year(doc)
            if (
                year in pdf_preferred_years
                and str(doc.get("representation") or "").upper() == "DIGITAL_REPORT"
            ):
                superseded_digital.append({
                    "document_id": doc.get("document_id"),
                    "report_year": year,
                    "source_url": doc.get("source_url"),
                    "reason": "CONCRETE_VERIFIED_FULL_REPORT_PDF_PREFERRED_OVER_DIGITAL_REPRESENTATION",
                })
                continue
            item = dict(doc)
            concrete_title = _concrete_pdf_title(item)
            if concrete_title and concrete_title != str(item.get("title") or ""):
                normalized_titles.append({
                    "document_id": item.get("document_id"),
                    "report_year": item.get("report_year"),
                    "old_title": item.get("title"),
                    "new_title": concrete_title,
                    "reason": "CONCRETE_YEAR_SPECIFIC_FULL_REPORT_PDF_FILENAME",
                })
                item["title"] = concrete_title
            out.append(item)
            continue

        if doc.get("document_type") != "SUSTAINABILITY_REPORT_SUMMARY":
            out.append(doc)
            continue
        year = _year(doc)
        if year is None:
            out.append(doc)
            continue
        if year in existing_full_years or not _explicit_full_report_pdf(doc):
            out.append(doc)
            continue

        title = str(doc.get("title") or "")
        url = str(doc.get("source_url") or "")
        alignment, issuers = entity_policy.entity_alignment(discovery, title, url)
        if alignment == "CONFLICT":
            out.append(doc)
            continue

        item = dict(doc)
        item["document_type"] = "SUSTAINABILITY_REPORT"
        item["document_category"] = "SUSTAINABILITY_REPORT"
        item["importance"] = "CORE"
        item["entity_alignment"] = alignment
        item.pop("coverage_role", None)
        concrete_title = _concrete_pdf_title(item)
        if concrete_title and concrete_title != title:
            normalized_titles.append({
                "document_id": item.get("document_id"),
                "report_year": year,
                "old_title": title,
                "new_title": concrete_title,
                "reason": "CONCRETE_YEAR_SPECIFIC_FULL_REPORT_PDF_FILENAME",
            })
            item["title"] = concrete_title
        item["notes"] = (
            str(item.get("notes") or "").rstrip()
            + " Final representation arbitration: explicit full-report PDF target overrides incidental summary/highlight words in surrounding page context."
        ).strip()
        out.append(item)
        existing_full_years.add(year)
        promoted.append({
            "document_id": item.get("document_id"),
            "report_year": year,
            "source_url": url,
            "entity_alignment": alignment,
            "explicit_issuers": issuers,
            "reason": "EXPLICIT_FULL_REPORT_PDF_TARGET",
        })

    promoted_years = {int(x["report_year"]) for x in promoted}
    gaps = []
    removed_gaps: List[Dict[str, Any]] = []
    for gap in documents.get("gaps", []) or []:
        try:
            gap_year = int(gap.get("year"))
        except (TypeError, ValueError):
            gap_year = None
        if gap.get("document_type") == "SUSTAINABILITY_REPORT" and gap_year in promoted_years:
            removed_gaps.append(dict(gap))
            continue
        gaps.append(gap)

    covered_years = {
        _year(doc) for doc in out
        if doc.get("document_type") == "SUSTAINABILITY_REPORT" and _year(doc) is not None
    }
    existing_gap_years = {
        int(g.get("year"))
        for g in gaps
        if isinstance(g, dict)
        and g.get("document_type") == "SUSTAINABILITY_REPORT"
        and str(g.get("year") or "").isdigit()
    }
    for conflict in route_year_conflicts_found:
        if conflict.get("action") != "REJECTED":
            continue
        year = int(conflict["report_year"])
        if year in covered_years or year in existing_gap_years:
            continue
        gaps.append({
            "gap_id": f"AUTO_SUSTAINABILITY_{year}_EXPLICIT_ROUTE_YEAR_CONFLICT",
            "document_type": "SUSTAINABILITY_REPORT",
            "year": year,
            "blocking": True,
            "status": "DISCOVERY_GAP",
            "verification_status": "UNVERIFIED",
            "reason": "EXPLICIT_ROUTE_YEAR_CONFLICT_NO_MATCHING_VERIFIED_ALTERNATIVE",
        })
        existing_gap_years.add(year)

    out, language_preference = prefer_korean_sustainability(discovery, out)
    documents["documents"] = out
    documents["gaps"] = gaps
    documents["discovery_status"] = (
        "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE"
        if not any(g.get("blocking") for g in gaps)
        else "PARTIAL"
    )
    audit.setdefault("stages", {})["report_finalizer"] = {
        "promoted_full_report_pdfs": promoted,
        "verified_annual_pdf_years": sorted(verified_annual_pdf_years),
        "superseded_digital_reports": superseded_digital,
        "normalized_pdf_titles": normalized_titles,
        "route_year_conflicts": route_year_conflicts_found,
        "removed_resolved_gaps": removed_gaps,
        "language_preference": language_preference,
    }
    return documents
