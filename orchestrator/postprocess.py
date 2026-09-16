"""Compatibility layer for integration semantics that require stronger evidence-aware reconciliation.

The previous implementation is preserved verbatim in ``postprocess_core``.  This
module only narrows known false REVIEW_REQUIRED cases without weakening the base
identity rules: legacy lot-address bridging requires an exact verified site-name
match, shared lower administrative units, and an independently confirmed public
source already linked to the official site.

Coverage semantics deliberately keep two different questions separate:

* collection completeness: was every selected period successfully queried?
* analytical coverage: are there enough actual disclosed data years for a trend?

A successfully queried year with no disclosed row is never turned into a zero-valued
data point.  When the requested history was fully audited but confirmed no-data years
make the observed series shorter than the analytical minimum, the source is labelled
``SHORT_DATA_SERIES_CONFIRMED`` rather than the collection-gap state
``SHORT_COVERAGE``.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import postprocess_core as _core
from collection_completeness import apply_current_entity_period as _apply_current_entity_period
from collection_completeness import public_rows as _public_rows
from postprocess_core import *  # re-export the existing public contract
from request_builder import build as _build_request

_BASE_RESOLVE_IDENTITY = _core.resolve_identity
_BASE_COVERAGE_ROWS = _core.coverage_rows

NO_MATCH_SOURCE_STATES = {
    "NO_MATCH",
    "RESPONSE_OK_NO_TERM_MATCH",
    "NO_SITE_MATCH",
    "NO_DATA_FOUND",
}
STRONG_SITE_STATES = {"VERIFIED", "SOURCE_VERIFIED"}
STRONG_IDENTITY_STATES = {"CONFIRMED", "VERIFIED", "SOURCE_VERIFIED"}
COMPLETE_PERIOD_STATES = {"DATA_PRESENT", "NO_DATA_CONFIRMED"}


def _admin_units(value):
    """Return lower administrative units usable across road/lot address variants."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return set()
    # Deliberately ignore top-level province/metropolitan labels. A bridge needs at
    # least two shared lower units such as 평택시+포승읍 or 곡성군+입면.
    return set(re.findall(r"[0-9A-Za-z가-힣]+(?:시|군|구|읍|면)", text))


def _unique_official_site_by_name(profile, site_rows):
    official = defaultdict(list)
    for site in profile.get("site_candidates", []) or []:
        if not isinstance(site, dict):
            continue
        if str(site.get("verification_state") or "").upper() not in STRONG_SITE_STATES:
            continue
        if str(site.get("identity_status") or "").upper() not in STRONG_IDENTITY_STATES:
            continue
        key = _core.normalize_name(site.get("site_name_raw"), profile)
        if key:
            official[key].append(site)

    canonical = defaultdict(list)
    for row in site_rows:
        if row.get("identity_status") != "CONFIRMED":
            continue
        key = _core.normalize_name(row.get("canonical_site_name"), profile)
        if key:
            canonical[key].append(row)

    out = {}
    for key, candidates in official.items():
        rows = canonical.get(key, [])
        if len(candidates) == 1 and len(rows) == 1:
            out[key] = (candidates[0], rows[0])
    return out


