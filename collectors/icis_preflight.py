"""Classify ICIS preflight HTTP replies separately from network failures."""


def classify_preflight_error(exc):
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    if code is None:
        return "REMOTE_HOST_UNREACHABLE", None
    code = int(code)
    if code in (404, 410):
        return "REMOTE_ENDPOINT_NOT_FOUND", code
    if code in (401, 403):
        return "REMOTE_ACCESS_RESTRICTED", code
    if code == 429 or 500 <= code <= 599:
        return "REMOTE_HTTP_UNAVAILABLE", code
    return "REMOTE_HTTP_REJECTED", code
