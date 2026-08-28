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
    """Evaluate user-facing sustainability-report history without conflating discovery and files.

    A report year can be *expected* because a verified document record or verified official
    archive/index says it exists, but it counts as *delivered* only when a real file is in
    01_사용자자료/04_지속가능경영보고서.  This prevents an index page or a timed-out URL
    from satisfying archive completeness.
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

    delivered_years = {y for y in (_file_year(p) for p in sustainability_paths) if y is not None}
    expected_years = set(delivered_years)
    failed_download_years = set()
    declared_report_years = set()
    verified_index_ranges = []

    for row in document_rows:
        dtype = str(row.get("document_type") or "").upper()
        title = str(row.get("title") or "")
        verification = str(row.get("verification_status") or "").upper()
        if verification not in STRONG_VERIFICATION:
            continue
        year = _year(row.get("report_year"))
        if dtype == "SUSTAINABILITY_REPORT":
            if year is not None:
                declared_report_years.add(year)
                expected_years.add(year)
                if str(row.get("collection_status") or "") == "DOWNLOAD_FAILED":
                    failed_download_years.add(year)
            continue

        # Some companies expose a verified report archive/index rather than one direct
        # document per year.  Only explicit coverage_start/end metadata may expand the
        # expected series; title text alone never manufactures years.
        lower = title.lower()
        looks_report_index = (
            dtype in {"SUSTAINABILITY_REPORT_INDEX", "ESG_REPORT_INDEX"}
            or (dtype == "ENVIRONMENTAL_DISCLOSURE" and ("지속가능" in title or "sustainab" in lower))
        )
        if looks_report_index:
            years = _range_years(row.get("coverage_start"), row.get("coverage_end"))
            if years:
                expected_years.update(years)
                verified_index_ranges.append({"start_year": min(years), "end_year": max(years)})

    expected_sorted = sorted(expected_years)
    delivered_sorted = sorted(delivered_years)
    latest = expected_sorted[-1] if expected_sorted else None
    required = minimum
    if legal_start is not None and latest is not None and legal_start <= latest:
        required = min(required, latest - legal_start + 1)

    if not expected_sorted:
        target_years = []
        state = "NO_VERIFIED_REPORT_SERIES"
        sufficient = False
    elif len(expected_sorted) < required:
        target_years = expected_sorted
        state = "DISCOVERY_COVERAGE_SHORT"
        sufficient = False
    else:
        target_years = expected_sorted[-required:]
        missing = sorted(set(target_years) - delivered_years)
        sufficient = not missing
        state = "FILE_COVERAGE_COMPLETE" if sufficient else "FILE_COVERAGE_PARTIAL"

    missing_years = sorted(set(target_years) - delivered_years)
    return {
        "schema_version": "1.0",
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
        "principle": "Verified existence/index coverage and actual delivered report files are separate states; only delivered files satisfy archive completeness.",
    }