def resolve_identity(candidates, profile):
    company_id, site_rows, id_rows, validations = _BASE_RESOLVE_IDENTITY(candidates, profile)

    official = _unique_official_site_by_name(profile, site_rows)
    # Independent corroboration is site-level, not label-level. Some public sources
    # expose only the legal company name while their exact official road address has
    # already anchored them to one verified canonical site. That is still independent
    # physical-site evidence. Co-located ambiguous official addresses remain protected
    # by the preserved core because they are not exact-address auto-confirmed.
    corroborated_by_site = defaultdict(set)
    for row in id_rows:
        if row.get("match_status") != "CONFIRMED" or not row.get("canonical_site_id"):
            continue
        corroborated_by_site[row.get("canonical_site_id")].add(row.get("source_key"))

    bridged_keys = set()
    bridged_candidate_ids = set()
    for row in id_rows:
        if not row.get("review_required"):
            continue
        key = _core.normalize_name(row.get("source_site_name_raw"), profile)
        if not key or key not in official:
            continue
        official_candidate, canonical_row = official[key]
        canonical_id = canonical_row.get("canonical_site_id")
        other_sources = corroborated_by_site.get(canonical_id, set()) - {row.get("source_key")}
        if not other_sources:
            continue
        shared = _admin_units(row.get("source_address_raw")) & _admin_units(official_candidate.get("address_raw"))
        if len(shared) < 2:
            continue

        old_id = row.get("canonical_site_id")
        row["canonical_site_id"] = canonical_id
        row["match_status"] = "CONFIRMED"
        row["match_basis"] = "OFFICIAL_SITE_NAME_LEGACY_ADDRESS_CROSS_SOURCE"
        row["review_required"] = False
        note = (
            "legacy lot/road address bridge: exact verified official site label; "
            f"shared_admin_units={'|'.join(sorted(shared))}; corroborating_sources={'|'.join(sorted(other_sources))}"
        )
        row["notes"] = ((row.get("notes") or "").strip() + "; " + note).strip("; ")
        bridged_keys.add(f"{row.get('source_key')}:{row.get('source_site_id')}")
        if old_id:
            bridged_candidate_ids.add(old_id)

    if bridged_keys:
        validations = [v for v in validations if v.get("object_key") not in bridged_keys]
        still_referenced = {r.get("canonical_site_id") for r in id_rows if r.get("canonical_site_id")}
        site_rows = [
            s for s in site_rows
            if not (
                s.get("identity_status") == "NEW_SITE_CANDIDATE"
                and s.get("canonical_site_id") in bridged_candidate_ids
                and s.get("canonical_site_id") not in still_referenced
            )
        ]

    return company_id, site_rows, id_rows, validations


def _as_year(value):
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def _meets_minimum_years(source, years):
    years = sorted({y for y in (_as_year(x) for x in years) if y is not None})
    if not years:
        return False
    if source == "CHEM_STATS":
        return len(years) >= 3 and max(years) - min(years) >= 4
    return len(years) >= 5 and all(years[i + 1] - years[i] == 1 for i in range(len(years) - 1))


def _audited_periods(root, profile):
    """Return evidence-backed per-year query states from the completeness auditor.

    The completeness auditor already knows each collector's retained response naming,
    per-year error logs and range-query semantics. Reusing it here avoids treating a
    merely requested year as a successfully queried year.
    """
    request = _build_request(profile)
    audited = _apply_current_entity_period(_public_rows(Path(root), request), profile)
    grouped = defaultdict(list)
    for item in audited:
        source = str(item.get("source") or "")
        if source not in getattr(_core, "SOURCES", []):
            continue
        if item.get("period_kind") != "YEAR" or str(item.get("expected") or "Y").upper() == "N":
            continue
        year = _as_year(item.get("period"))
        if year is None:
            continue
        grouped[source].append({**item, "_year": year})
    return grouped


