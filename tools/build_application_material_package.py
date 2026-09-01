from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import posixpath
import zipfile
from pathlib import PurePosixPath
from typing import Iterable


USER_PREFIX = "01_사용자자료/"
INDEX_PREFIX = "00_자료목록/"
WEB_ENDPOINT_EXTENSIONS = {".do", ".jsp", ".action", ".cgi", ".php", ".aspx"}

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


def build(input_zip: str, output_zip: str, root_name: str, company: str, source_run: str) -> dict[str, object]:
    inventory: list[dict[str, object]] = []
    transform_log: list[dict[str, object]] = []
    taken: dict[str, str] = {}
    copied_files = 0
    copied_bytes = 0
    skipped = 0
    extension_renamed = 0
    extension_unresolved = 0

    with zipfile.ZipFile(input_zip, "r") as src, zipfile.ZipFile(
        output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
    ) as out:
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
            transform_log.append(
                {
                    "original_path": info.filename,
                    "mapped_path": final_rel,
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

        readme = (
            f"{company} 지원용 환경자료 패키지\n\n"
            "이 패키지는 검증 완료된 Human_Archive에서 시스템 원본(90_시스템원본)을 제외하고,\n"
            "지원서·면접·직무공부에 바로 사용할 자료만 재분류한 것입니다.\n\n"
            f"원본 workflow run: {source_run}\n\n"
            "검증 범위:\n"
            "- 실제 파일 다운로드 및 0바이트/형식/해시 검증\n"
            "- 사업장·연도·수집상태(DATA_FOUND/NO_MATCH/NOT_PUBLISHED 등) 검증\n"
            "- 보고서/정책/상세자료의 자동 본문 파싱 및 의미 추출\n"
            "- 완전 동일 파일 SHA-256 중복 제거\n"
            "- .do/.jsp/.action 등 웹 엔드포인트형 파일명은 실제 파일 시그니처를 확인해 확장자 교정\n\n"
            "주의:\n"
            "- 수백 개 PDF를 사람이 전 페이지 수동 정독한 것은 아닙니다.\n"
            "- 지원서에 사용할 핵심 내용의 선별·해석은 이 패키지를 기반으로 별도 수행합니다.\n"
            "- 공식 NOT_PUBLISHED로 확인된 연도는 파일을 가짜로 만들지 않고 미발간 상태로 기록합니다.\n"
            "- 00_자료목록/원본검증목록은 원래 검증 패키지의 목록이며, 새 경로 기준 목록은 지원용_전체자료목록.csv입니다.\n"
        )
        out.writestr(f"{root_name}/README_먼저보기.txt", readme.encode("utf-8"))

        inventory_bytes = write_csv(
            inventory, ["path", "bytes", "sha256", "source_archive_path"]
        )
        out.writestr(f"{root_name}/00_자료목록/지원용_전체자료목록.csv", inventory_bytes)

        transform_bytes = write_csv(
            transform_log, ["original_path", "mapped_path", "sha256", "bytes", "extension_action", "action"]
        )
        out.writestr(f"{root_name}/00_자료목록/지원용_패키지_변환기록.csv", transform_bytes)

        summary = {
            "schema_version": "application-material-package-1.1",
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
