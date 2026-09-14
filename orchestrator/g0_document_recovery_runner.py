"""Fresh-process annual-document recovery for G0.

The primary zero-touch discovery process has a hard, shared live-network budget. A slow
corporate site may legitimately consume that budget while still producing a verified
company/site identity and unresolved annual-report gaps. Running the bounded document
fallbacks again in a fresh process gives those fallbacks an independent, shorter budget
without weakening the primary identity/site gate or extending its deadline.

This runner is positive-only: it may add byte/source-verified document routes, but a
failed second pass never converts a missing year into NOT_PUBLISHED and never changes
company/site identity.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator import g0_data_attr_report_recovery
from orchestrator import g0_entity_window_normalization
from orchestrator import g0_first_publication_recovery
from orchestrator import g0_generic_js_report_recovery
from orchestrator import g0_js_form_report_recovery
from orchestrator import g0_kind_sustainability_recovery
from orchestrator import g0_plain_href_report_recovery
from orchestrator import g0_report_catalog_policy
from orchestrator import g0_report_enrichment
from orchestrator import g0_report_entity_policy
from orchestrator import g0_report_finalizer
from orchestrator import g0_scripted_report_enrichment
from orchestrator import g0_scripted_report_navigation
from orchestrator import zero_touch_runner as runtime

DEFAULT_RECOVERY_BUDGET_SECONDS = 150
STRONG_VERIFICATION = {"VERIFIED", "SOURCE_VERIFIED"}


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def blocking_sustainability_years(documents: Dict[str, Any]) -> List[int]:
    delivered = set()
    for doc in documents.get("documents", []) or []:
        if not isinstance(doc, dict) or doc.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        if str(doc.get("verification_status") or "").upper() not in STRONG_VERIFICATION:
            continue
        try:
            delivered.add(int(doc.get("report_year")))
        except (TypeError, ValueError):
            pass

    years = []
    for gap in documents.get("gaps", []) or []:
        if not isinstance(gap, dict) or gap.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        if not bool(gap.get("blocking")):
            continue
        try:
            year = int(gap.get("year"))
        except (TypeError, ValueError):
            continue
        if year not in delivered:
            years.append(year)
    return sorted(set(years))


def _document_routes(documents: Dict[str, Any]) -> Dict[int, str]:
    routes: Dict[int, str] = {}
    for doc in documents.get("documents", []) or []:
        if not isinstance(doc, dict) or doc.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        if str(doc.get("verification_status") or "").upper() not in STRONG_VERIFICATION:
            continue
        try:
            year = int(doc.get("report_year"))
        except (TypeError, ValueError):
            continue
        url = str(doc.get("source_url") or "").strip()
        if url:
            routes[year] = url
    return routes


def _document_report_locators(documents: Dict[str, Any]) -> List[str]:
    """Return bounded HTTP provenance pages already present in report evidence.

    The primary G0 may locate an official report catalog and preserve it only as a
    document/gap ``source_locator`` while its broader corporate-page audit contains
    different pages.  A fresh positive-only recovery pass should not discard that
    provenance.  These pages are only seeds: downstream adapters still require local
    report semantics, same-host reconstruction and byte-verified PDF content.
    """
    out: List[str] = []
    rows = [*(documents.get("documents", []) or []), *(documents.get("gaps", []) or [])]
    for row in rows:
        if not isinstance(row, dict) or row.get("document_type") != "SUSTAINABILITY_REPORT":
            continue
        locator = str(row.get("source_locator") or "").strip()
        parsed = urlparse(locator)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        locator = locator.split("#", 1)[0]
        if locator not in out:
            out.append(locator)
    return out[:24]


def _seeded_generic_js_recovery(
    discovery: Dict[str, Any],
    documents: Dict[str, Any],
    audit: Dict[str, Any],
    stage: Dict[str, Any],
) -> Dict[str, Any]:
    """Run bounded first-party JS recovery with document provenance as extra seeds.

    ``g0_generic_js_report_recovery`` normally reads report index pages from the audit.
    The fresh pass additionally knows the post-discovery document evidence, which may
    contain a stronger official report-page locator.  Temporarily expose those locators
    to the adapter, then restore the original corporate-document audit verbatim so the
    provenance of the primary discovery stage is not rewritten.
    """
    stages = audit.setdefault("stages", {})
    corporate = stages.setdefault("corporate_documents", {})
    had_report_pages = "report_index_pages" in corporate
    original_pages = list(corporate.get("report_index_pages") or [])
    seeded = [p for p in _document_report_locators(documents) if p not in original_pages]
    stage["seeded_report_pages"] = seeded
    if seeded:
        corporate["report_index_pages"] = [*original_pages, *seeded]
    try:
        return g0_generic_js_report_recovery.enrich(discovery, documents, audit)
    finally:
        if had_report_pages:
            corporate["report_index_pages"] = original_pages
        else:
            corporate.pop("report_index_pages", None)


def _target_years_remaining(documents: Dict[str, Any], target_years: List[int]) -> List[int]:
    current = set(blocking_sustainability_years(documents))
    return sorted(year for year in target_years if year in current)


def run(out_dir: str | Path, budget_seconds: int = DEFAULT_RECOVERY_BUDGET_SECONDS) -> Dict[str, Any]:
    root = Path(out_dir)
    company_path = root / "company_discovery.json"
    documents_path = root / "document_evidence.json"
    audit_path = root / "Discovery_Audit.json"
    for path in (company_path, documents_path, audit_path):
        if not path.exists():
            raise FileNotFoundError(path)

    discovery = _read_json(company_path)
    documents = _read_json(documents_path)
    audit = _read_json(audit_path)
    before_years = blocking_sustainability_years(documents)
    stage = {
        "policy": "FRESH_PROCESS_POSITIVE_ONLY_DOCUMENT_RECOVERY",
        "budget_seconds": int(max(1, budget_seconds)),
        "blocking_years_before": before_years,
        "routes_before": _document_routes(documents),
    }
    audit.setdefault("stages", {})["fresh_process_document_recovery"] = stage

    if not before_years:
        stage.update({
            "status": "NOT_NEEDED",
            "blocking_years_after": [],
            "routes_after": stage["routes_before"],
        })
        _write_json(audit_path, audit)
        return stage

    # Importing zero_touch_runner installs the same bounded Http wrapper used by live
    # G0. Reset only its deadline in this new process; the primary process deadline is
    # untouched. The workflow supplies a substantially shorter second-pass budget.
    runtime._G0_NETWORK_DEADLINE = time.monotonic() + int(max(1, budget_seconds))

    # Start with the highest-confidence, already-located first-party report pages.  The
    # primary G0 can preserve a verified catalog only in document provenance, so the
    # fresh pass temporarily seeds those locators into the generic-JS adapter.
    documents = _seeded_generic_js_recovery(discovery, documents, audit, stage)
    remaining = _target_years_remaining(documents, before_years)
    stage["blocking_years_after_seeded_generic_js"] = remaining

    # Once the original blocking target years are positively recovered, do not spend
    # the independent budget on slower central-index or broad-navigation fallbacks.
    if remaining:
        documents = g0_js_form_report_recovery.enrich(discovery, documents, audit)
        documents = g0_data_attr_report_recovery.enrich(discovery, documents, audit)
        documents = g0_plain_href_report_recovery.enrich(discovery, documents, audit)
        documents = g0_kind_sustainability_recovery.enrich(discovery, documents, audit)
        documents = g0_scripted_report_enrichment.enrich(discovery, documents, audit)
        documents = g0_scripted_report_navigation.enrich(discovery, documents, audit)
        documents = g0_generic_js_report_recovery.enrich(discovery, documents, audit)
        stage["live_recovery_short_circuit"] = False
    else:
        stage["live_recovery_short_circuit"] = True
        stage["short_circuit_after"] = "SEEDED_GENERIC_JS_REPORT_RECOVERY"

    documents = g0_report_entity_policy.normalize(discovery, documents, audit)
    documents = runtime._merge_verified_document_routes(discovery, documents, audit)
    documents = g0_report_finalizer.finalize(discovery, documents, audit)
    documents = g0_report_catalog_policy.normalize_verified_catalog_gaps(discovery, documents, audit)
    documents = g0_first_publication_recovery.recover(discovery, documents, audit)
    documents = g0_entity_window_normalization.normalize(discovery, documents, audit)
    g0_report_enrichment.refresh_document_unresolved(discovery, documents, audit)

    after_years = blocking_sustainability_years(documents)
    stage.update({
        "status": "RECOVERED" if len(after_years) < len(before_years) else "NO_POSITIVE_RECOVERY",
        "blocking_years_after": after_years,
        "routes_after": _document_routes(documents),
        "recovered_years": sorted(set(before_years) - set(after_years)),
    })
    _write_json(documents_path, documents)
    _write_json(audit_path, audit)
    return stage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="generated-discovery")
    parser.add_argument("--budget-seconds", type=int, default=DEFAULT_RECOVERY_BUDGET_SECONDS)
    args = parser.parse_args()
    result = run(args.out_dir, args.budget_seconds)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
