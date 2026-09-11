"""Resolve domestic operational sites from explicit first-party site catalogs.

Environmental collection must not collapse a multi-plant company to one arbitrary
"primary" plant when the official company page explicitly enumerates several domestic
facilities. This adapter promotes the listed set only when a first-party page clearly
acts as a site catalog and contains at least two distinct operational-site records.

Structured production tables are the strongest contract because they preserve the
company's own facility name/address pairing, including distinct units at the same road
address. Structured DOM cards are next, with flattened text as a conservative fallback.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bs4 import BeautifulSoup

from orchestrator import g0_live_adapters as live
from orchestrator import zero_touch_discovery as base


# A domestic-site catalog may sit under an explicitly domestic navigation label or a
# broader global-network page that enumerates both domestic and overseas facilities.
# The page label only establishes catalog context; Korean road-address parsing and
# operational-facility extraction still decide which rows are promoted as domestic sites.
CATALOG_WORDS = (
    "국내사업장", "국내 사업장", "국내 사업장소개", "domestic sites",
    "domestic locations", "domestic plants", "korea locations",
    "글로벌네트워크", "글로벌 네트워크", "global network", "global locations",
)
PRODUCTION_TABLE_WORDS = (
    "생산공장", "생산 공장", "생산사업장", "생산 사업장",
    "production plant", "production plants", "production facility",
    "manufacturing plant", "manufacturing site", "factory", "factories",
)
OPERATIONAL_SUFFIXES = (
    "제철소", "공장", "연구소", "기술원", "사업장", "센터", "영업소", "사무소", "본사", "캠퍼스",
)
OPERATIONAL_SUFFIX_RE = "|".join(map(re.escape, OPERATIONAL_SUFFIXES))
SITE_NAME_RE = re.compile(
    rf"([A-Za-z0-9가-힣㈜()·&./\- ]{{2,70}}?(?:{OPERATIONAL_SUFFIX_RE}))\s*$",
    re.I,
)
NEAREST_SITE_TOKEN_RE = re.compile(
    rf"([A-Za-z0-9가-힣㈜()·&./\-]{{1,45}}\s*(?:{OPERATIONAL_SUFFIX_RE}))",
    re.I,
)
NON_SITE_UI_TERMS = (
    "제보센터", "고객센터", "고객지원센터", "문의센터", "채용센터", "홍보센터",
    "고객문의", "제보하기", "통합검색", "개인정보", "privacy center",
    "customer center", "contact center", "recruit center", "whistleblowing center",
)
NAME_CLASS_HINTS = ("name", "title", "site-name", "site_name", "branch-name", "plant-name", "factory-name")
ADDRESS_CLASS_HINTS = ("addr", "address", "site-addr", "site_addr", "site-address", "location-address")
REGION_PREFIX_CANONICAL = (
    ("서울특별시", "서울"), ("서울시", "서울"),
    ("부산광역시", "부산"), ("부산시", "부산"),
    ("대구광역시", "대구"), ("대구시", "대구"),
    ("인천광역시", "인천"), ("인천시", "인천"),
    ("광주광역시", "광주"), ("광주시", "광주"),
    ("대전광역시", "대전"), ("대전시", "대전"),
    ("울산광역시", "울산"), ("울산시", "울산"),
    ("세종특별자치시", "세종"), ("세종시", "세종"),
    ("경기도", "경기"), ("강원특별자치도", "강원"), ("강원도", "강원"),
    ("충청북도", "충북"), ("충청남도", "충남"),
    ("전북특별자치도", "전북"), ("전라북도", "전북"), ("전라남도", "전남"),
    ("경상북도", "경북"), ("경상남도", "경남"),
    ("제주특별자치도", "제주"), ("제주도", "제주"),
)
METRO_SHORT_REGION = "서울시|부산시|대구시|인천시|광주시|대전시|울산시|세종시"
CATALOG_REGION = f"{live.COMMON_REGION}|{METRO_SHORT_REGION}"
CATALOG_ROAD_ADDRESS_RE = re.compile(
    rf"((?:(?:{CATALOG_REGION})\s+|[가-힣]{{2,24}}(?:특별자치도|특별자치시|광역시|특별시|도)\s+)"
    r"[가-힣0-9]{1,24}(?:시|군|구)\s+"
    r"(?:[가-힣0-9]{1,24}(?:읍|면|동|리|구)\s+)?"
    r"[가-힣0-9·.\-]{1,36}(?:대로|로|길)\s*\d+(?:[-~]\d+)?(?:번길\s*\d+(?:[-~]\d+)?)?)"
)
GENERIC_CELL_WORDS = {
    "category", "region", "name", "location", "location & contact", "map",
    "구분", "지역", "명칭", "이름", "소재지", "주소", "연락처", "대한민국", "korea",
    "생산공장", "생산 공장", "생산사업장", "생산 사업장",
}


def _compact(value: str) -> str:
    """Return a stable Korean road-address key across common region spellings."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for long_name, short_name in REGION_PREFIX_CANONICAL:
        if text == long_name or text.startswith(long_name + " "):
            text = short_name + text[len(long_name):]
            break
    return re.sub(r"[^0-9가-힣]+", "", text)


