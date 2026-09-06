"""Fail-closed user-delivery scope for documents attached to in-scope source records.

A public-source record can belong to the requested site while an attached document
explicitly identifies another legal entity. Raw collection preserves that evidence,
but user-facing delivery must not silently inherit the attachment merely because its
parent record is in scope.

Only entities that the canonical Requested_Scope resolver has already rejected are
eligible for this guard. The filename must explicitly contain a sufficiently specific
normalized excluded-entity name; broad company-keyword similarity is never enough.
"""

from __future__ import annotations

import re
from typing import Any


ENTITY_EXCLUSION_REASONS = {
    "VERIFIED_RELATED_ENTITY_EXCLUSION",
    "SOURCE_ENTITY_NAME_EXTENDS_CURRENT_COMPANY",
    "SOURCE_ENTITY_NAME_NOT_CURRENT_COMPANY",
}


def normalize_entity_name(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\(\s*주\s*\)|㈜|주식회사|유한회사|\(\s*유\s*\)", "", text, flags=re.I)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).lower()


def excluded_entity_candidates(requested_scope: dict, source_key: str = "ENVINFO") -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in requested_scope.get("excluded_source_ids", []) or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("source_key") or "").upper() != str(source_key or "").upper():
            continue
        reason = str(row.get("reason") or "").upper()
        if reason not in ENTITY_EXCLUSION_REASONS:
            continue
        raw_name = str(row.get("source_site_name_raw") or "").strip()
        token = normalize_entity_name(raw_name)
        # Short tokens such as generic three-character company roots are too broad
        # for a filename-level legal-entity exclusion decision.
        if len(token) < 4:
            continue
        item = {
            "source_key": str(row.get("source_key") or ""),
            "source_site_id": str(row.get("source_site_id") or ""),
            "source_site_name_raw": raw_name,
            "reason": reason,
            "normalized_entity": token,
        }
        key = (item["source_site_id"], item["source_site_name_raw"], item["reason"])
        if key not in seen:
            candidates.append(item)
            seen.add(key)
    candidates.sort(key=lambda x: len(x["normalized_entity"]), reverse=True)
    return candidates


def match_envinfo_attachment(attachment: dict, requested_scope: dict) -> dict[str, str] | None:
    """Return an explicit exclusion decision for a cross-entity ENVINFO attachment.

    The parent ENVINFO compId is expected to have already passed requested-source-ID
    filtering. This function asks the separate question of whether the *document
    itself* explicitly names a verified excluded entity.
    """
    filename = str(attachment.get("original_filename") or "").strip()
    if not filename:
        return None
    normalized_filename = normalize_entity_name(filename)
    if not normalized_filename:
        return None
    for excluded in excluded_entity_candidates(requested_scope, "ENVINFO"):
        token = excluded["normalized_entity"]
        if token and token in normalized_filename:
            return {
                "decision": "CROSS_ENTITY_ATTACHMENT_EXCLUDED",
                "matched_surface": "ORIGINAL_FILENAME",
                "matched_excluded_entity": excluded["source_site_name_raw"],
                "matched_excluded_source_id": excluded["source_site_id"],
                "matched_exclusion_reason": excluded["reason"],
                "normalized_match": token,
            }
    return None
