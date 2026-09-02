"""Build runtime profile and collector request from Discovery evidence or profile fallback.

The zero-touch control plane writes ``requests/company_discovery.json``. When that
file is present it is the preferred runtime input and is compiled deterministically.
The tracked ``requests/company_profile.json`` remains a compatibility fallback for
existing proof runs and manual recovery; it is never overwritten by this module.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict

try:
    from .company_profile_builder import compile_discovery
    from .request_builder import build
except ImportError:  # script execution: python orchestrator/bootstrap_inputs.py
    from company_profile_builder import compile_discovery
    from request_builder import build


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _as_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 2100 else None


def _requested_history_window(discovery, profile):
    """Derive one explicit user-history window without guessing unavailable years.

    The window is built from requested periods, not from a source's deeper technical
    history.  It is used only as a completeness obligation for annual document series
    and post-collection audits; each source still follows its own availability plan.
    """
    policy = (discovery or {}).get("collection_policy") or {}
    explicit = policy.get("requested_history_window") or {}
    start = _as_year(explicit.get("start_year")); end = _as_year(explicit.get("end_year"))
    if start is not None and end is not None and start <= end:
        return {"start_year": start, "end_year": end, "basis": "EXPLICIT_REQUESTED_HISTORY_WINDOW"}

    years = []
    for raw in (policy.get("sources") or {}).values():
        if not isinstance(raw, dict):
            continue
        window = raw.get("requested_window") or {}
        for key in ("start_year", "end_year"):
            y = _as_year(window.get(key))
            if y is not None:
                years.append(y)
        for key in ("requested_survey_rounds", "daily_requested_years"):
            for value in raw.get(key, []) or []:
                y = _as_year(value)
                if y is not None:
                    years.append(y)
    if years:
        return {"start_year": min(years), "end_year": max(years), "basis": "DERIVED_FROM_REQUESTED_SOURCE_PERIODS"}

    # Compatibility fallback for old profiles that predate Discovery requested windows.
    for raw in (profile.get("source_plan") or {}).values():
        if not isinstance(raw, dict):
            continue
        for key in ("start_year", "end_year"):
            y = _as_year(raw.get(key))
            if y is not None:
                years.append(y)
        for key in ("years", "annual_years", "daily_years"):
            for value in raw.get(key, []) or []:
                y = _as_year(value)
                if y is not None:
                    years.append(y)
    return ({"start_year": min(years), "end_year": max(years), "basis": "DERIVED_FROM_SOURCE_PLAN"}
            if years else {})


def bootstrap_inputs(
    discovery_path: Path,
    profile_fallback_path: Path,
    profile_out: Path,
    request_out: Path,
    summary_out: Path,
) -> Dict[str, Any]:
    """Create runtime profile/request without mutating tracked source inputs."""
    if discovery_path.exists():
        discovery = _read_json(discovery_path)
        profile, summary = compile_discovery(discovery)
        # Collection remains legal-entity-wide, while the requested scope may narrow
        # human delivery and downstream analysis to a verified site set. This field
        # is control-plane metadata and therefore does not change collector queries.
        requested_scope = discovery.get("requested_scope") or {"mode": "COMPANY"}
        profile["requested_scope"] = requested_scope
        summary["requested_scope"] = requested_scope
        # Archive completeness needs the same history policy and both temporal
        # concepts that Discovery used. A rename bounds a name spelling, not the
        # existence of the legal entity itself.
        profile["minimum_history_years"] = int(
            (summary.get("collection_policies_selected") or {}).get("minimum_history_years") or 5
        )
        profile["current_legal_name_active_period"] = discovery.get("current_legal_name_active_period") or {}
        profile["legal_entity_active_period"] = discovery.get("legal_entity_active_period") or {}
        profile["requested_history_window"] = _requested_history_window(discovery, profile)
        summary["requested_history_window"] = profile["requested_history_window"]
        summary["legal_entity_active_period"] = profile["legal_entity_active_period"]
        mode = "DISCOVERY"
    elif profile_fallback_path.exists():
        profile = _read_json(profile_fallback_path)
        profile.setdefault("requested_scope", {"mode": "COMPANY"})
        profile.setdefault("minimum_history_years", 5)
        profile.setdefault("current_legal_name_active_period", {})
        profile.setdefault("legal_entity_active_period", {})
        profile.setdefault("requested_history_window", _requested_history_window({}, profile))
        mode = "PROFILE_FALLBACK"
        summary = {
            "summary_schema_version": "runtime-bootstrap-1.2",
            "bootstrap_mode": mode,
            "request_id": profile.get("request_id"),
            "company_resolved": None,
            "current_name": profile.get("company_display_name"),
            "requested_scope": profile.get("requested_scope"),
            "requested_history_window": profile.get("requested_history_window"),
            "legal_entity_active_period": profile.get("legal_entity_active_period"),
            "review_required_count": len(profile.get("discovery_review_required", [])),
            "note": "company_discovery.json absent; compatibility profile fallback used",
        }
    else:
        raise FileNotFoundError(
            f"No runtime company input found: {discovery_path} or {profile_fallback_path}"
        )

    request = build(profile)
    summary = dict(summary)
    summary["bootstrap_mode"] = mode
    summary["profile_output"] = str(profile_out)
    summary["request_output"] = str(request_out)

    _write_json(profile_out, profile)
    _write_json(request_out, request)
    _write_json(summary_out, summary)
    return {
        "bootstrap_mode": mode,
        "request_id": profile.get("request_id"),
        "company": profile.get("company_display_name"),
        "requested_scope": profile.get("requested_scope"),
        "requested_history_window": profile.get("requested_history_window"),
        "legal_entity_active_period": profile.get("legal_entity_active_period"),
        "profile": str(profile_out),
        "request": str(request_out),
        "summary": str(summary_out),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build runtime company inputs")
    parser.add_argument("--discovery", default="requests/company_discovery.json")
    parser.add_argument("--profile-fallback", default="requests/company_profile.json")
    parser.add_argument("--profile-out", default="requests/runtime/company_profile.generated.json")
    parser.add_argument("--request-out", default="requests/current.generated.json")
    parser.add_argument("--summary-out", default="requests/runtime/Company_Discovery_Summary.json")
    args = parser.parse_args()

    result = bootstrap_inputs(
        Path(args.discovery),
        Path(args.profile_fallback),
        Path(args.profile_out),
        Path(args.request_out),
        Path(args.summary_out),
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