def _site_key(name: str, address: str) -> str:
    """Keep distinct structured production units even at one road address."""
    return _compact(address) + "|" + base.normalize_name(name)


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


def _non_site_ui_name(value: str) -> bool:
    compact = re.sub(r"\s+", "", str(value or "")).casefold()
    return any(re.sub(r"\s+", "", term).casefold() in compact for term in NON_SITE_UI_TERMS)


# Flattened-text fallbacks are intentionally weaker than structured cards/tables.  A
# nearby sentence fragment can happen to end in an operational suffix (for example a
# prose phrase such as "...한 공장"), so suffix matching alone is not enough to promote
# it as a facility name.  These guards are lexical/grammatical and company-agnostic.
GENERIC_BARE_SITE_LABELS = {
    "공장", "사업장", "센터", "영업소", "사무소", "캠퍼스",
    "주요공장", "주요사업장", "국내공장", "국내사업장",
}
DESCRIPTIVE_SITE_PREFIX_RE = re.compile(
    r"(?:^|\s)[가-힣]+(?:하는|한|있는|없는|되는|된|중인|하던|했던)\s*$"
)
ACCOUNTING_SITE_CONTEXT_RE = re.compile(
    r"(?:단위|금액|매출|매출액|자산|백만원|천만원|억원|만원|천원|원)\)?\s*$",
    re.I,
)


def _prose_like_site_name(value: str, company: str) -> bool:
    """Reject sentence/table fragments that only *look* like facility labels.

    This is deliberately not a company allow-list.  It only rejects shapes that cannot
    safely be treated as a proper facility label in a flattened-text fallback.  A label
    equal to the company name plus a separated suffix remains valid even when the legal
    name itself happens to end with an adnominal-looking Korean syllable.
    """
    name = re.sub(r"\s+", " ", str(value or "")).strip(" -:：|")
    compact = re.sub(r"\s+", "", name)
    if compact in GENERIC_BARE_SITE_LABELS:
        return True

    # A proper label may contain balanced corporate parentheses such as ``(주)`` but a
    # dangling closing bracket is a strong sign that the token leaked from a table unit
    # or preceding prose, e.g. ``백만원) 사업장``.
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        if name.count(closing) > name.count(opening):
            return True

    suffix = next((s for s in OPERATIONAL_SUFFIXES if name.endswith(s)), "")
    if not suffix:
        return False
    prefix = name[:-len(suffix)].strip()
    if not prefix:
        return compact in GENERIC_BARE_SITE_LABELS

    company_compact = re.sub(r"[^0-9A-Za-z가-힣]+", "", str(company or "")).casefold()
    prefix_compact = re.sub(r"[^0-9A-Za-z가-힣]+", "", prefix).casefold()
    if company_compact and prefix_compact == company_compact:
        return False

    if ACCOUNTING_SITE_CONTEXT_RE.search(prefix):
        return True

    # When the suffix is written as a separate word, an immediately preceding Korean
    # adnominal form is prose ("보유한 공장", "운영하는 사업장"), not a site label.
    if re.search(r"\s" + re.escape(suffix) + r"$", name) and DESCRIPTIVE_SITE_PREFIX_RE.search(prefix):
        return True
    return False


