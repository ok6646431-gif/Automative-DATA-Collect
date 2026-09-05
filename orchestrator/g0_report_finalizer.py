"""Final arbitration for annual-report representation after all G0 recovery stages.

Earlier stages intentionally inspect broad page context. A full annual-report PDF can
therefore be demoted to a summary when the surrounding report page contains a section
named "Highlight". This finalizer uses the concrete document target as the stronger
representation signal: an explicit full-report PDF filename without summary tokens wins
over incidental words in surrounding page text.

The rule is company-agnostic and conservative. It never promotes a URL whose filename
itself says highlight/summary/brief, and it never overrides an explicit issuer conflict.
"""

from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import unquote, urlparse

from orchestrator import g0_report_entity_policy as entity_policy


def _pdf_basename(url: str) -> str:
    try:
        return unquote(urlparse(str(url or "")).path.rsplit("/", 1)[-1]).casefold()
    except Exception:
        return str(url or "").casefold()


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


def finalize(discovery: Dict[str, Any], documents: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
    docs = list(documents.get("documents", []) or [])
    existing_full_years = {
        int(d.get("report_year"))
        for d in docs
        if d.get("document_type") == "SUSTAINABILITY_REPORT" and d.get("report_year")
    }

    promoted: List[Dict[str, Any]] = []
    out: List[Dict[str, Any]] = []
    for doc in docs:
        if doc.get("document_type") != "SUSTAINABILITY_REPORT_SUMMARY":
            out.append(doc)
            continue
        try:
            year = int(doc.get("report_year"))
        except (TypeError, ValueError):
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

    documents["documents"] = out
    documents["gaps"] = gaps
    documents["discovery_status"] = (
        "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE"
        if not any(g.get("blocking") for g in gaps)
        else "PARTIAL"
    )
    audit.setdefault("stages", {})["report_finalizer"] = {
        "promoted_full_report_pdfs": promoted,
        "removed_resolved_gaps": removed_gaps,
    }
    return documents
