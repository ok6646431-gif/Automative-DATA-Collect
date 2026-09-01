from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import posixpath
import re
import zipfile
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Iterable


USER_PREFIX = "01_사용자자료/"
INDEX_PREFIX = "00_자료목록/"
WEB_ENDPOINT_EXTENSIONS = {".do", ".jsp", ".action", ".cgi", ".php", ".aspx"}
ENVINFO_PREFIX = "02_환경인허가_ENVINFO/"
ENVINFO_ATTACHMENT_MARKER = "/첨부자료/"
YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")

MAPPINGS = [
    ("01_사용자자료/00_환경관리검토/", "09_지원서공부용/00_환경관리검토/"),
    ("01_사용자자료/01_TMS/대기_CleanSYS/", "03_대기/CleanSYS/"),
    ("01_사용자자료/01_TMS/수질_SOOSIRO/", "04_수질/SOOSIRO/"),
    ("01_사용자자료/02_화학물질/PRTR_배출이동량/", "05_화학물질/PRTR_배출이동량/"),
    ("01_사용자자료/02_화학물질/화학물질통계/", "05_화학물질/화학물질통계/"),
    ("01_사용자자료/03_환경정보공개시스템/", "02_환경인허가_ENVINFO/"),
    ("01_사용자자료/04_지속가능경영보고서/", "06_지속가능경영보고서/"),
    ("01_사용자자료/06_회사환경정책/", "07_회사환경정책_ESG/"),
    ("01_사용자자료/07_가이드라인_참고자료/", "08_BAT_기술기준/"),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def find_relative_member(name: str) -> str | None:
    parts = PurePosixPath(name).parts
    for marker in ("00_자료목록", "01_사용자자료"):
        if marker in parts:
            idx = parts.index(marker)
            return "/".join(parts[idx:])
    return None


def map_relative_path(relative: str) -> str | None:
    if relative.startswith(INDEX_PREFIX):
        return "00_자료목록/원본검증목록/" + relative[len(INDEX_PREFIX):]
    for old, new in MAPPINGS:
        if relative.startswith(old):
            return new + relative[len(old):]
    if relative.startswith(USER_PREFIX):
        return "10_기타사용자자료/" + relative[len(USER_PREFIX):]
    return None


def is_envinfo_attachment(path: str) -> bool:
    return path.startswith(ENVINFO_PREFIX) and ENVINFO_ATTACHMENT_MARKER in path


def envinfo_site(path: str) -> str:
    parts = PurePosixPath(path).parts
    return parts[1] if len(parts) > 1 and parts[0] == ENVINFO_PREFIX.rstrip("/") else ""


def path_year(path: str) -> str:
    match = YEAR_RE.search(PurePosixPath(path).name)
    return match.group(1) if match else ""


def detect_payload_extension(data: bytes) -> str | None:
    """Return a user-facing extension only when the payload is confidently identifiable."""
    head = data[:8192]
    stripped = head.lstrip()
    lower = stripped.lower()

    if head.startswith(b"%PDF-"):
        return ".pdf"
    if head.startswith((b"\x89PNG\r\n\x1a\n",)):
        return ".png"
    if head.startswith((b"\xff\xd8\xff",)):
        return ".jpg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if lower.startswith(b"<!doctype html") or lower.startswith(b"<html") or b"<html" in lower[:2048]:
        return ".html"
    if stripped.startswith((b"{", b"[")):
        try:
            json.loads(data.decode("utf-8-sig"))
            return ".json"
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data), "r") as z:
                names = set(z.namelist())
                if "[Content_Types].xml" in names:
                    if any(name.startswith("xl/") for name in names):
                        return ".xlsx"
                    if any(name.startswith("word/") for name in names):
                        return ".docx"
                    if any(name.startswith("ppt/") for name in names):
                        return ".pptx"
                return ".zip"
        except zipfile.BadZipFile:
            pass
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        # Legacy OLE compound files cannot be distinguished reliably without extra parsing.
        return None
    return None


def normalize_user_extension(path: str, data: bytes) -> tuple[str, str]:
    """Replace servlet/web endpoint suffixes with the actual payload extension when certain."""
    stem, ext = posixpath.splitext(path)
    ext_lower = ext.lower()
    if ext_lower not in WEB_ENDPOINT_EXTENSIONS:
        return path, "UNCHANGED"
    detected = detect_payload_extension(data)
    if not detected:
        return path, "UNRESOLVED_WEB_ENDPOINT_EXTENSION"
    return stem + detected, f"RENAMED_{ext_lower}_TO_{detected}"


