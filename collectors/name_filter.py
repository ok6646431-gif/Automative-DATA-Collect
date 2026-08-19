import re


def normalize_entity_name(value):
    """Normalize only for verified related-entity exclusion matching.

    This is not an identity-resolution function. It removes spacing/punctuation and
    case differences so source-native spellings such as '(주)'/'㈜' do not defeat an
    explicit exclusion. The exclusion itself must already have been VERIFIED by the
    Discovery compiler.
    """
    text = str(value or "").casefold().replace("㈜", "주")
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def matching_exclusion(value, exclusions):
    candidate = normalize_entity_name(value)
    if not candidate:
        return ""
    for exclusion in exclusions or []:
        normalized = normalize_entity_name(exclusion)
        if normalized and normalized in candidate:
            return str(exclusion)
    return ""


def is_excluded_entity(value, exclusions):
    return bool(matching_exclusion(value, exclusions))
