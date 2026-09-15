import re


# This module is the shared pre-download identity boundary for all public-source collectors.
LEGAL_FORM_PATTERNS = [
    r"주식회사", r"유한회사", r"유한책임회사", r"합자회사", r"합명회사",
    r"\(주\)", r"㈜", r"\(유\)",
]

# Generic facility-role suffixes. They are used only after an exact current-entity
# prefix or a verified site name has already been established.
SITE_ROLE_SUFFIXES = [
    "제철소", "사업장", "사업소", "공장", "본사", "사무소", "연구소", "연구원",
    "센터", "캠퍼스", "단지", "기지", "터미널",
]
ADDRESS_ADMIN_SUFFIXES = ["특별자치시", "특별자치도", "광역시", "특별시", "시", "군", "구"]


def _without_legal_forms(value):
    text = str(value or "").casefold()
    for pattern in LEGAL_FORM_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def compact_name(value):
    """Normalize spelling/layout while preserving the entity/site lexical content."""
    text = _without_legal_forms(value)
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def compact_address(value):
    text = str(value or "").casefold()
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def _gate_sites(gate):
    out = []
    for site in (gate or {}).get("verified_sites", []) or []:
        if not isinstance(site, dict):
            continue
        name = str(site.get("site_name") or "").strip()
        address = str(site.get("address") or "").strip()
        if name or address:
            out.append({"site_name": name, "address": address})
    return out


def _verified_site_name_location_tokens(sites, entity_names):
    """Derive short aliases from verified site names, e.g. 포항제철소 -> 포항."""
    entity_set = {x for x in entity_names if x}
    out = set()
    for site in sites:
        raw = compact_name(site.get("site_name"))
        if not raw:
            continue
        stem = raw
        for suffix in sorted(SITE_ROLE_SUFFIXES, key=len, reverse=True):
            compact_suffix = compact_name(suffix)
            if compact_suffix and stem.endswith(compact_suffix):
                stem = stem[:-len(compact_suffix)]
                break
        if (
            stem
            and stem not in entity_set
            and len(stem) >= 2
            and re.fullmatch(r"[가-힣]{2,}", stem)
        ):
            out.add(stem)
    return out


def _verified_address_location_tokens(sites):
    """Extract Korean locality names only from already verified site addresses.

    This does not make address-only identity sufficient. It supplies a conservative
    vocabulary for source-native labels such as '효성티앤씨(울산)' when the official
    site catalog calls the facility '나이론폴리에스터 울산공장'.
    """
    out = set()
    suffix_pattern = "|".join(re.escape(x) for x in sorted(ADDRESS_ADMIN_SUFFIXES, key=len, reverse=True))
    pattern = re.compile(rf"([가-힣]{{2,}})({suffix_pattern})(?=\s|$)")
    for site in sites:
        address = str(site.get("address") or "")
        for match in pattern.finditer(address):
            token = compact_name(match.group(1))
            if len(token) >= 2:
                out.add(token)
    return out


def _verified_location_tokens(sites, entity_names):
    return sorted(
        _verified_site_name_location_tokens(sites, entity_names)
        | _verified_address_location_tokens(sites)
    )


def evaluate_candidate(name, address="", gate=None):
    """Decide whether a source candidate may trigger heavy/detail collection.

    Search result metadata may be broad. Detail pages, attachments and repeated
    source-ID probing are allowed only when the candidate can be tied to the verified
    current legal entity or a verified site. Address alone is deliberately not
    sufficient because co-located official units can be distinct identities.

    Public systems may shorten an official site label by dropping a business-unit
    prefix, for example official '나이론폴리에스터 울산공장' versus source-native
    '효성티앤씨(주) 울산공장'. A short label is admitted only when it starts with an
    exact verified current entity name and the remaining suffix is either a verified
    locality or verified locality + generic facility role. This never admits a group
    affiliate merely because its name starts with the requested-company stem.
    """
    gate = gate or {}
    if not gate or gate.get("enabled", True) is False:
        return {"allowed": True, "decision": "ALLOW_LEGACY_NO_GATE", "reason": "identity gate not configured"}

    candidate = compact_name(name)
    candidate_address = compact_address(address)
    entity_names = [compact_name(x) for x in gate.get("current_entity_names", []) or []]
    entity_names = [x for x in entity_names if x]
    sites = _gate_sites(gate)

    if not candidate:
        return {"allowed": False, "decision": "REJECT_UNVERIFIED_ENTITY", "reason": "source candidate has no usable entity/site name"}

    if candidate in entity_names:
        return {"allowed": True, "decision": "ALLOW_CURRENT_ENTITY_NAME", "reason": "source name exactly matches a verified current legal entity name"}

    address_match = False
    for site in sites:
        site_name = compact_name(site.get("site_name"))
        site_address = compact_address(site.get("address"))
        if site_address and candidate_address:
            address_match = address_match or (
                site_address == candidate_address
                or site_address in candidate_address
                or candidate_address in site_address
            )

        if site_name:
            if candidate == site_name or candidate.startswith(site_name):
                return {"allowed": True, "decision": "ALLOW_VERIFIED_SITE_NAME", "reason": f"source name matches verified site {site.get('site_name')}"}

            for entity in entity_names:
                if not entity:
                    continue
                joined = entity + site_name
                reverse = site_name + entity
                if candidate == joined or candidate == reverse or candidate.startswith(joined):
                    return {"allowed": True, "decision": "ALLOW_CURRENT_ENTITY_SITE", "reason": f"source name combines verified current entity and site {site.get('site_name')}"}
                if candidate.startswith(entity) and site_name in candidate[len(entity):]:
                    return {"allowed": True, "decision": "ALLOW_CURRENT_ENTITY_SITE", "reason": f"source name contains verified site {site.get('site_name')} after current entity stem"}

    location_tokens = _verified_location_tokens(sites, entity_names)
    role_tokens = [compact_name(x) for x in SITE_ROLE_SUFFIXES]
    for entity in entity_names:
        if not candidate.startswith(entity):
            continue
        suffix = candidate[len(entity):]
        if suffix and suffix in location_tokens:
            return {
                "allowed": True,
                "decision": "ALLOW_CURRENT_ENTITY_LOCATION_ALIAS",
                "reason": f"source name is current entity plus verified location token {suffix}",
            }
        for location in location_tokens:
            if any(suffix == location + role for role in role_tokens if role):
                return {
                    "allowed": True,
                    "decision": "ALLOW_CURRENT_ENTITY_LOCATION_ROLE_ALIAS",
                    "reason": f"source name is current entity plus verified location/role alias {suffix}",
                }

    if address_match:
        return {
            "allowed": False,
            "decision": "REJECT_ADDRESS_ONLY",
            "reason": "verified site address matched but name identity did not; address alone cannot prove site/legal identity",
        }

    return {
        "allowed": False,
        "decision": "REJECT_UNVERIFIED_ENTITY",
        "reason": "candidate is a search hit but is not the verified current entity or a verified site",
    }


def split_candidates(rows, *, name_getter, address_getter=None, gate=None):
    """Split broad search candidates into heavy-collection allow/reject sets."""
    allowed = []
    rejected = []
    for row in rows:
        name = name_getter(row)
        address = address_getter(row) if address_getter else ""
        decision = evaluate_candidate(name, address, gate)
        enriched = dict(row)
        enriched["detail_scope_decision"] = decision["decision"]
        enriched["detail_scope_reason"] = decision["reason"]
        if decision["allowed"]:
            allowed.append(enriched)
        else:
            rejected.append(enriched)
    return allowed, rejected