def coverage_rows(root, company_id, id_rows, profile=None):
    rows = _BASE_COVERAGE_ROWS(root, company_id, id_rows)
    if not profile:
        return rows

    # Fail conservative. If the evidence-aware audit cannot be reconstructed here,
    # preserve the core SHORT_COVERAGE/NO_DATA states; archive-stage completeness will
    # still run later and can block delivery on missing periods.
    try:
        audited = _audited_periods(root, profile)
    except Exception:
        return rows

    for row in rows:
        source = str(row.get("source_key") or "")
        periods = audited.get(source, [])
        if not periods:
            continue

        expected_years = sorted({x["_year"] for x in periods})
        complete_years = sorted({x["_year"] for x in periods if x.get("completeness_state") in COMPLETE_PERIOD_STATES})
        data_years = sorted({x["_year"] for x in periods if x.get("completeness_state") == "DATA_PRESENT"})
        no_data_years = sorted({x["_year"] for x in periods if x.get("completeness_state") == "NO_DATA_CONFIRMED"})
        all_expected_complete = bool(expected_years) and set(complete_years) == set(expected_years)
        query_meets_minimum = _meets_minimum_years(source, complete_years)

        audit_detail = (
            f"query_complete={len(complete_years)}/{len(expected_years)}"
            f"; audited_years={'|'.join(map(str, expected_years)) or '-'}"
            f"; no_data_confirmed={'|'.join(map(str, no_data_years)) or '-'}"
        )
        row["rounds_or_detail"] = (
            str(row.get("rounds_or_detail") or "") + " | " + audit_detail
        ).strip(" |")

        if row.get("coverage_status") == "NO_DATA":
            if all_expected_complete and no_data_years and not data_years:
                row["coverage_status"] = "NO_DATA_CONFIRMED"
                row["meets_minimum"] = False
                row["comparability_status"] = "NOT_APPLICABLE_NO_DATA"
                row["collected_start"] = min(complete_years)
                row["collected_end"] = max(complete_years)
                row["next_action"] = (
                    "preserve verified no-data state; do not infer zero values or fabricate a trend series"
                )
            continue

        if row.get("coverage_status") == "SHORT_COVERAGE":
            # The actual series is still short, so meets_minimum remains False. The
            # important distinction is that no additional collection inside the audited
            # window can create the missing observations: those years were successfully
            # queried and explicitly yielded no disclosed data.
            if all_expected_complete and query_meets_minimum and no_data_years:
                row["coverage_status"] = "SHORT_DATA_SERIES_CONFIRMED"
                row["meets_minimum"] = False
                row["comparability_status"] = "SHORT_SERIES_CONFIRMED_NO_DATA"
                row["next_action"] = (
                    "limit trend claims to observed data years; do not impute confirmed no-data years as zero or treat them as a collection gap"
                )

    return rows


# Patch the preserved core's global identity lookup so callers of its unchanged
# helpers receive the corrected behavior. ``run_integration`` below passes the full
# profile into the enhanced coverage reconciliation explicitly.
_core.resolve_identity = resolve_identity
_core.coverage_rows = coverage_rows


def run_integration(root, profile_path, out):
    root = Path(root)
    out = Path(out)
    profile = _core.read_json(profile_path, {}) or {}
    candidates = _core.extract_candidates(root, profile)
    company_id, sites, ids, validations = resolve_identity(candidates, profile)
    cov = coverage_rows(root, company_id, ids, profile)

    _core.write_csv(out / "Site_Master.csv", sites, [
        "company_id", "canonical_site_id", "canonical_site_name", "site_type", "country", "region",
        "canonical_address_key", "identity_status", "first_seen_year", "last_seen_year", "active_status", "notes",
    ])
    _core.write_csv(out / "Source_Identity.csv", ids, [
        "company_id", "canonical_site_id", "source_key", "source_site_id", "source_site_name_raw",
        "source_address_raw", "valid_from", "valid_to", "match_status", "match_basis", "review_required",
        "raw_id_text_required", "notes",
    ])
    _core.write_csv(out / "Coverage_Status.csv", cov, [
        "company_id", "source_key", "coverage_scope", "available_start", "available_end", "collected_start",
        "collected_end", "rounds_or_detail", "meets_minimum", "event_baseline_status", "comparability_status",
        "coverage_status", "next_action",
    ])
    _core.write_csv(out / "Validation_Queue.csv", validations, [
        "validation_id", "company_id", "object_type", "object_key", "issue_type", "severity", "detected_by",
        "evidence", "recommended_action", "status", "resolved_by", "resolved_at", "notes",
    ])
    _core.merge_review_json(out / "REVIEW_REQUIRED.json", validations)

    summary = {
        "company_id": company_id,
        "identity_candidates": len(candidates),
        "canonical_confirmed": sum(x["identity_status"] == "CONFIRMED" for x in sites),
        "new_site_candidates": sum(x["identity_status"] == "NEW_SITE_CANDIDATE" for x in sites),
        "source_identity_confirmed": sum(x["match_status"] == "CONFIRMED" for x in ids),
        "identity_review_required": sum(bool(x["review_required"]) for x in ids),
        "coverage_short": sum(x["coverage_status"] == "SHORT_COVERAGE" for x in cov),
        "coverage_data_short_confirmed": sum(x["coverage_status"] == "SHORT_DATA_SERIES_CONFIRMED" for x in cov),
    }
    (out / "Integration_Summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