def _operational_name(value: str, company: str) -> str:
    """Accept explicit first-party facility labels without requiring the legal name.

    Global-network pages often label cards as e.g. ``울산공장`` or ``기술원`` rather
    than repeating the corporate legal name.  The page-level first-party catalog
    contract supplies company ownership; requiring the company token in every card
    causes a false fallback to neighbouring labels.  Service/navigation labels are
    rejected explicitly so ``제보센터`` or ``고객센터`` cannot become sites.
    """
    name = re.sub(r"\s+", " ", str(value or "")).strip(" -:：|")
    if not name or not any(name.endswith(suffix) for suffix in OPERATIONAL_SUFFIXES):
        return ""
    if _non_site_ui_name(name) or _prose_like_site_name(name, company):
        return ""
    return name


def _validated_address(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    match = CATALOG_ROAD_ADDRESS_RE.search(text)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" |:-:：")


def _table_name(cells: Sequence[str], address_index: int, address_cell: str) -> str:
    """Choose the facility-name cell immediately before the address/contact cell."""
    candidates = list(cells[:address_index])
    address_match = CATALOG_ROAD_ADDRESS_RE.search(address_cell)
    if address_match:
        prefix = _clean_cell(address_cell[:address_match.start()])
        if prefix:
            candidates.append(prefix)
    for raw in reversed(candidates):
        value = _clean_cell(raw)
        folded = value.casefold()
        if not value or folded in GENERIC_CELL_WORDS:
            continue
        if any(word.casefold() == folded for word in PRODUCTION_TABLE_WORDS):
            continue
        if CATALOG_ROAD_ADDRESS_RE.search(value):
            continue
        if len(value) > 90 or _non_site_ui_name(value):
            continue
        return value
    return ""


def _structured_table_sites(company: str, page: base.Page) -> Dict[str, Dict[str, Any]]:
    """Extract name/address pairs from explicit production/manufacturing tables."""
    html = str(page.html or "")
    if not html.strip():
        return {}
    soup = BeautifulSoup(html, "html.parser")
    found: Dict[str, Dict[str, Any]] = {}
    for table in soup.find_all("table"):
        marker = " ".join(table.stripped_strings).casefold()
        if not any(word.casefold() in marker for word in PRODUCTION_TABLE_WORDS):
            continue
        for row in table.find_all("tr"):
            tags = row.find_all(["th", "td"], recursive=False)
            if not tags:
                tags = row.find_all(["th", "td"])
            cells = [_clean_cell(" ".join(tag.stripped_strings)) for tag in tags]
            if not cells:
                continue
            address = ""
            address_index = -1
            address_cell = ""
            for index, cell in enumerate(cells):
                address = _validated_address(cell)
                if address:
                    address_index = index
                    address_cell = cell
                    break
            if not address:
                continue
            name = _table_name(cells, address_index, address_cell)
            if not name:
                continue
            key = _site_key(name, address)
            if not key:
                continue
            found.setdefault(key, {
                "name": name,
                "address": address,
                "source_locator": page.url,
                "extraction_contract": "STRUCTURED_PRODUCTION_TABLE_NAME_ADDRESS_PAIR",
            })
    return found


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
        # Legacy DOM-card discovery intentionally deduplicates repeated representations
        # of one physical location by address. Same-address distinct units are preserved
        # only by the stronger structured production-table contract above.
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


