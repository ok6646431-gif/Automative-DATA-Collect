"""Build an effective BAT catalog from verified publication-state corrections.

The master catalog intentionally preserves discovery history. A later audit can find
that an entry was promoted too early (for example, a revision was announced for future
distribution but final publication cannot be verified). This module applies small,
auditable status corrections without deleting the historical catalog evidence.

Core rule: a newer revision deactivates the last verified published matching revision
only after final publication is itself verified from an official government/NIER page
or downloadable original. Planning, consultation and scheduled-distribution language
are not publication proof.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Tuple

CATALOG_PATH = Path(__file__).with_name("bat_master_catalog.json")
OVERRIDES_PATH = Path(__file__).with_name("bat_catalog_status_overrides.json")


def _read(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_effective_catalog(
    catalog_path: Path = CATALOG_PATH,
    overrides_path: Path = OVERRIDES_PATH,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    catalog = deepcopy(_read(Path(catalog_path)))
    overrides_file = Path(overrides_path)
    if not overrides_file.exists():
        return catalog, []

    correction = _read(overrides_file)
    entries = list(catalog.get("entries", []) or [])
    by_id = {str(e.get("catalog_id") or ""): e for e in entries}
    excluded = set()
    advisories: List[Dict[str, Any]] = []

    for override in correction.get("overrides", []) or []:
        catalog_id = str(override.get("catalog_id") or "")
        entry = by_id.get(catalog_id)
        if not entry:
            advisories.append({
                "catalog_id": catalog_id,
                "status": "OVERRIDE_TARGET_NOT_PRESENT",
                "reason_code": override.get("reason_code", ""),
                "evidence": override.get("evidence", []),
            })
            continue

        original = {
            key: entry.get(key)
            for key in (
                "preferred", "publication_status", "supersession_status",
                "collection_policy", "official_source_locator", "official_document_page",
                "official_pdf_url",
            )
        }
        effective_fields = dict(override.get("effective_fields") or {})
        entry.update(effective_fields)
        notes_append = str(override.get("notes_append") or "").strip()
        if notes_append:
            old_notes = str(entry.get("notes") or "").strip()
            entry["notes"] = (old_notes + "; " + notes_append).strip("; ")

        include = override.get("include_in_effective_catalog", True) is not False
        if not include:
            excluded.add(catalog_id)

        advisories.append({
            "catalog_id": catalog_id,
            "status": "APPLIED",
            "reason_code": override.get("reason_code", ""),
            "include_in_effective_catalog": include,
            "original_fields": original,
            "effective_fields": effective_fields,
            "evidence": override.get("evidence", []),
            "notes": notes_append,
        })

    catalog["entries"] = [e for e in entries if str(e.get("catalog_id") or "") not in excluded]
    catalog["effective_catalog_as_of"] = correction.get("verified_as_of")
    catalog["effective_catalog_policy"] = correction.get("policy")
    catalog["status_override_source"] = str(overrides_file)
    return catalog, advisories


def materialize_effective_catalog(
    package: Path,
    catalog_path: Path = CATALOG_PATH,
    overrides_path: Path = OVERRIDES_PATH,
) -> Tuple[Path, List[Dict[str, Any]]]:
    """Write the corrected runtime catalog and its audit trail into the package.

    Status overrides apply only to the repository's production master catalog. Custom
    catalogs supplied by unit tests or callers remain untouched.
    """
    package = Path(package)
    requested = Path(catalog_path)
    try:
        is_master = requested.resolve() == CATALOG_PATH.resolve()
    except FileNotFoundError:
        is_master = False
    if not is_master:
        return requested, []

    effective, advisories = build_effective_catalog(requested, overrides_path)
    effective_path = package / "BAT_Effective_Catalog.json"
    advisory_path = package / "BAT_Catalog_Advisories.json"
    effective_path.write_text(json.dumps(effective, ensure_ascii=False, indent=2), encoding="utf-8")
    advisory_path.write_text(json.dumps({
        "schema_version": "1.0",
        "verified_as_of": effective.get("effective_catalog_as_of"),
        "policy": effective.get("effective_catalog_policy"),
        "advisories": advisories,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return effective_path, advisories
