import re
from pathlib import Path

STRONG_VERIFICATION = {"VERIFIED", "SOURCE_VERIFIED"}
YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def _year(value):
    if value in (None, ""):
        return None
    text = str(value)
    m = YEAR_RE.search(text)
    if m:
        return int(m.group(1))
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if 1900 <= value <= 2100 else None


def _range_years(start, end):
    a = _year(start); b = _year(end)
    if a is None or b is None or a > b or b - a > 30:
        return set()
    return set(range(a, b + 1))


def _file_year(path):
    # Archive filenames intentionally place the report/disclosure year near the front.
    # Use the first explicit four-digit year instead of inferring from file timestamps.
    m = YEAR_RE.search(Path(path).name)
    return int(m.group(1)) if m else None


def evaluate(profile, document_rows, sustainability_paths):
    """Evaluate sustainability-report history against the full verified series.

    A report year can be expected because a verified document record, a verified
    official archive/index, or an explicit requested-history window says that the
    annual series should cover it.  It counts as delivered only when a real report
    file is present.  Minimum-history policy is a floor for discovery quality; it is
    never permission to discard older verified years from a longer known series.
    """
    profile = profile or {}
    document_rows = document_rows or []
    minimum = profile.get("minimum_history_years", 5)
    try:
        minimum = max(1, int(minimum))
    except (TypeError, ValueError):
        minimum = 5

    active = profile.get("current_legal_name_active_period") or {}
    legal_start = _year(active.get("start_year"))
    requested = profile.get("requested_history_window") or {}
    requested_years = _range_years(requested.get("start_year"), requested.get("end_year"))

    delivered_years = {y for y in (_file_year(p) for p in sustainability_paths) if y is not None}
    expected_years = set(delivered_years)
    failed_download_years = set()
    declared_report_years = set()
    verified_index_ranges = []
    annual_series_verified = False

    for row in document_rows:
        dtype = str(row.get("document_type") or "").upper()
        title = str(row.get("title") or "")
        verification = str(row.get("verification_status") or "").upper()
        if verification not in STRONG_VERIFICATION:
            continue
        year = _year(row.get("report_year"))
        if dtype == "SUSTAINABILITY_REPORT":
            annual_series_verified = True
            if year is not None:
                declared_report_years.add(year)
                expected_years.add(year)
                if str(row.get("collection_status") or "").upper() == "DOWNLOAD_FAILED":
                    failed_download_years.add(year)
            continue

        # Some companies expose a verified report archive/index rather than one direct
        # document per year. Only explicit coverage_start/end metadata may expand the
        # expected series; title text alone never manufactures years.
        lower = title.lower()
        looks_report_index = (
            dtype in {"SUSTAINABILITY_REPORT_INDEX", "ESG_REPORT_INDEX"}
            or (dtype == "ENVIRONMENTAL_DISCLOSURE" and ("지속가능" in title or "sustainab" in lower))
        )
        if looks_report_index:
            annual_series_verified = True
            years = _range_years(row.get("coverage_start"), row.get("coverage_end"))
            if years:
                expected_years.update(years)
                verified_index_ranges.append({"start_year": min(years), "end_year": max(years)})

    # Once the annual report series itself is verified, an explicit requested history
    # window is a completeness obligation, not a suggestion to retain only latest N.
    if annual_series_verified and requested_years:
        expected_years.update(requested_years)

    if legal_start is not None:
        expected_years = {y for y in expected_years if y >= legal_start}
        delivered_years = {y for y in delivered_years if y >= legal_start}

    expected_sorted = sorted(expected_years)
    delivered_sorted = sorted(delivered_years)
    target_years = expected_sorted
    required = len(target_years)

    if not expected_sorted:
        state = "NO_VERIFIED_REPORT_SERIES"
        sufficient = False
    elif len(expected_sorted) < minimum and not (
        legal_start is not None and expected_sorted[-1] - legal_start + 1 < minimum
    ):
        state = "DISCOVERY_COVERAGE_SHORT"
        sufficient = False
    else:
        missing = sorted(set(target_years) - delivered_years)
        sufficient = not missing
        state = "FILE_COVERAGE_COMPLETE" if sufficient else "FILE_COVERAGE_PARTIAL"

    missing_years = sorted(set(target_years) - delivered_years)
    return {
        "schema_version": "1.1",
        "state": state,
        "minimum_history_years": minimum,
        "required_report_count": required,
        "expected_report_years": expected_sorted,
        "target_report_years": target_years,
        "delivered_report_years": delivered_sorted,
        "missing_target_years": missing_years,
        "declared_report_years": sorted(declared_report_years),
        "failed_download_years": sorted(failed_download_years),
        "verified_index_ranges": verified_index_ranges,
        "coverage_sufficient": sufficient,
        "principle": "Every year in the verified/requested annual series must be delivered or explicitly resolved; minimum-history is never a license to drop older known years.",
    }
