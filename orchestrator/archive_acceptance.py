"""Fail-closed acceptance checks for the final human-facing archive.

Collection/package validation answers whether the evidence is trustworthy. This
module answers a different question: whether the exact artifact a user receives
still satisfies the human-delivery contract.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

PROHIBITED_USER_SUFFIXES = {".html", ".htm", ".json", ".jsonl"}
REQUIRED_USER_XLSX = {
    "CLEANSYS_AIR": "01_사용자자료/01_TMS/대기_CleanSYS/CleanSYS_대기TMS_정리.xlsx",
    "SOOSIRO_WATER": "01_사용자자료/01_TMS/수질_SOOSIRO/SOOSIRO_수질TMS_정리.xlsx",
    "PRTR": "01_사용자자료/02_화학물질/PRTR_배출이동량/PRTR_화학물질배출이동량_정리.xlsx",
    "CHEM_STATS": "01_사용자자료/02_화학물질/화학물질통계/화학물질통계_정리.xlsx",
}
SUSTAINABILITY_FOLDER = "01_사용자자료/04_지속가능경영보고서"
REVIEW_FOLDER = "01_사용자자료/00_환경관리검토"
BAT_ROOT = "02_BAT_참고자료"
BAT_INDEX = f"{BAT_ROOT}/00_BAT_적용후보_및_수집현황.xlsx"
BAT_DOCUMENT_ROOT = f"{BAT_ROOT}/01_BAT_원문"
BAT_SITE_MAP_ROOT = f"{BAT_ROOT}/02_사업장별_적용맵"
LEGACY_BAT_ROOT = "01_사용자자료/07_가이드라인_참고자료/BAT_기준서"
YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def _pdf_bytes_ok(data: bytes) -> bool:
    return len(data) >= 1000 and data.lstrip().startswith(b"%PDF-") and b"%%EOF" in data[-4096:]


def _xlsx_bytes_ok(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            names = set(zf.namelist())
            return (
                "[Content_Types].xml" in names
                and "xl/workbook.xml" in names
                and any(name.startswith("xl/worksheets/") and name.endswith(".xml") for name in names)
                and zf.testzip() is None
            )
    except (OSError, zipfile.BadZipFile):
        return False


def _tree_files(root: Path) -> dict[str, Path]:
    return {
        p.relative_to(root).as_posix(): p
        for p in root.rglob("*")
        if p.is_file()
    }


def _bat_tree_checks(files: dict[str, Path]) -> tuple[dict[str, bool], list[dict[str, str]]]:
    failures: list[dict[str, str]] = []
    bat_files = {name: p for name, p in files.items() if name.startswith(BAT_ROOT + "/")}
    legacy = sorted(name for name in files if name.startswith(LEGACY_BAT_ROOT + "/"))
    if legacy:
        failures.append({"check": "LEGACY_BAT_EMBEDDED_ABSENT", "detail": ", ".join(legacy[:20])})

    if not bat_files:
        return {
            "bat_reference_area_valid": True,
            "legacy_bat_embedded_absent": not legacy,
        }, failures

    index = bat_files.get(BAT_INDEX)
    if index is None or not _xlsx_bytes_ok(index.read_bytes()):
        failures.append({"check": "BAT_INDEX_VALID", "detail": BAT_INDEX})

    bad_suffix = sorted(
        name for name in bat_files
        if Path(name).suffix.lower() not in {".pdf", ".xlsx"}
    )
    if bad_suffix:
        failures.append({"check": "BAT_HUMAN_FORMATS_ONLY", "detail": ", ".join(bad_suffix[:20])})

    bad_maps = []
    for name, p in bat_files.items():
        if name.startswith(BAT_SITE_MAP_ROOT + "/"):
            if Path(name).suffix.lower() != ".xlsx" or not _xlsx_bytes_ok(p.read_bytes()):
                bad_maps.append(name)
    if bad_maps:
        failures.append({"check": "BAT_SITE_MAPS_VALID", "detail": ", ".join(bad_maps[:20])})

    bad_pdfs = []
    misplaced_pdfs = []
    for name, p in bat_files.items():
        if Path(name).suffix.lower() != ".pdf":
            continue
        if not name.startswith(BAT_DOCUMENT_ROOT + "/"):
            misplaced_pdfs.append(name)
        if not _pdf_bytes_ok(p.read_bytes()):
            bad_pdfs.append(name)
    if misplaced_pdfs:
        failures.append({"check": "BAT_PDFS_SINGLE_SOURCE_AREA", "detail": ", ".join(misplaced_pdfs[:20])})
    if bad_pdfs:
        failures.append({"check": "BAT_PDFS_STRUCTURALLY_VALID", "detail": ", ".join(bad_pdfs[:20])})

    return {
        "bat_reference_area_valid": not any(f["check"].startswith("BAT_") for f in failures),
        "legacy_bat_embedded_absent": not legacy,
    }, failures


def _bat_zip_checks(files: dict[str, bytes]) -> tuple[dict[str, bool], list[dict[str, str]]]:
    failures: list[dict[str, str]] = []
    bat_files = {name: data for name, data in files.items() if name.startswith(BAT_ROOT + "/")}
    legacy = sorted(name for name in files if name.startswith(LEGACY_BAT_ROOT + "/"))
    if legacy:
        failures.append({"check": "LEGACY_BAT_EMBEDDED_ABSENT", "detail": ", ".join(legacy[:20])})

    if not bat_files:
        return {
            "bat_reference_area_valid": True,
            "legacy_bat_embedded_absent": not legacy,
        }, failures

    index = bat_files.get(BAT_INDEX)
    if index is None or not _xlsx_bytes_ok(index):
        failures.append({"check": "BAT_INDEX_VALID", "detail": BAT_INDEX})

    bad_suffix = sorted(
        name for name in bat_files
        if Path(name).suffix.lower() not in {".pdf", ".xlsx"}
    )
    if bad_suffix:
        failures.append({"check": "BAT_HUMAN_FORMATS_ONLY", "detail": ", ".join(bad_suffix[:20])})

    bad_maps = [
        name for name, data in bat_files.items()
        if name.startswith(BAT_SITE_MAP_ROOT + "/")
        and (Path(name).suffix.lower() != ".xlsx" or not _xlsx_bytes_ok(data))
    ]
    if bad_maps:
        failures.append({"check": "BAT_SITE_MAPS_VALID", "detail": ", ".join(bad_maps[:20])})

    misplaced_pdfs = [
        name for name in bat_files
        if Path(name).suffix.lower() == ".pdf" and not name.startswith(BAT_DOCUMENT_ROOT + "/")
    ]
    if misplaced_pdfs:
        failures.append({"check": "BAT_PDFS_SINGLE_SOURCE_AREA", "detail": ", ".join(misplaced_pdfs[:20])})
    bad_pdfs = [
        name for name, data in bat_files.items()
        if Path(name).suffix.lower() == ".pdf" and not _pdf_bytes_ok(data)
    ]
    if bad_pdfs:
        failures.append({"check": "BAT_PDFS_STRUCTURALLY_VALID", "detail": ", ".join(bad_pdfs[:20])})

    return {
        "bat_reference_area_valid": not any(f["check"].startswith("BAT_") for f in failures),
        "legacy_bat_embedded_absent": not legacy,
    }, failures


def validate_archive_tree(archive_root: str | Path, expected_env_pdf_count: int | None = None) -> dict:
    root = Path(archive_root)
    files = _tree_files(root)
    failures: list[dict[str, str]] = []

    user_files = {name: p for name, p in files.items() if name.startswith("01_사용자자료/")}
    leaked = sorted(name for name in user_files if Path(name).suffix.lower() in PROHIBITED_USER_SUFFIXES)
    if leaked:
        failures.append({"check": "USER_MACHINE_FORMATS_ABSENT", "detail": ", ".join(leaked[:20])})

    invalid_xlsx = []
    for source, rel in REQUIRED_USER_XLSX.items():
        p = files.get(rel)
        if p is None:
            invalid_xlsx.append(f"{source}:missing:{rel}")
        elif not _xlsx_bytes_ok(p.read_bytes()):
            invalid_xlsx.append(f"{source}:invalid_xlsx:{rel}")
    if invalid_xlsx:
        failures.append({"check": "STRUCTURED_USER_EXPORTS_VALID", "detail": "; ".join(invalid_xlsx)})

    invalid_pdfs = []
    for name, p in user_files.items():
        if Path(name).suffix.lower() == ".pdf" and not _pdf_bytes_ok(p.read_bytes()):
            invalid_pdfs.append(name)
    if invalid_pdfs:
        failures.append({"check": "USER_PDFS_STRUCTURALLY_VALID", "detail": ", ".join(invalid_pdfs[:20])})

    sust_files = sorted(name for name in user_files if name.startswith(SUSTAINABILITY_FOLDER + "/"))
    sust_nested = [name for name in sust_files if len(Path(name).relative_to(SUSTAINABILITY_FOLDER).parts) != 1]
    sust_non_pdf = [name for name in sust_files if Path(name).suffix.lower() != ".pdf"]
    sust_no_year = [name for name in sust_files if not YEAR_RE.search(Path(name).name)]
    if sust_nested or sust_non_pdf or sust_no_year:
        detail = []
        if sust_nested:
            detail.append("nested=" + ",".join(sust_nested[:10]))
        if sust_non_pdf:
            detail.append("non_pdf=" + ",".join(sust_non_pdf[:10]))
        if sust_no_year:
            detail.append("no_year=" + ",".join(sust_no_year[:10]))
        failures.append({"check": "SUSTAINABILITY_SHALLOW_PDF_SERIES", "detail": "; ".join(detail)})

    review_files = sorted(name for name in user_files if name.startswith(REVIEW_FOLDER + "/"))
    review_bad = [name for name in review_files if Path(name).suffix.lower() not in {".pdf", ".xlsx"}]
    if review_bad:
        failures.append({"check": "REVIEW_USER_FORMATS", "detail": ", ".join(review_bad[:20])})

    env_detail_pdfs = [
        name for name in user_files
        if name.startswith("01_사용자자료/03_환경정보공개시스템/")
        and "/첨부자료/" not in name
        and Path(name).suffix.lower() == ".pdf"
        and Path(name).name.startswith("환경정보공개_")
    ]
    if expected_env_pdf_count is not None and len(env_detail_pdfs) < expected_env_pdf_count:
        failures.append({
            "check": "ENVINFO_SITE_YEAR_PDF_COMPLETE",
            "detail": f"expected>={expected_env_pdf_count}; actual={len(env_detail_pdfs)}",
        })

    bat_checks, bat_failures = _bat_tree_checks(files)
    failures.extend(bat_failures)

    checks = {
        "user_machine_formats_absent": not leaked,
        "structured_user_exports_valid": not invalid_xlsx,
        "user_pdfs_structurally_valid": not invalid_pdfs,
        "sustainability_shallow_pdf_series": not (sust_nested or sust_non_pdf or sust_no_year),
        "review_user_formats": not review_bad,
        "envinfo_site_year_pdf_complete": expected_env_pdf_count is None or len(env_detail_pdfs) >= expected_env_pdf_count,
        **bat_checks,
    }
    return {"status": "PASS" if not failures else "FAIL", "checks": checks, "failures": failures}


def _zip_members(zip_path: Path) -> tuple[str, dict[str, bytes]]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity failure at {bad}")
        files = [i for i in zf.infolist() if not i.is_dir()]
        if not files:
            raise RuntimeError("archive ZIP is empty")
        roots = {Path(i.filename).parts[0] for i in files if Path(i.filename).parts}
        if len(roots) != 1:
            raise RuntimeError(f"archive ZIP must have exactly one root folder, found {sorted(roots)}")
        root = next(iter(roots))
        return root, {
            Path(info.filename).relative_to(root).as_posix(): zf.read(info)
            for info in files
        }


def validate_archive_zip(zip_path: str | Path, expected_env_pdf_count: int | None = None) -> dict:
    path = Path(zip_path)
    try:
        root_name, files = _zip_members(path)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        return {"status": "FAIL", "checks": {"zip_integrity": False}, "failures": [{"check": "ZIP_INTEGRITY", "detail": str(exc)}]}

    failures: list[dict[str, str]] = []
    user = {name: data for name, data in files.items() if name.startswith("01_사용자자료/")}
    leaked = sorted(name for name in user if Path(name).suffix.lower() in PROHIBITED_USER_SUFFIXES)
    if leaked:
        failures.append({"check": "USER_MACHINE_FORMATS_ABSENT", "detail": ", ".join(leaked[:20])})

    bad_xlsx = []
    for source, rel in REQUIRED_USER_XLSX.items():
        data = files.get(rel)
        if data is None:
            bad_xlsx.append(f"{source}:missing:{rel}")
        elif not _xlsx_bytes_ok(data):
            bad_xlsx.append(f"{source}:invalid_xlsx:{rel}")
    if bad_xlsx:
        failures.append({"check": "STRUCTURED_USER_EXPORTS_VALID", "detail": "; ".join(bad_xlsx)})

    bad_pdf = [name for name, data in user.items() if Path(name).suffix.lower() == ".pdf" and not _pdf_bytes_ok(data)]
    if bad_pdf:
        failures.append({"check": "USER_PDFS_STRUCTURALLY_VALID", "detail": ", ".join(bad_pdf[:20])})

    sust = sorted(name for name in user if name.startswith(SUSTAINABILITY_FOLDER + "/"))
    nested = [name for name in sust if len(Path(name).relative_to(SUSTAINABILITY_FOLDER).parts) != 1]
    non_pdf = [name for name in sust if Path(name).suffix.lower() != ".pdf"]
    no_year = [name for name in sust if not YEAR_RE.search(Path(name).name)]
    if nested or non_pdf or no_year:
        failures.append({"check": "SUSTAINABILITY_SHALLOW_PDF_SERIES", "detail": json.dumps({"nested": nested[:10], "non_pdf": non_pdf[:10], "no_year": no_year[:10]}, ensure_ascii=False)})

    review_bad = [name for name in user if name.startswith(REVIEW_FOLDER + "/") and Path(name).suffix.lower() not in {".pdf", ".xlsx"}]
    if review_bad:
        failures.append({"check": "REVIEW_USER_FORMATS", "detail": ", ".join(review_bad[:20])})

    env_count = sum(
        1 for name in user
        if name.startswith("01_사용자자료/03_환경정보공개시스템/")
        and "/첨부자료/" not in name
        and Path(name).suffix.lower() == ".pdf"
        and Path(name).name.startswith("환경정보공개_")
    )
    if expected_env_pdf_count is not None and env_count < expected_env_pdf_count:
        failures.append({"check": "ENVINFO_SITE_YEAR_PDF_COMPLETE", "detail": f"expected>={expected_env_pdf_count}; actual={env_count}"})

    bat_checks, bat_failures = _bat_zip_checks(files)
    failures.extend(bat_failures)

    return {
        "status": "PASS" if not failures else "FAIL",
        "archive_root": root_name,
        "checks": {
            "zip_integrity": True,
            "user_machine_formats_absent": not leaked,
            "structured_user_exports_valid": not bad_xlsx,
            "user_pdfs_structurally_valid": not bad_pdf,
            "sustainability_shallow_pdf_series": not (nested or non_pdf or no_year),
            "review_user_formats": not review_bad,
            "envinfo_site_year_pdf_complete": expected_env_pdf_count is None or env_count >= expected_env_pdf_count,
            **bat_checks,
        },
        "failures": failures,
    }


def assert_pass(report: dict, label: str = "archive") -> dict:
    if report.get("status") != "PASS":
        raise RuntimeError(f"{label} acceptance failed: " + json.dumps(report.get("failures", []), ensure_ascii=False))
    return report