def safe_collision_path(path: str, taken: dict[str, str], digest: str) -> tuple[str, str]:
    if path not in taken:
        return path, "COPIED"
    if taken[path] == digest:
        return path, "SKIPPED_IDENTICAL_PATH_COLLISION"
    stem, ext = posixpath.splitext(path)
    n = 2
    while True:
        candidate = f"{stem}__{n}{ext}"
        if candidate not in taken:
            return candidate, "RENAMED_PATH_COLLISION"
        if taken[candidate] == digest:
            return candidate, "SKIPPED_IDENTICAL_PATH_COLLISION"
        n += 1


def write_csv(rows: Iterable[dict[str, object]], fieldnames: list[str]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def read_prior_envinfo_attachment_references(src: zipfile.ZipFile) -> list[dict[str, str]]:
    """Read logical ENVINFO attachments removed by Human Archive same-folder dedup.

    The Human Archive deliberately stores exact same-folder copies once and records the
    removed logical paths in ``Deduplicated_User_File_References.csv``.  A support
    package must merge those rows into its own reference inventory; otherwise it would
    under-count attachment relationships merely because an earlier packaging stage
    already avoided repeated bytes.
    """
    suffix = "/00_자료목록/Deduplicated_User_File_References.csv"
    matches = [info for info in src.infolist() if not info.is_dir() and info.filename.endswith(suffix)]
    if not matches:
        return []
    if len(matches) != 1:
        raise RuntimeError(
            "expected at most one Deduplicated_User_File_References.csv, "
            f"found {len(matches)}"
        )
    text = src.read(matches[0]).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    result = []
    for row in rows:
        removed = str(row.get("removed_user_path") or "")
        retained = str(row.get("retained_user_path") or "")
        if not removed.startswith("01_사용자자료/03_환경정보공개시스템/"):
            continue
        if "/첨부자료/" not in removed or "/첨부자료/" not in retained:
            continue
        result.append({key: str(value or "") for key, value in row.items()})
    return result


def build(input_zip: str, output_zip: str, root_name: str, company: str, source_run: str) -> dict[str, object]:
    inventory: list[dict[str, object]] = []
    transform_log: list[dict[str, object]] = []
    taken: dict[str, str] = {}
    copied_files = 0
    copied_bytes = 0
    skipped = 0
    extension_renamed = 0
    extension_unresolved = 0
    envinfo_attachment_by_sha: dict[str, str] = {}
    envinfo_attachment_references: list[dict[str, object]] = []
    envinfo_site_stats: dict[str, dict[str, object]] = defaultdict(
        lambda: {"records": 0, "attachment_references": 0, "attachment_hashes": set(), "years": set()}
    )
    envinfo_record_documents = 0
    envinfo_record_bytes = 0
    envinfo_unique_attachment_bytes = 0
    envinfo_duplicate_attachment_bytes_avoided = 0
    envinfo_duplicate_attachment_references = 0
    envinfo_source_duplicate_attachment_references = 0
    envinfo_logical_paths: set[str] = set()

    with zipfile.ZipFile(input_zip, "r") as src, zipfile.ZipFile(
        output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
    ) as out:
        prior_envinfo_references = read_prior_envinfo_attachment_references(src)
        for info in src.infolist():
            if info.is_dir():
                continue
            relative = find_relative_member(info.filename)
            if not relative:
                continue
            mapped = map_relative_path(relative)
            if not mapped:
                continue
            data = src.read(info)
            mapped, extension_action = normalize_user_extension(mapped, data)
            if extension_action.startswith("RENAMED_"):
                extension_renamed += 1
            elif extension_action == "UNRESOLVED_WEB_ENDPOINT_EXTENSION":
                extension_unresolved += 1
            digest = sha256_bytes(data)
            final_rel, action = safe_collision_path(mapped, taken, digest)
            retained_path = ""
            attachment = is_envinfo_attachment(final_rel)
            if action != "SKIPPED_IDENTICAL_PATH_COLLISION" and attachment:
                retained_path = envinfo_attachment_by_sha.get(digest, "")
                if retained_path:
                    action = "REFERENCED_IDENTICAL_ENVINFO_ATTACHMENT"
            transform_log.append(
                {
                    "original_path": info.filename,
                    "mapped_path": final_rel,
                    "retained_path": retained_path,
                    "sha256": digest,
                    "bytes": len(data),
                    "extension_action": extension_action,
                    "action": action,
                }
            )
            if action == "SKIPPED_IDENTICAL_PATH_COLLISION":
                skipped += 1
                continue
            taken[final_rel] = digest

            if attachment:
                site = envinfo_site(final_rel)
                year = path_year(final_rel)
                stats = envinfo_site_stats[site]
                stats["attachment_references"] = int(stats["attachment_references"]) + 1
                stats["attachment_hashes"].add(digest)
                if year:
                    stats["years"].add(year)
                duplicate_reference = bool(retained_path)
                envinfo_attachment_references.append(
                    {
                        "logical_path": final_rel,
                        "stored_path": retained_path or final_rel,
                        "site": site,
                        "year": year,
                        "bytes": len(data),
                        "sha256": digest,
                        "reference_type": (
                            "IDENTICAL_SHA256_REFERENCE" if duplicate_reference else "STORED_FILE"
                        ),
                        "source_archive_path": info.filename,
                    }
                )
                envinfo_logical_paths.add(final_rel)
                if duplicate_reference:
                    envinfo_duplicate_attachment_references += 1
                    envinfo_duplicate_attachment_bytes_avoided += len(data)
                    continue
                envinfo_attachment_by_sha[digest] = final_rel
                envinfo_unique_attachment_bytes += len(data)

            out_path = f"{root_name}/{final_rel}"
            out.writestr(out_path, data)
            inventory.append(
                {
                    "path": final_rel,
                    "bytes": len(data),
                    "sha256": digest,
                    "source_archive_path": info.filename,
                }
            )
            copied_files += 1
            copied_bytes += len(data)

            if final_rel.startswith(ENVINFO_PREFIX) and not attachment:
                site = envinfo_site(final_rel)
                year = path_year(final_rel)
                stats = envinfo_site_stats[site]
                stats["records"] = int(stats["records"]) + 1
                if year:
                    stats["years"].add(year)
                envinfo_record_documents += 1
                envinfo_record_bytes += len(data)

        envinfo_source_attachment_paths = len(envinfo_attachment_references)
        for prior in prior_envinfo_references:
            logical_path = map_relative_path(prior["removed_user_path"])
            retained_mapped_path = map_relative_path(prior["retained_user_path"])
            if not logical_path or not retained_mapped_path or logical_path in envinfo_logical_paths:
                continue
            digest = prior.get("sha256", "")
            if not digest or digest not in envinfo_attachment_by_sha:
                raise RuntimeError(
                    "prior ENVINFO attachment reference has no retained physical content: "
                    f"{prior['removed_user_path']}"
                )
            stored_path = envinfo_attachment_by_sha[digest]
            byte_count = int(prior.get("bytes") or 0)
            site = envinfo_site(logical_path)
            year = path_year(logical_path)
            stats = envinfo_site_stats[site]
            stats["attachment_references"] = int(stats["attachment_references"]) + 1
            stats["attachment_hashes"].add(digest)
            if year:
                stats["years"].add(year)
            envinfo_attachment_references.append(
                {
                    "logical_path": logical_path,
                    "stored_path": stored_path,
                    "site": site,
                    "year": year,
                    "bytes": byte_count,
                    "sha256": digest,
                    "reference_type": "IDENTICAL_SHA256_SOURCE_REFERENCE",
                    "source_archive_path": prior["removed_user_path"],
                }
            )
            envinfo_logical_paths.add(logical_path)
            envinfo_duplicate_attachment_references += 1
            envinfo_source_duplicate_attachment_references += 1
            envinfo_duplicate_attachment_bytes_avoided += byte_count

        envinfo_attachment_references.sort(key=lambda row: str(row["logical_path"]))
        envinfo_attachment_count = len(envinfo_attachment_references)
        envinfo_unique_attachment_count = len(envinfo_attachment_by_sha)
        envinfo_physical_files = envinfo_record_documents + envinfo_unique_attachment_count
        envinfo_physical_bytes = envinfo_record_bytes + envinfo_unique_attachment_bytes
        envinfo_site_count = len([site for site in envinfo_site_stats if site])

        count_rows = [
            {
                "항목": "환경정보_공개레코드",
                "값": envinfo_record_documents,
                "설명": "사업장·연도별 ENVINFO 상세 문서 수",
            },
            {
                "항목": "환경정보_첨부관계",
                "값": envinfo_attachment_count,
                "설명": "각 공개 레코드에 연결된 첨부 경로 수(동일 내용의 반복 연결 포함)",
            },
            {
                "항목": "환경정보_고유첨부파일",
                "값": envinfo_unique_attachment_count,
                "설명": "SHA-256이 서로 다른 실제 첨부파일 수",
            },
            {
                "항목": "환경정보_중복첨부참조",
                "값": envinfo_duplicate_attachment_references,
                "설명": "동일 파일을 다시 저장하지 않고 참조목록으로 보존한 첨부관계 수",
            },
            {
                "항목": "환경정보_물리파일",
                "값": envinfo_physical_files,
                "설명": "공개레코드 문서와 고유 첨부파일을 합한 실제 저장 파일 수",
            },
            {
                "항목": "환경정보_사업장",
                "값": envinfo_site_count,
                "설명": "ENVINFO 상세 문서가 포함된 사업장 수",
            },
            {
                "항목": "환경정보_중복저장방지_바이트",
                "값": envinfo_duplicate_attachment_bytes_avoided,
                "설명": "논리 참조로 전환해 반복 저장하지 않은 원본 바이트 합계",
            },
        ]
        out.writestr(
            f"{root_name}/00_자료목록/ENVINFO_자료수_설명.csv",
            write_csv(count_rows, ["항목", "값", "설명"]),
        )

        reference_bytes = write_csv(
            envinfo_attachment_references,
            [
                "logical_path",
                "stored_path",
                "site",
                "year",
                "bytes",
                "sha256",
                "reference_type",
                "source_archive_path",
            ],
        )
        out.writestr(
            f"{root_name}/00_자료목록/ENVINFO_첨부자료_참조목록.csv",
            reference_bytes,
        )

        site_rows = []
        for site, stats in sorted(envinfo_site_stats.items()):
            if not site:
                continue
            site_rows.append(
                {
                    "사업장": site,
                    "공개레코드": stats["records"],
                    "첨부관계": stats["attachment_references"],
                    "사업장내_고유첨부": len(stats["attachment_hashes"]),
                    "공개연도": "|".join(sorted(stats["years"])),
                }
            )
        out.writestr(
            f"{root_name}/00_자료목록/ENVINFO_사업장별_자료수.csv",
            write_csv(
                site_rows,
                ["사업장", "공개레코드", "첨부관계", "사업장내_고유첨부", "공개연도"],
            ),
        )

        readme = (
            f"{company} 지원용 환경자료 패키지\n\n"
            "이 패키지는 검증 완료된 Human_Archive에서 시스템 원본(90_시스템원본)을 제외하고,\n"
            "지원서·면접·직무공부에 바로 사용할 자료만 재분류한 것입니다.\n\n"
            f"원본 workflow run: {source_run}\n\n"
            "ENVINFO 자료 수:\n"
            f"- 환경정보 공개 레코드: {envinfo_record_documents}건\n"
            f"- 첨부 관계: {envinfo_attachment_count}건\n"
            f"- SHA-256 기준 고유 첨부파일: {envinfo_unique_attachment_count}개\n"
            f"- 동일 첨부 참조 전환: {envinfo_duplicate_attachment_references}건\n"
            f"- 실제 저장 파일: {envinfo_physical_files}개(공개 레코드 + 고유 첨부)\n"
            f"- 사업장: {envinfo_site_count}곳\n\n"
            "검증 범위:\n"
            "- 실제 파일 다운로드 및 0바이트/형식/해시 검증\n"
            "- 사업장·연도·수집상태(DATA_FOUND/NO_MATCH/NOT_PUBLISHED 등) 검증\n"
            "- 보고서/정책/상세자료의 자동 본문 파싱 및 의미 추출\n"
            "- 완전 동일한 ENVINFO 첨부는 SHA-256으로 한 번만 저장하고 사업장·연도 관계는 참조목록으로 보존\n"
            "- .do/.jsp/.action 등 웹 엔드포인트형 파일명은 실제 파일 시그니처를 확인해 확장자 교정\n\n"
            "주의:\n"
            "- 수백 개 PDF를 사람이 전 페이지 수동 정독한 것은 아닙니다.\n"
            "- 지원서에 사용할 핵심 내용의 선별·해석은 이 패키지를 기반으로 별도 수행합니다.\n"
            "- 공식 NOT_PUBLISHED로 확인된 연도는 파일을 가짜로 만들지 않고 미발간 상태로 기록합니다.\n"
            "- 00_자료목록/원본검증목록은 원래 검증 패키지의 목록이며, 새 경로 기준 목록은 지원용_전체자료목록.csv입니다.\n"
            "- ENVINFO_첨부자료_참조목록.csv의 logical_path와 stored_path로 중복 제거 전의 사업장·연도 연결을 확인할 수 있습니다.\n"
            "- ENVINFO_자료수_설명.csv에서 공개 레코드와 첨부파일 수를 구분해 확인할 수 있습니다.\n"
        )
        out.writestr(f"{root_name}/README_먼저보기.txt", readme.encode("utf-8"))

        inventory_bytes = write_csv(
            inventory, ["path", "bytes", "sha256", "source_archive_path"]
        )
        out.writestr(f"{root_name}/00_자료목록/지원용_전체자료목록.csv", inventory_bytes)

        transform_bytes = write_csv(
            transform_log,
            [
                "original_path",
                "mapped_path",
                "retained_path",
                "sha256",
                "bytes",
                "extension_action",
                "action",
            ],
        )
        out.writestr(f"{root_name}/00_자료목록/지원용_패키지_변환기록.csv", transform_bytes)

        summary = {
            "schema_version": "application-material-package-1.2",
            "company": company,
            "source_workflow_run": source_run,
            "source_human_archive": input_zip,
            "root_name": root_name,
            "copied_files": copied_files,
            "copied_bytes": copied_bytes,
            "skipped_identical_path_collisions": skipped,
            "web_endpoint_extensions_renamed": extension_renamed,
            "web_endpoint_extensions_unresolved": extension_unresolved,
            "system_originals_included": False,
            "folder_policy": "SUPPORT_STUDY_FACING_ONLY",
            "envinfo_disclosure_records": envinfo_record_documents,
            "envinfo_attachment_references": envinfo_attachment_count,
            "envinfo_source_attachment_paths": envinfo_source_attachment_paths,
            "envinfo_unique_attachments": envinfo_unique_attachment_count,
            "envinfo_duplicate_attachment_references": envinfo_duplicate_attachment_references,
            "envinfo_source_duplicate_attachment_references": envinfo_source_duplicate_attachment_references,
            "envinfo_physical_files": envinfo_physical_files,
            "envinfo_physical_bytes": envinfo_physical_bytes,
            "envinfo_duplicate_attachment_bytes_avoided": envinfo_duplicate_attachment_bytes_avoided,
            "envinfo_site_count": envinfo_site_count,
            "envinfo_reference_file": "00_자료목록/ENVINFO_첨부자료_참조목록.csv",
        }
        out.writestr(
            f"{root_name}/00_자료목록/지원용_패키지_요약.json",
            json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    with zipfile.ZipFile(output_zip, "r") as check:
        bad = check.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity failure: {bad}")
        names = check.namelist()
        if any("90_시스템원본" in name for name in names):
            raise RuntimeError("System-original folder leaked into support package")
        if not any(name.endswith("README_먼저보기.txt") for name in names):
            raise RuntimeError("README missing from support package")
        if not any("지원용_전체자료목록.csv" in name for name in names):
            raise RuntimeError("Support-package inventory missing")
        if not any("ENVINFO_첨부자료_참조목록.csv" in name for name in names):
            raise RuntimeError("ENVINFO attachment reference inventory missing")
        envinfo_physical_members = [name for name in names if f"/{ENVINFO_PREFIX}" in name]
        if len(envinfo_physical_members) != summary["envinfo_physical_files"]:
            raise RuntimeError(
                "ENVINFO physical-file count mismatch: "
                f"archive={len(envinfo_physical_members)} summary={summary['envinfo_physical_files']}"
            )

    summary["output_zip"] = output_zip
    summary["zip_sha256"] = sha256_file(output_zip)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--source-run", required=True)
    args = parser.parse_args()
    result = build(args.input, args.output, args.root, args.company, args.source_run)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
