"""Resolve all domestic operational sites from an explicit first-party site catalog.

Environmental collection must not collapse a multi-plant company to one arbitrary
"primary" plant when the official company page explicitly enumerates several domestic
facilities. This adapter promotes the complete listed set only when one first-party page
clearly identifies itself as a domestic-site catalog and contains at least two distinct
operational-site addresses.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from orchestrator import g0_live_adapters as live
from orchestrator import zero_touch_discovery as base


CATALOG_WORDS = (
    "국내사업장", "국내 사업장", "국내 사업장소개", "domestic sites",
    "domestic locations", "domestic plants", "korea locations",
)
SITE_NAME_RE = re.compile(
    r"([A-Za-z0-9가-힣㈜()·&.\- ]{2,70}?(?:공장|연구소|사업장|센터|사무소|본사))\s*$",
    re.I,
)
OPERATIONAL_SUFFIXES = ("공장", "연구소", "사업장", "센터", "사무소", "본사")


def _compact(value: str) -> str:
    return re.sub(r"[^0-9가-힣]+", "", str(value or ""))


def _site_name(text: str, address_start: int, company: str) -> str:
    before = re.sub(r"\s+", " ", text[max(0, address_start - 180):address_start]).strip()
    match = SITE_NAME_RE.search(before)
    if match:
        name = re.sub(r"\s+", " ", match.group(1)).strip(" -:：|")
        # Keep the nearest facility phrase, stripping unrelated preceding prose.
        pieces = re.split(r"[|•·\n\r\t]", name)
        name = pieces[-1].strip() if pieces else name
        # If a long sentence slipped into the regex, keep from the last company token.
        company_token = re.sub(r"\s+", "", company)
        compact_name = re.sub(r"\s+", "", name)
        idx = compact_name.rfind(company_token)
        if idx > 0:
            # Fall back to a suffix-only label when whitespace reconstruction is unsafe.
            suffix = next((s for s in OPERATIONAL_SUFFIXES if compact_name.endswith(s)), "사업장")
            return f"{company} {suffix}"
        return name
    return f"{company} 사업장"


def discover(
    company: str,
    pages: Sequence[base.Page],
) -> Optional[Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]]:
    for page in pages:
        text = str(page.text or "")
        folded = text.casefold()
        if not any(word.casefold() in folded for word in CATALOG_WORDS):
            continue

        found: Dict[str, Dict[str, Any]] = {}
        for match in live.FLEX_ROAD_ADDRESS_RE.finditer(text):
            address = re.sub(r"\s+", " ", match.group(1)).strip()
            context = text[max(0, match.start() - 220): min(len(text), match.end() + 80)]
            if not any(term in context for term in OPERATIONAL_SUFFIXES):
                continue
            key = _compact(address)
            if not key:
                continue
            name = _site_name(text, match.start(), company)
            found.setdefault(key, {
                "name": name,
                "address": address,
                "source_locator": page.url,
            })

        # A dedicated catalog with only one address is not enough evidence that the
        # complete multi-site set was enumerated. Leave the normal resolver in control.
        if len(found) < 2:
            continue

        sites: List[Dict[str, Any]] = []
        for item in found.values():
            cid = base._slug(company + " " + item["name"] + " " + item["address"])
            sites.append({
                "candidate_id": cid,
                "site_name_raw": item["name"],
                "address_raw": item["address"],
                "business_unit_raw": "official domestic-site catalog",
                "source_locator": item["source_locator"],
                "identity_status": "CONFIRMED",
                "verification_state": "VERIFIED",
                "discovery_evidence": {
                    "evidence_type": "EXPLICIT_DOMESTIC_SITE_CATALOG",
                    "catalog_page": item["source_locator"],
                },
            })
        scope = {
            "mode": "SITE_SET",
            "label": f"{company} 국내 사업장",
            "candidate_ids": [s["candidate_id"] for s in sites],
            "raw_collection_policy": "PRESERVE_COMPANY_WIDE",
            "archive_policy": "FILTER_TO_REQUESTED_SCOPE",
            "analysis_policy": "FILTER_TO_REQUESTED_SCOPE",
        }
        return sites, scope, []
    return None
