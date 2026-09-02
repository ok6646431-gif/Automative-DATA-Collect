from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import posixpath
import re
import zipfile
from pathlib import PurePosixPath
from typing import Iterable
from xml.etree import ElementTree as ET

ENVINFO_PREFIX = "02_환경인허가_ENVINFO/"
WEB_ENDPOINT_EXTENSIONS = {".do", ".jsp", ".action", ".cgi", ".php", ".aspx"}
SOURCE_PREFIXES = {
    "ENVINFO": ENVINFO_PREFIX,
    "CLEANSYS_AIR": "03_대기/CleanSYS/",
    "SOOSIRO_WATER": "04_수질/SOOSIRO/",
    "PRTR": "05_화학물질/PRTR_배출이동량/",
    "CHEM_STATS": "05_화학물질/화학물질통계/",
}
TEXT_EXTENSIONS = {".csv", ".json", ".jsonl", ".txt", ".md", ".html", ".htm", ".xml"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _find_unique_suffix(z: zipfile.ZipFile, suffix: str) -> str:
    matches = [n for n in z.namelist() if not n.endswith("/") and n.endswith(suffix)]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {suffix}, found {len(matches)}")
    return matches[0]


def _root_name(z: zipfile.ZipFile) -> str:
    roots = {PurePosixPath(n).parts[0] for n in z.namelist() if n and not n.endswith("/")}
    if len(roots) != 1:
        raise RuntimeError(f"package must have exactly one root directory, found {sorted(roots)}")
    return next(iter(roots))


def _relative(root: str, name: str) -> str:
    prefix = root.rstrip("/") + "/"
    if not name.startswith(prefix):
        raise RuntimeError(f"member outside package root: {name}")
    return name[len(prefix):]


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def _xlsx_values(data: bytes) -> list[str]:
    """Extract searchable cell values from an XLSX with stdlib only."""
    chunks: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as xlsx:
            for name in xlsx.namelist():
                if not (
                    name == "xl/sharedStrings.xml"
                    or name.startswith("xl/worksheets/") and name.endswith(".xml")
                ):
                    continue
                try:
                    root = ET.fromstring(xlsx.read(name))
                except ET.ParseError:
                    continue
                for elem in root.iter():
                    local = elem.tag.rsplit("}", 1)[-1]
                    if local in {"t", "v"} and elem.text:
                        chunks.append(elem.text)
    except zipfile.BadZipFile:
        return []
    return chunks


def _json_values(value: object) -> list[str]:
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            result.append(str(key))
            result.extend(_json_values(item))
        return result
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_json_values(item))
        return result
    if value is None:
        return []
    return [str(value)]


def _searchable_values(path: str, data: bytes) -> list[str]:
    ext = posixpath.splitext(path)[1].lower()
    if ext == ".xlsx":
        return _xlsx_values(data)
    text = _decode_text(data) if ext in TEXT_EXTENSIONS else ""
    if not text:
        return []
    if ext == ".csv":
        return [cell for row in csv.reader(io.StringIO(text)) for cell in row]
    if ext in {".json", ".jsonl"}:
        try:
            if ext == ".json":
                return _json_values(json.loads(text))
            values: list[str] = []
            for line in text.splitlines():
                if line.strip():
                    values.extend(_json_values(json.loads(line)))
            return values
        except json.JSONDecodeError:
            pass
    return [line.strip() for line in text.splitlines() if line.strip()]


def _normalize_site(value: object) -> str:
    text = str(value or "").casefold().replace("㈜", "")
    text = re.sub(r"\(\s*주\s*\)", "", text)
    text = text.replace("주식회사", "")
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def _site_core(value: object) -> str:
    text = _normalize_site(value)
    for suffix in ("공장", "사업장"):
        if text.endswith(suffix):
            text = text[:-len(suffix)]
    return text


def _site_matches_target(site: str, targets: Iterable[str]) -> bool:
    candidate = _site_core(site)
    if not candidate:
        return False
    for target in targets:
        normalized = _site_core(target)
        if normalized and (normalized in candidate or candidate in normalized):
            return True
    return False


def _read_json(z: zipfile.ZipFile, suffix: str) -> dict:
    return json.loads(_decode_text(z.read(_find_unique_suffix(z, suffix))))


