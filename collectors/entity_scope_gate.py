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
# Role-only aliases are much less specific than site-name aliases. Keep this list
# deliberately narrow. "회사명 + 본사" is a common public-source form and is
# admitted only when exactly one verified site carries that role.
UNIQUE_ROLE_ONLY_SUFFIXES = {"본사"}
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


def _site_name_segments(value):
    """Return explicit source-meaningful pieces of a verified composite site label.

    Official catalogs sometimes publish a single label such as
    "창원 3사업장/R&D 캠퍼스". Public reporting systems may use only the first
    explicit segment. Splitting is limited to visible catalog separators and does
    not invent fuzzy substrings.
    """
    raw = str(value or "").strip()
    if not raw:
        return []
    pieces = [raw]
    pieces.extend(x.strip() for x in re.split(r"[/|,;·ㆍ]+", raw) if x.strip())
    out = []
    seen = set()
    for piece in pieces:
        token = compact_name(piece)
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _strip_one_site_role(token):
    token = compact_name(token)
    for suffix in sorted(SITE_ROLE_SUFFIXES, key=len, reverse=True):
        role = compact_name(suffix)
        if role and token.endswith(role) and len(token) > len(role):
            return token[:-len(role)], role
    return token, ""


def _verified_site_alias_tokens(sites, entity_names):
    """Build exact aliases from verified site labels only.

    Examples:
      율촌CNT공장 -> 율촌cnt
      창원 3사업장/R&D 캠퍼스 -> 창원3사업장
    The aliases remain exact tokens. They are accepted only after an exact current
    legal-entity prefix, so this does not create free-form fuzzy company matching.
    """
    entity_set = {x for x in entity_names if x}
    out = set()
    for site in sites:
        for token in _site_name_segments(site.get("site_name")):
            if token and token not in entity_set:
                out.add(token)
            stem, _ = _strip_one_site_role(token)
            if stem and stem not in entity_set and len(stem) >= 2:
                out.add(stem)
    return out


def _verified_unique_role_tokens(sites):
    """Return conservative role-only aliases that identify exactly one verified site."""
    allowed_roles = {compact_name(x) for x in UNIQUE_ROLE_ONLY_SUFFIXES}
    counts = {}
    for site in sites:
        roles_for_site = set()
        for token in _site_name_segments(site.get("site_name")):
            _, role = _strip_one_site_role(token)
            if role in allowed_roles:
                roles_for_site.add(role)
        for role in roles_for_site:
            counts[role] = counts.get(role, 0) + 1
    return {role for role, count in counts.items() if count == 1}


def _verified_site_name_location_tokens(sites, entity_names):
    """Derive short locality aliases from verified site names, e.g. 포항제철소 -> 포항."""
    entity_set = {x for x in entity_names if x}
    out = set()
    for site in sites:
        for raw in _site_name_segments(site.get("site_name")):
            stem, _ = _strip_one_site_role(raw)
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

    Public systems may shorten verified site labels in three conservative ways:
    (1) use a catalog segment of a composite label,
    (2) omit one generic facility-role suffix, or
    (3) use a verified locality plus an optional generic facility role.
    All such aliases require an exact verified current-entity prefix. A bare generic
    role is allowed only for the narrow role-only allowlist and only when that role
    identifies exactly one verified site.
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

    site_alias_tokens = _verified_site_alias_tokens(sites, entity_names)
    unique_role_tokens = _verified_unique_role_tokens(sites)
    location_tokens = _verified_location_tokens(sites, entity_names)
    role_tokens = [compact_name(x) for x in SITE_ROLE_SUFFIXES]

    for entity in entity_names:
        if not candidate.startswith(entity):
            continue
        suffix = candidate[len(entity):]
        if not suffix:
            continue

        # Preserve the pre-existing decision semantics for locality aliases. A site
        # like 포항제철소 also yields the site stem 포항, but locality is the older and
        # narrower classification and should win when both apply.
        if suffix in location_tokens:
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

        if suffix in site_alias_tokens:
            return {
                "allowed": True,
                "decision": "ALLOW_CURRENT_ENTITY_VERIFIED_SITE_ALIAS",
                "reason": f"source name is current entity plus exact alias derived from a verified site label: {suffix}",
            }

        if suffix in unique_role_tokens:
            return {
                "allowed": True,
                "decision": "ALLOW_CURRENT_ENTITY_UNIQUE_ROLE_ALIAS",
                "reason": f"source name is current entity plus role {suffix}, which identifies one verified site",
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
