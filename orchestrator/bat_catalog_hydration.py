"""Probe official BAT sources to hydrate missing direct-PDF metadata.

This module is deliberately read-only with respect to bat_master_catalog.json. It
reuses the production collector's official-host and PDF-byte verification path, then
writes candidate direct URLs and SHA-256 digests for review. A separate explicit
promotion step is required before the master catalog changes.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

try:
    from .bat_catalog_effective import CATALOG_PATH, OVERRIDES_PATH, build_effective_catalog
    from .bat_collector import _document_specs, fetch_pdf_from_spec, sha256_bytes
except ImportError:
    from bat_catalog_effective import CATALOG_PATH, OVERRIDES_PATH, build_effective_catalog
    from bat_collector import _document_specs, fetch_pdf_from_spec, sha256_bytes


def select_entries(catalog: Dict[str, Any], mode: str = "locator-pending") -> List[Dict[str, Any]]:
    rows=[]
    for entry in catalog.get("entries", []) or []:
        if entry.get("preferred") is not True:
            continue
        if str(entry.get("publication_status") or "").upper() != "PUBLISHED":
            continue
        policy=str(entry.get("collection_policy") or "").upper()
        sha=str(entry.get("official_pdf_sha256") or "").strip()
        if mode == "locator-pending":
            if policy != "WAIT_FOR_LATEST_LOCATOR":
                continue
        elif mode == "unverified-published":
            if sha:
                continue
        elif mode == "all-published":
            pass
        else:
            raise ValueError(f"Unknown hydration mode: {mode}")
        rows.append(entry)
    return rows


def probe_catalog(
    catalog_path: Path = CATALOG_PATH,
    overrides_path: Path = OVERRIDES_PATH,
    mode: str = "locator-pending",
    fetcher: Callable[[Dict[str, Any]], tuple] = fetch_pdf_from_spec,
) -> Dict[str, Any]:
    effective, advisories=build_effective_catalog(Path(catalog_path), Path(overrides_path))
    selected=select_entries(effective, mode)
    results=[]
    for entry in selected:
        specs=_document_specs(entry)
        for spec in specs:
            base={
                "catalog_id": str(entry.get("catalog_id") or ""),
                "catalog_family": str(entry.get("catalog_family") or ""),
                "title": str(spec.get("title") or entry.get("title") or ""),
                "revision_generation": str(entry.get("revision_generation") or ""),
                "publication_year": entry.get("publication_year"),
                "document_part": str(spec.get("document_part") or "1"),
                "volume_no": str(spec.get("volume_no") or spec.get("document_part") or "1"),
                "collection_policy": str(entry.get("collection_policy") or ""),
                "configured_pdf_url": str(spec.get("official_pdf_url") or ""),
                "configured_document_page": str(spec.get("official_document_page") or ""),
                "configured_source_locator": str(spec.get("official_source_locator") or ""),
            }
            try:
                final_url, data, method=fetcher(spec)
                results.append({
                    **base,
                    "status": "VERIFIED_PDF",
                    "verified_pdf_url": str(final_url),
                    "sha256": sha256_bytes(data),
                    "bytes": len(data),
                    "resolution_method": str(method),
                    "error": "",
                })
            except Exception as exc:
                results.append({
                    **base,
                    "status": "UNRESOLVED",
                    "verified_pdf_url": "",
                    "sha256": "",
                    "bytes": 0,
                    "resolution_method": "",
                    "error": f"{type(exc).__name__}: {exc}"[:4000],
                })
    verified=[r for r in results if r["status"]=="VERIFIED_PDF"]
    unresolved=[r for r in results if r["status"]!="VERIFIED_PDF"]
    return {
        "schema_version": "1.0",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "status": "COMPLETE" if not unresolved else ("PARTIAL" if verified else "NO_PDFS_RESOLVED"),
        "summary": {
            "selected_entry_count": len(selected),
            "document_probe_count": len(results),
            "verified_pdf_count": len(verified),
            "unresolved_count": len(unresolved),
        },
        "results": results,
        "effective_catalog_advisories": advisories,
        "promotion_policy": "Read-only probe. Promote a URL/SHA pair only after reviewing this artifact and preserving revision authority.",
    }


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--catalog", default=str(CATALOG_PATH))
    ap.add_argument("--overrides", default=str(OVERRIDES_PATH))
    ap.add_argument("--mode", choices=("locator-pending","unverified-published","all-published"), default="locator-pending")
    ap.add_argument("--out", default="BAT_Catalog_Hydration.json")
    args=ap.parse_args()
    payload=probe_catalog(Path(args.catalog), Path(args.overrides), args.mode)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"status":payload["status"], **payload["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