def _read_csv(z: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    text = _decode_text(z.read(_find_unique_suffix(z, suffix)))
    return list(csv.DictReader(io.StringIO(text)))


def _source_exclusions(scope: dict) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in scope.get("excluded_source_ids") or []:
        source_key = str(row.get("source_key") or "")
        if not source_key:
            continue
        grouped.setdefault(source_key, []).append(
            {
                "source_site_id": str(row.get("source_site_id") or ""),
                "source_site_name_raw": str(row.get("source_site_name_raw") or ""),
                "reason": str(row.get("reason") or ""),
            }
        )
    return grouped


def validate_package(path: str, expected_company: str | None = None) -> dict[str, object]:
    checks: list[str] = []
    with zipfile.ZipFile(path, "r") as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity failure: {bad}")
        checks.append("ZIP_INTEGRITY")

        root = _root_name(z)
        physical_names = [n for n in z.namelist() if not n.endswith("/")]
        relative_names = [_relative(root, n) for n in physical_names]

        if any("90_시스템원본" in n for n in relative_names):
            raise RuntimeError("system-original folder leaked into support package")
        checks.append("NO_SYSTEM_ORIGINALS")

        summary = _read_json(z, "/00_자료목록/지원용_패키지_요약.json")
        scope = _read_json(z, "/00_자료목록/원본검증목록/Requested_Scope.json")
        archive_manifest = _read_json(z, "/00_자료목록/원본검증목록/Archive_Manifest.json")

        if expected_company and str(summary.get("company")) != expected_company:
            raise RuntimeError(
                f"company mismatch: expected={expected_company!r} summary={summary.get('company')!r}"
            )
        checks.append("COMPANY_IDENTITY")

        if summary.get("system_originals_included") is not False:
            raise RuntimeError("summary does not declare system_originals_included=false")
        if int(summary.get("web_endpoint_extensions_unresolved", 0)) != 0:
            raise RuntimeError(
                "unresolved web-endpoint extensions remain: "
                f"{summary.get('web_endpoint_extensions_unresolved')}"
            )
        leaked_endpoint_names = [
            p for p in relative_names if posixpath.splitext(p)[1].lower() in WEB_ENDPOINT_EXTENSIONS
        ]
        if leaked_endpoint_names:
            raise RuntimeError(f"web endpoint extension leaked into package: {leaked_endpoint_names[:5]}")
        checks.append("USER_FACING_EXTENSIONS")

        disclosure = int(summary.get("envinfo_disclosure_records", 0))
        references = int(summary.get("envinfo_attachment_references", 0))
        source_paths = int(summary.get("envinfo_source_attachment_paths", 0))
        unique_attachments = int(summary.get("envinfo_unique_attachments", 0))
        duplicate_refs = int(summary.get("envinfo_duplicate_attachment_references", 0))
        source_duplicate_refs = int(summary.get("envinfo_source_duplicate_attachment_references", 0))
        physical = int(summary.get("envinfo_physical_files", 0))
        site_count = int(summary.get("envinfo_site_count", 0))

        if physical != disclosure + unique_attachments:
            raise RuntimeError(
                "ENVINFO count identity failed: physical != disclosure + unique attachments "
                f"({physical} != {disclosure} + {unique_attachments})"
            )
        if references != unique_attachments + duplicate_refs:
            raise RuntimeError(
                "ENVINFO count identity failed: references != unique attachments + duplicate refs "
                f"({references} != {unique_attachments} + {duplicate_refs})"
            )
        if references != source_paths + source_duplicate_refs:
            raise RuntimeError(
                "ENVINFO count identity failed: references != source paths + source duplicate refs "
                f"({references} != {source_paths} + {source_duplicate_refs})"
            )
        checks.append("ENVINFO_COUNT_IDENTITIES")

        count_rows = _read_csv(z, "/00_자료목록/ENVINFO_자료수_설명.csv")
        count_map = {row["항목"]: int(row["값"]) for row in count_rows}
        expected_counts = {
            "환경정보_공개레코드": disclosure,
            "환경정보_첨부관계": references,
            "환경정보_고유첨부파일": unique_attachments,
            "환경정보_중복첨부참조": duplicate_refs,
            "환경정보_물리파일": physical,
            "환경정보_사업장": site_count,
        }
        mismatches = {
            key: (count_map.get(key), value)
            for key, value in expected_counts.items()
            if count_map.get(key) != value
        }
        if mismatches:
            raise RuntimeError(f"ENVINFO count CSV disagrees with summary: {mismatches}")
        checks.append("ENVINFO_COUNT_CSV")

        envinfo_members = [p for p in relative_names if p.startswith(ENVINFO_PREFIX)]
        if len(envinfo_members) != physical:
            raise RuntimeError(
                f"ENVINFO physical member mismatch: archive={len(envinfo_members)} summary={physical}"
            )
        attachment_members = [p for p in envinfo_members if "/첨부자료/" in p]
        record_members = [p for p in envinfo_members if "/첨부자료/" not in p]
        if len(attachment_members) != unique_attachments or len(record_members) != disclosure:
            raise RuntimeError(
                "ENVINFO member classes disagree with summary: "
                f"records={len(record_members)}/{disclosure}, attachments={len(attachment_members)}/{unique_attachments}"
            )

        attachment_hashes: dict[str, str] = {}
        physical_sha_to_path: dict[str, str] = {}
        for rel in attachment_members:
            data = z.read(f"{root}/{rel}")
            digest = sha256_bytes(data)
            if digest in physical_sha_to_path:
                raise RuntimeError(
                    "duplicate ENVINFO physical attachment bytes remain: "
                    f"{physical_sha_to_path[digest]} and {rel}"
                )
            physical_sha_to_path[digest] = rel
            attachment_hashes[rel] = digest
        checks.append("ENVINFO_PHYSICAL_SHA_UNIQUE")

        ref_rows = _read_csv(z, "/00_자료목록/ENVINFO_첨부자료_참조목록.csv")
        if len(ref_rows) != references:
            raise RuntimeError(
                f"ENVINFO reference row mismatch: csv={len(ref_rows)} summary={references}"
            )
        logical_seen: set[str] = set()
        for row in ref_rows:
            logical = row.get("logical_path", "")
            stored = row.get("stored_path", "")
            digest = row.get("sha256", "")
            if not logical or logical in logical_seen:
                raise RuntimeError(f"duplicate or empty ENVINFO logical path: {logical!r}")
            logical_seen.add(logical)
            if stored not in attachment_hashes:
                raise RuntimeError(f"ENVINFO reference points to missing attachment: {stored}")
            if attachment_hashes[stored] != digest:
                raise RuntimeError(
                    f"ENVINFO reference digest mismatch: stored={stored} csv={digest} actual={attachment_hashes[stored]}"
                )
        checks.append("ENVINFO_REFERENCE_INTEGRITY")

        sites = sorted({PurePosixPath(p).parts[1] for p in envinfo_members if len(PurePosixPath(p).parts) > 1})
        if len(sites) != site_count:
            raise RuntimeError(f"ENVINFO site count mismatch: archive={len(sites)} summary={site_count}")
        target_site_tokens = [str(x) for x in archive_manifest.get("target_site_tokens") or [] if str(x)]
        if target_site_tokens:
            outside = [site for site in sites if not _site_matches_target(site, target_site_tokens)]
            if outside:
                raise RuntimeError(
                    "ENVINFO site outside requested target_site_tokens: "
                    f"outside={outside} targets={target_site_tokens}"
                )
        checks.append("ENVINFO_SITE_SCOPE")

        exclusions = _source_exclusions(scope)
        exclusion_hits: list[dict[str, str]] = []
        for source_key, prefix in SOURCE_PREFIXES.items():
            source_exclusions = exclusions.get(source_key, [])
            if not source_exclusions:
                continue
            source_members = [p for p in relative_names if p.startswith(prefix)]
            for rel in source_members:
                data = z.read(f"{root}/{rel}")
                values = _searchable_values(rel, data)
                normalized_values = {_normalize_site(value) for value in values if value}
                normalized_path = _normalize_site(rel)
                for excluded in source_exclusions:
                    source_id = excluded["source_site_id"]
                    source_name = excluded["source_site_name_raw"]
                    reliable_id = bool(source_id and (not source_id.isdigit() or len(source_id) >= 10))
                    id_hit = bool(reliable_id and any(value.strip() == source_id for value in values))
                    name_norm = _normalize_site(source_name)
                    name_hit = bool(
                        name_norm
                        and (name_norm in normalized_values or name_norm in normalized_path)
                    )
                    if id_hit or name_hit:
                        exclusion_hits.append(
                            {
                                "source_key": source_key,
                                "member": rel,
                                "source_site_id": source_id,
                                "source_site_name_raw": source_name,
                                "matched_by": "SOURCE_ID" if id_hit else "SOURCE_NAME",
                            }
                        )
        if exclusion_hits:
            raise RuntimeError(
                "verified excluded source entity leaked into support package: "
                + json.dumps(exclusion_hits[:10], ensure_ascii=False)
            )
        checks.append("VERIFIED_EXCLUSION_RECHECK")

        target_ids = scope.get("target_source_ids") or {}
        declared_sources = sorted(k for k, v in target_ids.items() if isinstance(v, list))
        checks.append("REQUESTED_SCOPE_METADATA_PRESENT")

        return {
            "schema_version": "application-material-package-validation-1.0",
            "status": "PASS",
            "package": path,
            "root_name": root,
            "company": summary.get("company"),
            "requested_scope_label": scope.get("label"),
            "declared_sources": declared_sources,
            "excluded_source_entities_declared": sum(len(v) for v in exclusions.values()),
            "excluded_source_entity_hits": 0,
            "envinfo_disclosure_records": disclosure,
            "envinfo_attachment_references": references,
            "envinfo_unique_attachments": unique_attachments,
            "envinfo_duplicate_attachment_references": duplicate_refs,
            "envinfo_physical_files": physical,
            "envinfo_site_count": site_count,
            "checks": checks,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--company")
    args = parser.parse_args()
    result = validate_package(args.input, args.company)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
