"""Static integrity audit for the BAT master/effective catalogs.

The master catalog preserves discovery history. Runtime matching uses the effective
catalog after verified status overrides are applied. This audit distinguishes hard
structural errors from expected operational warnings such as a newly published
revision whose direct PDF bytes have not yet been verified.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

try:
    from .bat_catalog_effective import (
        CATALOG_PATH,
        OVERRIDES_PATH,
        build_effective_catalog,
    )
except ImportError:
    from bat_catalog_effective import CATALOG_PATH, OVERRIDES_PATH, build_effective_catalog

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _read(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _issue(code: str, severity: str, message: str, **context: Any) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, **context}


def _revision_key(entry: Dict[str, Any]) -> Tuple[str, str]:
    return (str(entry.get("revision_generation") or ""), str(entry.get("publication_year") or ""))


def _has_official_locator(entry: Dict[str, Any]) -> bool:
    return any(
        str(entry.get(key) or "").strip()
        for key in ("official_source_locator", "official_document_page", "official_pdf_url")
    )


def audit_catalog(
    catalog_path: Path = CATALOG_PATH,
    overrides_path: Path = OVERRIDES_PATH,
) -> Dict[str, Any]:
    catalog_path = Path(catalog_path)
    overrides_path = Path(overrides_path)
    master = _read(catalog_path)
    master_entries = list(master.get("entries", []) or [])
    effective, advisories = build_effective_catalog(catalog_path, overrides_path)
    effective_entries = list(effective.get("entries", []) or [])

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    ids = [str(e.get("catalog_id") or "") for e in master_entries]
    duplicate_ids = sorted(k for k, v in Counter(ids).items() if k and v > 1)
    for catalog_id in duplicate_ids:
        errors.append(_issue(
            "DUPLICATE_CATALOG_ID", "ERROR", "catalog_id must be unique",
            catalog_id=catalog_id,
        ))

    required = ("catalog_id", "catalog_family", "title", "authority", "publication_status", "collection_policy")
    for idx, entry in enumerate(master_entries):
        catalog_id = str(entry.get("catalog_id") or "")
        for key in required:
            if not str(entry.get(key) or "").strip():
                errors.append(_issue(
                    "MISSING_REQUIRED_FIELD", "ERROR", f"Master catalog entry lacks {key}",
                    catalog_id=catalog_id, field=key, index=idx,
                ))
        sha = str(entry.get("official_pdf_sha256") or "").strip()
        url = str(entry.get("official_pdf_url") or "").strip()
        if sha and not SHA256_RE.fullmatch(sha):
            errors.append(_issue(
                "INVALID_PDF_SHA256", "ERROR", "official_pdf_sha256 must be 64 hex characters",
                catalog_id=catalog_id, sha256=sha,
            ))
        if sha and not url:
            errors.append(_issue(
                "SHA_WITHOUT_PDF_URL", "ERROR", "Byte hash exists without the PDF URL it verifies",
                catalog_id=catalog_id,
            ))
        if url and not sha:
            warnings.append(_issue(
                "PDF_URL_NOT_BYTE_VERIFIED", "WARNING", "Direct PDF URL exists but has no recorded SHA-256",
                catalog_id=catalog_id, official_pdf_url=url,
            ))

    for advisory in advisories:
        if advisory.get("status") == "OVERRIDE_TARGET_NOT_PRESENT":
            errors.append(_issue(
                "OVERRIDE_TARGET_NOT_PRESENT", "ERROR", "Status override targets a missing master entry",
                catalog_id=advisory.get("catalog_id", ""),
                reason_code=advisory.get("reason_code", ""),
            ))

    by_family: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in effective_entries:
        family = str(entry.get("catalog_family") or entry.get("catalog_id") or "")
        by_family[family].append(entry)

    family_rows: List[Dict[str, Any]] = []
    for family, entries in sorted(by_family.items()):
        preferred = [e for e in entries if e.get("preferred") is True]
        preferred_revisions = sorted({_revision_key(e) for e in preferred})
        if len(preferred_revisions) > 1:
            errors.append(_issue(
                "MULTIPLE_PREFERRED_REVISIONS", "ERROR",
                "One BAT family resolves to more than one preferred revision generation/year",
                catalog_family=family,
                preferred_revisions=[list(x) for x in preferred_revisions],
                catalog_ids=[e.get("catalog_id", "") for e in preferred],
            ))
        if not preferred:
            warnings.append(_issue(
                "FAMILY_WITHOUT_PREFERRED_REVISION", "WARNING",
                "Effective catalog family has no preferred runtime revision",
                catalog_family=family,
            ))

        for entry in entries:
            catalog_id = str(entry.get("catalog_id") or "")
            preferred_flag = entry.get("preferred") is True
            status = str(entry.get("publication_status") or "")
            policy = str(entry.get("collection_policy") or "")

            if preferred_flag and policy == "AUDIT_ONLY_SUPERSEDED":
                errors.append(_issue(
                    "PREFERRED_MARKED_SUPERSEDED", "ERROR",
                    "Preferred runtime entry cannot use superseded-only collection policy",
                    catalog_id=catalog_id, catalog_family=family,
                ))
            if policy == "COLLECT_WHEN_MATCHED" and status != "PUBLISHED":
                errors.append(_issue(
                    "COLLECTABLE_ENTRY_NOT_PUBLISHED", "ERROR",
                    "COLLECT_WHEN_MATCHED is allowed only for verified published references",
                    catalog_id=catalog_id, publication_status=status,
                ))
            if preferred_flag and status == "PUBLISHED" and not _has_official_locator(entry):
                errors.append(_issue(
                    "PUBLISHED_PREFERRED_WITHOUT_OFFICIAL_LOCATOR", "ERROR",
                    "Published preferred runtime entry has no official source locator",
                    catalog_id=catalog_id, catalog_family=family,
                ))
            if preferred_flag and status == "PUBLISHED" and policy == "WAIT_FOR_LATEST_LOCATOR":
                warnings.append(_issue(
                    "LATEST_LOCATOR_PENDING", "WARNING",
                    "Publication is verified but the latest original/download locator remains pending",
                    catalog_id=catalog_id, catalog_family=family,
                ))
            if preferred_flag and status == "PUBLISHED" and not str(entry.get("official_pdf_sha256") or "").strip():
                warnings.append(_issue(
                    "PREFERRED_PUBLISHED_PDF_NOT_BYTE_VERIFIED", "WARNING",
                    "Preferred published reference does not yet have a byte-verified direct PDF cache",
                    catalog_id=catalog_id, catalog_family=family,
                ))
            if preferred_flag and status != "PUBLISHED":
                warnings.append(_issue(
                    "PREFERRED_NONFINAL_REFERENCE", "WARNING",
                    "Preferred entry is not a final published reference; collection must remain fail-closed",
                    catalog_id=catalog_id, catalog_family=family,
                    publication_status=status, collection_policy=policy,
                ))

        family_rows.append({
            "catalog_family": family,
            "entry_count": len(entries),
            "preferred_catalog_ids": [str(e.get("catalog_id") or "") for e in preferred],
            "preferred_revisions": [list(x) for x in preferred_revisions],
            "published_entry_count": sum(str(e.get("publication_status") or "") == "PUBLISHED" for e in entries),
            "byte_verified_entry_count": sum(bool(str(e.get("official_pdf_sha256") or "").strip()) for e in entries),
        })

    preferred_effective = [e for e in effective_entries if e.get("preferred") is True]
    published_preferred = [e for e in preferred_effective if str(e.get("publication_status") or "") == "PUBLISHED"]
    byte_verified_preferred = [e for e in published_preferred if str(e.get("official_pdf_sha256") or "").strip()]

    payload = {
        "schema_version": "1.0",
        "catalog_as_of": master.get("catalog_as_of"),
        "effective_catalog_as_of": effective.get("effective_catalog_as_of"),
        "status": "PASS" if not errors else "FAIL",
        "summary": {
            "master_entry_count": len(master_entries),
            "effective_entry_count": len(effective_entries),
            "family_count": len(by_family),
            "effective_preferred_entry_count": len(preferred_effective),
            "effective_published_preferred_count": len(published_preferred),
            "effective_byte_verified_preferred_count": len(byte_verified_preferred),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "override_advisory_count": len(advisories),
        },
        "errors": errors,
        "warnings": warnings,
        "families": family_rows,
        "override_advisories": advisories,
        "principles": [
            "Master catalog preserves historical discovery evidence.",
            "Runtime invariants are evaluated after verified status overrides are applied.",
            "Missing byte verification is visible as a warning unless a hash/URL pair is internally inconsistent.",
            "Unpublished or unverified preferred references must remain fail-closed for collection.",
        ],
    }
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=str(CATALOG_PATH))
    ap.add_argument("--overrides", default=str(OVERRIDES_PATH))
    ap.add_argument("--out", default="BAT_Catalog_Audit.json")
    args = ap.parse_args()
    payload = audit_catalog(Path(args.catalog), Path(args.overrides))
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], **payload["summary"]}, ensure_ascii=False, indent=2))
    if payload["errors"]:
        print(json.dumps({"errors": payload["errors"]}, ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
