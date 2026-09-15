import re


# This module is the shared pre-download identity boundary for all public-source collectors.
LEGAL_FORM_PATTERNS = [
    r"주식회사", r"유한회사", r"유한책임회사", r"합자회사", r"합명회사",
    r"\(주\)", r"㈜", r"\(유\)",
]

# These are generic facility-role suffixes, not company-specific aliases.  Removing
# one from a *verified* site name can yield a conservative source-native location
# token such as '포항' from '포항제철소' or '울산' from '울산공장'.
SITE_ROLE_SUFFIXES = [
    "제철소", "사업장", "사업소", "공장", "본사", "사무소", "연구소", "연구원",
    "센터", "캠퍼스", "단지", "기지", "터미널",
]


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
    # Administrative suffix spelling is not an identity fact; remove only layout noise.
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


def _verified_location_tokens(sites, entity_names):
    """Derive conservative short location aliases from verified site names only.

    The token is usable only for heavy-download admission when the source label is
    exactly '<verified current entity><token>'.  It never creates or merges a
    canonical site identity.  Address text alone never creates these tokens.
    """
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
        # Require at least two Korean syllables.  Ignore stems that collapse to the
        # company itself (for example '포스코센터' -> '포스코').
        if (
            stem
            and stem not in entity_set
            and len(stem) >= 2
            and re.fullmatch(r"[가-힣]{2,}", stem)
        ):
            out.add(stem)
    return sorted(out)


def evaluate_candidate(name, address="", gate=None):
    """Decide whether a source candidate may trigger heavy/detail collection.

    Search result metadata may be broad.  Detail pages, attachments and repeated
    source-ID probing are allowed only when the candidate can be tied to the verified
    current legal entity or a verified site name.  Address alone is deliberately not
    sufficient because co-located official units can be distinct identities.

    A source may abbreviate a verified site to a location label, e.g. '회사(포항)'
    instead of '회사 포항제철소'.  Such a label is admitted only when its suffix exactly
    equals a location token derived from a verified site name.  This is an admission
    rule for collection only; downstream identity resolution still decides which site
    the source record belongs to.

    Returns a dict with ``allowed``, ``decision`` and ``reason``.
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
            # A verified site name can appear by itself in source-native systems.
            if candidate == site_name or candidate.startswith(site_name):
                return {"allowed": True, "decision": "ALLOW_VERIFIED_SITE_NAME", "reason": f"source name matches verified site {site.get('site_name')}"}

            # Common public-source labels are '<legal entity> <site>' or the reverse.
            # Require the verified site token as well as the entity stem so a group
            # affiliate such as '포스코퓨처엠' cannot pass merely because it starts with
            # the short requested/company stem '포스코'.
            for entity in entity_names:
                if not entity:
                    continue
                joined = entity + site_name
                reverse = site_name + entity
                if candidate == joined or candidate == reverse or candidate.startswith(joined):
                    return {"allowed": True, "decision": "ALLOW_CURRENT_ENTITY_SITE", "reason": f"source name combines verified current entity and site {site.get('site_name')}"}
                if candidate.startswith(entity) and site_name in candidate[len(entity):]:
                    return {"allowed": True, "decision": "ALLOW_CURRENT_ENTITY_SITE", "reason": f"source name contains verified site {site.get('site_name')} after current entity stem"}

    # Source-native systems sometimes collapse a facility role to a parenthesized
    # location, e.g. '포스코(포항)'.  Permit only an exact entity+verified-location
    # composition.  Extra suffix text is intentionally rejected, so affiliate names
    # such as '포스코퓨처엠' cannot satisfy this rule.
    location_tokens = _verified_location_tokens(sites, entity_names)
    for entity in entity_names:
        if not candidate.startswith(entity):
            continue
        suffix = candidate[len(entity):]
        if suffix and suffix in location_tokens:
            return {
                "allowed": True,
                "decision": "ALLOW_CURRENT_ENTITY_LOCATION_ALIAS",
                "reason": f"source name is current entity plus verified site-derived location token {suffix}",
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
