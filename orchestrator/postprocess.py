"""Compatibility layer for integration semantics that require stronger evidence-aware reconciliation.

The previous implementation is preserved verbatim in ``postprocess_core``.  This
module only narrows known false REVIEW_REQUIRED cases without weakening the base
identity rules: legacy lot-address bridging requires an exact verified site-name
match, shared lower administrative units, and an independently confirmed public
source already linked to the official site.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import postprocess_core as _core
from postprocess_core import *  # re-export the existing public contract

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


def coverage_rows(root, company_id, id_rows):
    rows = _BASE_COVERAGE_ROWS(root, company_id, id_rows)
    root = Path(root)
    for row in rows:
        source = row.get("source_key")
        status = _core.read_json(root / source / "status.json", {}) or {}
        state = str(status.get("status") or "").upper()
        if row.get("coverage_status") != "NO_DATA" or state not in NO_MATCH_SOURCE_STATES:
            continue

        queried_years = []
        for key in ("annual_years", "years", "requested_years"):
            values = status.get(key)
            if isinstance(values, list):
                for value in values:
                    try:
                        queried_years.append(int(str(value)[:4]))
                    except Exception:
                        pass
        queried_years = sorted(set(queried_years))
        if queried_years:
            row["collected_start"] = min(queried_years)
            row["collected_end"] = max(queried_years)
        row["coverage_status"] = "NO_DATA_CONFIRMED"
        row["meets_minimum"] = False
        row["comparability_status"] = "NOT_APPLICABLE_NO_DATA"
        row["rounds_or_detail"] = (
            str(row.get("rounds_or_detail") or "") + f" | collector_state={state}"
        ).strip(" |").strip()
        row["next_action"] = "preserve verified no-match state; do not infer a trend series"
    return rows


# Patch the preserved core's global lookup points so callers of its unchanged
# run_integration() receive the corrected behavior.
_core.resolve_identity = resolve_identity
_core.coverage_rows = coverage_rows


def run_integration(root, profile_path, out):
    return _core.run_integration(root, profile_path, out)
