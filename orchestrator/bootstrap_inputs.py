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
        mode = "DISCOVERY"
    elif profile_fallback_path.exists():
        profile = _read_json(profile_fallback_path)
        mode = "PROFILE_FALLBACK"
        summary = {
            "summary_schema_version": "runtime-bootstrap-1.0",
            "bootstrap_mode": mode,
            "request_id": profile.get("request_id"),
            "company_resolved": None,
            "current_name": profile.get("company_display_name"),
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