def _semantic_heading_sites(company: str, page: base.Page) -> Dict[str, Dict[str, Any]]:
    """Pair semantic facility headings with the next bounded Korean road address.

    Some official location pages use clean HTML headings (for example a headquarters,
    R&D campus, or service center) but do not expose ``name``/``address`` CSS classes.
    Flattening such a page destroys card boundaries and can reuse the previous facility
    name for the next address. On an already-confirmed first-party catalog page, a
    semantic heading followed by exactly one road address before the next facility
    heading is a stronger contract than proximity in flattened text.
    """
    html = str(page.html or "")
    if not html.strip():
        return {}
    soup = BeautifulSoup(html, "html.parser")
    found: Dict[str, Dict[str, Any]] = {}
    heading_names = {"h1", "h2", "h3", "h4", "h5", "h6", "dt", "strong"}

    headings: List[Tuple[Any, str]] = []
    for tag in soup.find_all(True):
        role = str((getattr(tag, "attrs", {}) or {}).get("role") or "").casefold()
        if getattr(tag, "name", "") not in heading_names and role != "heading" and not _class_matches(tag, NAME_CLASS_HINTS):
            continue
        raw = _clean_cell(" ".join(tag.stripped_strings))
        name = _operational_name(raw, company)
        if name:
            headings.append((tag, name))

    for heading, name in headings:
        address = ""
        scanned = 0
        for tag in heading.find_all_next(True):
            scanned += 1
            if scanned > 40:
                break
            if tag is not heading:
                role = str((getattr(tag, "attrs", {}) or {}).get("role") or "").casefold()
                if getattr(tag, "name", "") in heading_names or role == "heading" or _class_matches(tag, NAME_CLASS_HINTS):
                    next_name = _operational_name(_clean_cell(" ".join(tag.stripped_strings)), company)
                    if next_name:
                        break
            value = _clean_cell(" ".join(tag.stripped_strings))
            matches = list(CATALOG_ROAD_ADDRESS_RE.finditer(value))
            if len(matches) != 1:
                continue
            candidate = _validated_address(value)
            if candidate:
                address = candidate
                break
        if not address:
            continue
        key = _compact(address)
        if not key:
            continue
        found.setdefault(key, {
            "name": name,
            "address": address,
            "source_locator": page.url,
            "extraction_contract": "SEMANTIC_HEADING_ADDRESS_PAIR",
        })
    return found


def _bounded_site_name(name: str, company: str) -> str:
    name = re.sub(r"\s+", " ", str(name or "")).strip(" -:：|")
    company_token = re.sub(r"\s+", "", company)
    compact_name = re.sub(r"\s+", "", name)
    idx = compact_name.rfind(company_token)
    if idx > 0:
        suffix = next((s for s in OPERATIONAL_SUFFIXES if compact_name.endswith(s)), "사업장")
        return f"{company} {suffix}"
    return name


def _site_name(text: str, address_start: int, company: str) -> str:
    raw_before = str(text[max(0, address_start - 180):address_start])
    compact_candidates = NEAREST_SITE_TOKEN_RE.findall(raw_before)
    for candidate in reversed(compact_candidates):
        name = _operational_name(_bounded_site_name(candidate, company), company)
        if name:
            return name

    before = re.sub(r"\s+", " ", raw_before).strip()
    match = SITE_NAME_RE.search(before)
    if match:
        name = re.sub(r"\s+", " ", match.group(1)).strip(" -:：|")
        pieces = re.split(r"[|•·\n\r\t]", name)
        name = pieces[-1].strip() if pieces else name
        name = _operational_name(_bounded_site_name(name, company), company)
        if name:
            return name
    # Fail closed. A road address with no explicit nearby facility label can be a
    # footer/contact address and must not be promoted as a generic company site.
    return ""


def _flattened_text_sites(company: str, page: base.Page) -> Dict[str, Dict[str, Any]]:
    text = str(page.text or "")
    found: Dict[str, Dict[str, Any]] = {}
    for match in CATALOG_ROAD_ADDRESS_RE.finditer(text):
        address = re.sub(r"\s+", " ", match.group(1)).strip()
        context = text[max(0, match.start() - 220): min(len(text), match.end() + 80)]
        if not any(term in context for term in OPERATIONAL_SUFFIXES):
            continue
        name = _site_name(text, match.start(), company)
        if not name:
            continue
        key = _compact(address)
        if not key:
            continue
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

        found = _structured_table_sites(company, page)
        if len(found) < 2:
            found = _structured_dom_sites(company, page)
        if len(found) < 2:
            found = _semantic_heading_sites(company, page)
        if len(found) < 2:
            found = _flattened_text_sites(company, page)
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
