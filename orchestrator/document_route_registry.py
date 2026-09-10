"""Persist verified document-route memory by DART legal-entity key.

The current request files intentionally represent one company at a time. This registry
prevents a company switch from erasing previously verified delivery routes. Entries are
keyed only by strongly verified DART selectKey values; cross-entity reuse fails closed.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.document_route_merge import dart_keys, merge_document_routes, same_verified_entity

SCHEMA_VERSION = "1.0"


def empty_registry() -> Dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "entities": {}}


def entity_key(company: Dict[str, Any]) -> str:
    keys = sorted(dart_keys(company))
    return keys[0] if len(keys) == 1 else ""


def merge_from_registry(
    registry: Dict[str, Any],
    fresh_company: Dict[str, Any],
    fresh_documents: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    key = entity_key(fresh_company)
    info = {"status": "NO_MATCH", "entity_key": key, "restored_documents": 0, "primary_routes_changed": 0}
    if not key:
        info["status"] = "NO_UNIQUE_VERIFIED_DART_KEY"
        return copy.deepcopy(fresh_documents), info
    entry = (registry.get("entities") or {}).get(key)
    if not isinstance(entry, dict):
        return copy.deepcopy(fresh_documents), info
    old_company = entry.get("company") or {}
    old_documents = entry.get("document_evidence") or {}
    if not same_verified_entity(old_company, fresh_company):
        info["status"] = "ENTITY_GUARD_REJECTED"
        return copy.deepcopy(fresh_documents), info

    before_docs = list(fresh_documents.get("documents", []) or [])
    before_urls = {
        (str(d.get("document_type") or ""), d.get("report_year")): str(d.get("source_url") or "")
        for d in before_docs if isinstance(d, dict)
    }
    # Registry data is supplied explicitly here. Do not recursively consult the on-disk
    # registry again while evaluating this in-memory snapshot.
    merged = merge_document_routes(
        old_company, old_documents, fresh_company, fresh_documents, _skip_registry=True
    )
    after_docs = list(merged.get("documents", []) or [])
    restored = sum(
        1 for d in after_docs
        if isinstance(d, dict) and d.get("route_merge_status") == "RESTORED_PREVIOUS_VERIFIED_DOCUMENT"
    )
    changed = 0
    for d in after_docs:
        if not isinstance(d, dict):
            continue
        k = (str(d.get("document_type") or ""), d.get("report_year"))
        if k in before_urls and before_urls[k] != str(d.get("source_url") or ""):
            changed += 1
    info.update({"status": "APPLIED", "restored_documents": restored, "primary_routes_changed": changed})
    return merged, info


def update_registry(
    registry: Dict[str, Any],
    company: Dict[str, Any],
    documents: Dict[str, Any],
) -> Dict[str, Any]:
    """Upsert one verified entity without weakening already remembered routes."""
    key = entity_key(company)
    if not key:
        raise ValueError("registry update requires exactly one strongly verified DART selectKey")
    out = copy.deepcopy(registry or empty_registry())
    out["schema_version"] = SCHEMA_VERSION
    entities = out.setdefault("entities", {})
    previous = entities.get(key)
    durable_docs = copy.deepcopy(documents)
    if isinstance(previous, dict):
        old_company = previous.get("company") or {}
        old_documents = previous.get("document_evidence") or {}
        if not same_verified_entity(old_company, company):
            raise ValueError(f"registry entity guard failed for DART key {key}")
        # Merge exactly once against the supplied persistent entry. This call must not
        # re-read the same registry from disk, otherwise route provenance can be folded
        # repeatedly during one promotion.
        durable_docs = merge_document_routes(
            old_company, old_documents, company, durable_docs, _skip_registry=True
        )
    entities[key] = {
        "current_legal_name": company.get("current_legal_name") or company.get("requested_company_name"),
        "company": copy.deepcopy(company),
        "document_evidence": durable_docs,
    }
    return out


def load_registry(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return empty_registry()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("entities", {}), dict):
        raise ValueError("invalid document route registry")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    update = sub.add_parser("update")
    update.add_argument("--registry", required=True)
    update.add_argument("--company", required=True)
    update.add_argument("--documents", required=True)
    args = parser.parse_args()

    if args.command == "update":
        registry_path = Path(args.registry)
        registry = load_registry(registry_path)
        company = json.loads(Path(args.company).read_text(encoding="utf-8"))
        documents = json.loads(Path(args.documents).read_text(encoding="utf-8"))
        result = update_registry(registry, company, documents)
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "UPDATED", "entity_key": entity_key(company)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
