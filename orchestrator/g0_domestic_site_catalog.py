"""Resolve all domestic operational sites from an explicit first-party site catalog.

Environmental collection must not collapse a multi-plant company to one arbitrary
"primary" plant when the official company page explicitly enumerates several domestic
facilities. This adapter promotes the complete listed set only when one first-party page
clearly identifies itself as a domestic-site catalog and contains at least two distinct
operational-site addresses.

Structured DOM pairs are preferred over flattened-text inference. Corporate site pages
commonly publish repeated facility cards such as ``name`` + ``addr`` or equivalent
class/data attributes. When those pairs are available, use the exact first-party label
and address from the same card. Flattened text remains only as a conservative fallback.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bs4 import BeautifulSoup

from orchestrator import g0_live_adapters as live
from orchestrator import zero_touch_discovery as base


CATALOG_WORDS = (
    "국내사업장", "국내 사업장", "국내 사업장소개", "domestic sites",
    "domestic locations", "domestic plants", "korea locations",
)
SITE_NAME_RE = re.compile(
    r"([A-Za-z0-9가-힣㈜()·&.\- ]{2,70}?(?:제철소|공장|연구소|사업장|센터|사무소|본사))\s*$",
    re.I,
)
# Operational facility vocabulary is industry-agnostic. `제철소` is a facility type,
# not a company exception, and must behave like 공장/사업장 during site extraction.
OPERATIONAL_SUFFIXES = ("제철소", "공장", "연구소", "사업장", "센터", "사무소", "본사")
NAME_CLASS_HINTS = ("name", "title", "site-name", "site_name", "branch-name", "plant-name", "factory-name")
ADDRESS_CLASS_HINTS = ("addr", "address", "site-addr", "site_addr", "site-address", "location-address")


def _compact(value: str) -> str:
    return re.sub(r"[^0-9가-힣]+", "", str(value or ""))


def _class_tokens(tag: Any) -> List[str]:
    attrs = getattr(tag, "attrs", {}) or {}
    raw = attrs.get("class") or []
    if isinstance(raw, str):
        raw = raw.split()
    return [str(x).casefold() for x in raw]


def _class_matches(tag: Any, hints: Sequence[str]) -> bool:
    tokens = _class_tokens(tag)
    for token in tokens:
        if token in hints:
            return True
        if any(hint in token for hint in hints if len(hint) >= 4):
            return True
    return False


def _operational_name(value: str, company: str) -> str:
    name = re.sub(r"\s+", " ", str(value or "")).strip(" -:：|")
    if not name or not any(name.endswith(suffix) for suffix in OPERATIONAL_SUFFIXES):
        return ""
    company_norm = base.normalize_name(company)
    name_norm = base.normalize_name(name)
    # An explicit domestic-site catalog can use a brand rather than the legal suffix,
    # but it should still identify the requested company when a company name is present.
    if company_norm and name_norm and company_norm not in name_norm and name_norm not in company_norm:
        return ""
    return name


def _validated_address(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    match = live.FLEX_ROAD_ADDRESS_RE.search(text)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _structured_dom_sites(company: str, page: base.Page) -> Dict[str, Dict[str, Any]]:
    """Extract exact facility-name/address pairs from repeated first-party DOM cards."""
    html = str(page.html or "")
    if not html.strip():
        return {}
    soup = BeautifulSoup(html, "html.parser")
    found: Dict[str, Dict[str, Any]] = {}

    address_tags = [tag for tag in soup.find_all(True) if _class_matches(tag, ADDRESS_CLASS_HINTS)]
    for address_tag in address_tags:
        address = _validated_address(" ".join(address_tag.stripped_strings))
        if not address:
            continue

        # Stay inside the nearest repeated card/list item. This prevents a page-level
        # heading from being paired with a different facility's address.
        container = address_tag
        chosen_container = None
        for _ in range(6):
            container = getattr(container, "parent", None)
            if container is None:
                break
            if getattr(container, "name", "") in {"li", "article"}:
                chosen_container = container
                break
            classes = _class_tokens(container)
            if any(any(hint in token for hint in ("branch", "site", "plant", "factory", "location", "card", "item")) for token in classes):
                chosen_container = container
                break
        if chosen_container is None:
            chosen_container = getattr(address_tag, "parent", None)
        if chosen_container is None:
            continue

        name_candidates: List[str] = []
        for tag in chosen_container.find_all(True):
            if _class_matches(tag, NAME_CLASS_HINTS):
                value = " ".join(tag.stripped_strings).strip()
                if value:
                    name_candidates.append(value)
            data_title = str((getattr(tag, "attrs", {}) or {}).get("data-title") or "").strip()
            if data_title:
                name_candidates.append(data_title)

        name = ""
        for candidate in name_candidates:
            name = _operational_name(candidate, company)
            if name:
                break
        if not name:
            continue

        key = _compact(address)
        if not key:
            continue
        found.setdefault(key, {
            "name": name,
            "address": address,
            "source_locator": page.url,
            "extraction_contract": "STRUCTURED_DOM_NAME_ADDRESS_PAIR",
        })
    return found


def _site_name(text: str, address_start: int, company: str) -> str:
    before = re.sub(r"\s+", " ", text[max(0, address_start - 180):address_start]).strip()
    match = SITE_NAME_RE.search(before)
    if match:
        name = re.sub(r"\s+", " ", match.group(1)).strip(" -:：|")
        pieces = re.split(r"[|•·\n\r\t]", name)
        name = pieces[-1].strip() if pieces else name
        company_token = re.sub(r"\s+", "", company)
        compact_name = re.sub(r"\s+", "", name)
        idx = compact_name.rfind(company_token)
        if idx > 0:
            suffix = next((s for s in OPERATIONAL_SUFFIXES if compact_name.endswith(s)), "사업장")
            return f"{company} {suffix}"
        return name
    return f"{company} 사업장"


def _flattened_text_sites(company: str, page: base.Page) -> Dict[str, Dict[str, Any]]:
    text = str(page.text or "")
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
            "extraction_contract": "FLATTENED_TEXT_FALLBACK",
        })
    return found


def discover(
    company: str,
    pages: Sequence[base.Page],
) -> Optional[Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]]:
    for page in pages:
        text = str(page.text or "")
        folded = text.casefold()
        if not any(word.casefold() in folded for word in CATALOG_WORDS):
            continue

        found = _structured_dom_sites(company, page)
        if len(found) < 2:
            found = _flattened_text_sites(company, page)

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
                    "extraction_contract": item.get("extraction_contract"),
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
