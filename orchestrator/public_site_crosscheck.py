"""Conservative public-source facility evidence comparison.

Use real, independently captured ENVINFO and CHEM_STATS records to identify
name/location correlations without claiming their source-native IDs are
interchangeable. TMS applicability and zero emissions are never inferred from
a missing registry match. The module only audits evidence; it never mutates
verified facilities or collector requests.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

TMS = ("CLEANSYS_AIR", "SOOSIRO_WATER")
REGIONS = {
    "서울": "서울", "부산": "부산", "대구": "대구", "인천": "인천",
    "광주": "광주", "대전": "대전", "울산": "울산", "세종": "세종",
    "경기": "경기", "강원": "강원", "충북": "충북", "충청북": "충북",
    "충남": "충남", "충청남": "충남", "전북": "전북", "전라북": "전북",
    "전남": "전남", "전라남": "전남", "경북": "경북", "경상북": "경북",
    "경남": "경남", "경상남": "경남", "제주": "제주",
}


def _read_json(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8-sig"))
    return {}


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def legal_key(name: str) -> str:
    value = re.sub(r"\s+", "", str(name or ""))
    value = re.sub(r"^(?:\(주\)|㈜|주식회사)+", "", value)
    value = re.sub(r"(?:\(주\)|㈜|주식회사)+$", "", value)
    return value.casefold()


def road_address(address: str) -> dict:
    """Compare the primary Korean road-number anchor, not full facility identity.

    Extra comma-separated numbers must survive the comparison as a warning.
    Never use this loose anchor as a facility-ID or TMS registry key.
    """
    value = re.sub(r"\s+", " ", str(address or "")).strip()
    value = re.sub(r"([가-힣]+로)\s+(\d+(?:번)?길)", r"\1\2", value)
    region_match = re.match(
        r"^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|"
        r"충청북|충청남|전북|전남|전라북|전라남|경북|경남|경상북|경상남|제주)",
        value,
    )
    region = REGIONS.get(region_match.group(1), "") if region_match else ""
    matches = list(re.finditer(
        r"([가-힣0-9]+(?:대로|로|길))\s*(\d+(?:-\d+)?)", value
    ))
    if not matches:
        return {"region": region, "road": "", "number": "", "key": "",
                "additional_numbers": [], "raw": value}
    first = matches[0]
    road = re.sub(r"\s+", "", first.group(1))
    number = first.group(2)
    following = value[first.end():]
    # A corporate complex can publish 36, 50, 60, 70 while one registry reports
    # only 36. This proves neither source records a separate facility nor the same one.
    extra = re.match(r"\s*,\s*(\d+(?:\s*,\s*\d+)*)", following)
    additional = re.findall(r"\d+", extra.group(1)) if extra else []
    return {"region": region, "road": road, "number": number,
            "key": f"{region}|{road}|{number}" if region else "",
            "additional_numbers": additional, "raw": value}


def envinfo_official_site_rows(env_root: Path) -> list[dict]:
    """Extract only explicit, labelled first-party business-site tables."""
    rows = []
    for html in sorted((env_root / "raw_detail").glob("*.html")):
        soup = BeautifulSoup(html.read_bytes(), "html.parser")
        year_match = re.match(r"(20\d\d)_", html.name)
        for tr in soup.find_all("tr"):
            cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip()
                     for td in tr.find_all(["td", "th"], recursive=False)]
            if len(cells) < 3 or not any(
                label in cells[0] for label in ("대표사업장", "사업장", "본사")
            ):
                continue
            name, address = cells[1], cells[2]
            anchor = road_address(address)
            if not anchor["key"] or not legal_key(name):
                continue
            rows.append({
                "year": int(year_match.group(1)) if year_match else None,
                "source": "ENVINFO_DETAIL",
                "site_name": name,
                "address": address,
                "location": anchor,
                "proof": html.as_posix(),
            })
    return rows


def evaluate(output_root: str | Path, current_legal_name: str) -> dict:
    root = Path(output_root)
    env = root / "ENVINFO"
    chem = root / "CHEM_STATS"
    target = legal_key(current_legal_name)
    if not target:
        raise ValueError("Verified current legal entity name required")
    env_rows = _read_csv(env / "discovery.csv")
    chem_rows = _read_csv(chem / "discovery.csv")
    if not env_rows or not chem_rows:
        return {
            "status": "REVIEW_REQUIRED",
            "reason": "CROSS_SOURCE_INPUT_NOT_AVAILABLE",
            "source_rows": {"ENVINFO": len(env_rows), "CHEM_STATS": len(chem_rows)},
            "facility_id_crosswalk_verified": False,
        }

    env_ids: dict[str, set[int]] = defaultdict(set)
    for row in env_rows:
        if legal_key(row.get("compNm", "")) != target:
            continue
        sid = str(row.get("compId") or "").strip()
        if sid:
            try:
                env_ids[sid].add(int(row["year"]))
            except (KeyError, TypeError, ValueError):
                pass

    explicit = [
        row for row in envinfo_official_site_rows(env)
        if legal_key(row["site_name"]) == target
    ]
    chem_sites = []
    for row in chem_rows:
        if legal_key(row.get("bplcNm", "")) != target:
            continue
        source_id = str(row.get("bplcId") or "").strip()
        address = road_address(row.get("locplcAdres", ""))
        if not source_id:
            continue
        chem_sites.append({
            "source_id": source_id,
            "year": row.get("reportYear") or row.get("search_year"),
            "site_name": row.get("bplcNm"),
            "address": row.get("locplcAdres"),
            "location": address,
        })

    matching = []
    for chem_row in chem_sites:
        corresponding = [
            site for site in explicit
            if chem_row["location"]["key"] and
            chem_row["location"]["key"] == site["location"]["key"]
        ]
        matching.append({
            "chem_source_id": chem_row["source_id"],
            "chem_year": chem_row["year"],
            "same_legal_name": True,
            "official_envinfo_location_years": sorted({
                site["year"] for site in corresponding if site["year"] is not None
            }),
            "shared_primary_road_anchor": bool(corresponding),
            "chem_multiple_address_numbers": chem_row["location"]["additional_numbers"],
            "chem_address": chem_row["address"],
        })

    chem_ids = sorted(set(x["source_id"] for x in chem_sites))
    joint = bool(env_ids) and bool(explicit) and bool(chem_sites) and all(
        row["shared_primary_road_anchor"] for row in matching
    )
    crosswalk = "RELATED_LOCATION_CANDIDATES_NOT_VERIFIED_AS_IDENTICAL_FACILITY"
    tms = {}
    for source in TMS:
        status = _read_json(root / source / "status.json")
        if not status:
            tms[source] = {
                "query_state": "NOT_RUN", "facility_identity": "UNVERIFIED",
                "disclosure_applicability": "UNCONFIRMED",
            }
            continue
        found = status.get("status") == "DATA_FOUND"
        tms[source] = {
            "query_state": status.get("status"),
            "registry_scan_complete": status.get("registry_scan_complete"),
            "source_native_id_found": bool(
                status.get("fact_codes") or status.get("candidate_count")
            ),
            "facility_identity": (
                "SOURCE_NATIVE_CANDIDATE_REQUIRES_RECORD_REVIEW" if found
                else "UNVERIFIED_NO_ID_MATCH"
            ),
            "disclosure_applicability": "UNCONFIRMED",
            "no_emissions_inference": True,
        }

    issues = []
    if not env_ids:
        issues.append("ENVINFO_LEGAL_ID_NOT_VERIFIED")
    if not explicit:
        issues.append("ENVINFO_SITE_ADDRESS_NOT_EXPLICITLY_EXTRACTED")
    if not chem_sites:
        issues.append("CHEM_STATS_LEGAL_SITE_NOT_VERIFIED")
    if chem_sites and not joint:
        issues.append("CROSS_SOURCE_LOCATION_CORRELATION_INCOMPLETE")
    if len(chem_ids) > 1:
        issues.append("MULTIPLE_SOURCE_NATIVE_CHEM_IDS_NO_AUTO_MERGE")
    if any(x["chem_multiple_address_numbers"] for x in matching):
        issues.append("MULTI_NUMBER_LOCATION_SCOPE_REQUIRES_REVIEW")
    if any(v.get("facility_identity") == "UNVERIFIED_NO_ID_MATCH" for v in tms.values()):
        issues.append("TMS_NO_MATCH_DOES_NOT_PROVE_NON_APPLICABILITY")

    return {
        "status": "CORRELATED_WITH_LIMITATIONS" if joint else "REVIEW_REQUIRED",
        "company_legal_name": current_legal_name,
        "source_rows": {"ENVINFO": len(env_rows), "CHEM_STATS": len(chem_rows)},
        "envinfo_native_ids": [
            {"id": sid, "years": sorted(years)} for sid, years in sorted(env_ids.items())
        ],
        "envinfo_official_site_rows": explicit,
        "chem_native_ids": chem_ids,
        "chem_sites": chem_sites,
        "location_correlation": matching,
        "crosswalk_state": crosswalk,
        "facility_id_crosswalk_verified": False,
        "tms": tms,
        "review_issues": issues,
        "principle": (
            "Matching legal name and road address establishes correlated source records, "
            "not equivalence of facility IDs, not direct wastewater treatment linkage, "
            "and not TMS non-applicability or zero emissions."
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output-root", default="output")
    p.add_argument("--legal-name", required=True)
    p.add_argument("--out", default="Public_Source_Site_Crosscheck.json")
    args = p.parse_args()
    result = evaluate(args.output_root, args.legal_name)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "envinfo_native_ids": len(result.get("envinfo_native_ids") or []),
        "chem_native_ids": len(result.get("chem_native_ids") or []),
        "tms": {k: v["facility_identity"] for k, v in result.get("tms", {}).items()},
        "review_issues": result.get("review_issues", []),
    }, ensure_ascii=False))
    return 0 if result["status"] == "CORRELATED_WITH_LIMITATIONS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
