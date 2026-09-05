"""Probe official BAT sources to hydrate missing direct-PDF metadata.

This module is deliberately read-only with respect to bat_master_catalog.json. It
reuses the production collector's official-host, attachment parsing and PDF-byte
verification rules, then writes candidate direct URLs and SHA-256 digests for review.
A separate explicit promotion step is required before the master catalog changes.

Hydration is an audit/discovery task, not a production download. Its default network
profile therefore uses a short bounded request budget so one slow government endpoint
cannot monopolize the whole catalog scan. Production collection policy is unchanged.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from .bat_catalog_effective import CATALOG_PATH, OVERRIDES_PATH, build_effective_catalog
    from . import bat_collector as bc
except ImportError:
    from bat_catalog_effective import CATALOG_PATH, OVERRIDES_PATH, build_effective_catalog
    import bat_collector as bc


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


def _quick_session():
    import requests
    s=requests.Session()
    s.headers.update({'User-Agent':'Mozilla/5.0 (BATCatalogHydration/1.0; official-public-reference)'})
    return s


def fetch_pdf_from_spec_quick(spec: Dict[str, Any], timeout=(5,20), max_attachments=8):
    """Resolve one catalog spec with the production verifier under a short audit budget."""
    import requests
    session=_quick_session()
    expected=str(spec.get('official_pdf_sha256') or '').strip().lower()
    errors=[]

    direct=str(spec.get('official_pdf_url') or '').strip()
    if direct:
        try:
            rr=bc._get(session,direct,timeout=timeout)
            final,data,digest=bc._verified_pdf_response(rr,expected)
            return final,data,f'VERIFIED_OFFICIAL_DIRECT_PDF:sha256={digest}'
        except requests.RequestException as exc:
            errors.append(f'network:direct:{direct}:{type(exc).__name__}:{exc}')
        except Exception as exc:
            errors.append(f'direct:{direct}:{type(exc).__name__}:{exc}')

    pages=[]
    for key in ('official_document_page','official_source_locator'):
        value=str(spec.get(key) or '').strip()
        if value and value not in pages:
            pages.append(value)
    for value in spec.get('official_fallback_pages',[]) or []:
        value=str(value or '').strip()
        if value and value not in pages:
            pages.append(value)

    for page in pages:
        if not bc._official_host(page):
            errors.append(f'non_official_locator:{page}')
            continue
        try:
            variants=bc._page_variants(page)
        except Exception as exc:
            errors.append(f'page_variant:{page}:{type(exc).__name__}:{exc}')
            continue
        for variant in variants:
            try:
                r=bc._get(session,variant,timeout=timeout)
            except requests.RequestException as exc:
                errors.append(f'network:page:{variant}:{type(exc).__name__}:{exc}')
                continue
            except Exception as exc:
                errors.append(f'page:{variant}:{type(exc).__name__}:{exc}')
                continue
            if r.content.lstrip().startswith(b'%PDF-'):
                final,data,digest=bc._verified_pdf_response(r,expected)
                return final,data,f'DIRECT_PDF_PAGE:sha256={digest}'
            try:
                candidates=bc.attachment_candidates(r.url,r.text)[:max_attachments]
            except Exception as exc:
                errors.append(f'attachment_parse:{r.url}:{type(exc).__name__}:{exc}')
                continue
            for _,url,label in candidates:
                try:
                    rr=bc._get(session,url,timeout=timeout)
                except requests.RequestException as exc:
                    errors.append(f'network:attachment:{url}:{type(exc).__name__}:{exc}')
                    continue
                except Exception as exc:
                    errors.append(f'attachment:{url}:{type(exc).__name__}:{exc}')
                    continue
                if not rr.content.lstrip().startswith(b'%PDF-'):
                    errors.append(f'attachment_not_pdf:{rr.url}')
                    continue
                final,data,digest=bc._verified_pdf_response(rr,expected)
                return final,data,f'OFFICIAL_PAGE_ATTACHMENT:{label[:100]}:sha256={digest}'

    detail=' | '.join(errors[-12:]) if errors else 'no verified official direct PDF or document page'
    raise RuntimeError('Quick official BAT PDF hydration failed; '+detail)


def _classify_error(message: str) -> str:
    low=str(message or '').lower()
    if 'network:' in low or 'connecttimeout' in low or 'readtimeout' in low or 'connectionerror' in low:
        return 'SOURCE_UNREACHABLE'
    if 'not a pdf' in low or 'attachment_not_pdf' in low:
        return 'RESPONDED_NO_VERIFIED_PDF'
    return 'UNRESOLVED'


def probe_catalog(
    catalog_path: Path = CATALOG_PATH,
    overrides_path: Path = OVERRIDES_PATH,
    mode: str = "locator-pending",
    fetcher: Optional[Callable[[Dict[str, Any]], tuple]] = None,
) -> Dict[str, Any]:
    effective, advisories=build_effective_catalog(Path(catalog_path), Path(overrides_path))
    selected=select_entries(effective, mode)
    results=[]
    fetcher=fetcher or fetch_pdf_from_spec_quick
    for entry in selected:
        specs=bc._document_specs(entry)
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
                    "sha256": bc.sha256_bytes(data),
                    "bytes": len(data),
                    "resolution_method": str(method),
                    "error": "",
                })
            except Exception as exc:
                error=f"{type(exc).__name__}: {exc}"[:4000]
                results.append({
                    **base,
                    "status": _classify_error(error),
                    "verified_pdf_url": "",
                    "sha256": "",
                    "bytes": 0,
                    "resolution_method": "",
                    "error": error,
                })
    verified=[r for r in results if r["status"]=="VERIFIED_PDF"]
    unresolved=[r for r in results if r["status"]!="VERIFIED_PDF"]
    source_unreachable=[r for r in results if r["status"]=="SOURCE_UNREACHABLE"]
    return {
        "schema_version": "1.1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "network_profile": "QUICK_BOUNDED_AUDIT",
        "status": "COMPLETE" if not unresolved else ("PARTIAL" if verified else "NO_PDFS_RESOLVED"),
        "summary": {
            "selected_entry_count": len(selected),
            "document_probe_count": len(results),
            "verified_pdf_count": len(verified),
            "unresolved_count": len(unresolved),
            "source_unreachable_count": len(source_unreachable),
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
