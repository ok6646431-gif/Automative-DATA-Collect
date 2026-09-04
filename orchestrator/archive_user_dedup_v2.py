"""Canonicalize ENV-INFO user attachments before final archive ZIP deduplication.

The collector may expose the same attachment in several site/year disclosure rows and
promote the same bytes into sustainability/policy folders.  The human archive should
not physically carry every exact copy.  This stage keeps one byte-identical canonical
copy, records every original user-facing occurrence in an XLSX reference table, then
runs the existing system-vs-user ZIP deduplication.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import archive_zip_dedup as core

try:
    import xlsxwriter
except Exception:
    xlsxwriter = None

USER_ROOT = "01_사용자자료"
ENVINFO_ROOT = "03_환경정보공개시스템"
CENTRAL_FOLDER = "첨부자료_원문"
REFERENCE_XLSX = "ENVINFO_첨부자료_참조표.xlsx"


def _rel(path: Path, archive_root: Path) -> str:
    return path.relative_to(archive_root).as_posix()


def _is_envinfo_attachment_path(rel: str) -> bool:
    parts = Path(rel).parts
    return (
        len(parts) >= 5
        and parts[0] == USER_ROOT
        and parts[1] == ENVINFO_ROOT
        and parts[3] == "첨부자료"
    )


def _is_envinfo_generated_copy(rel: str) -> bool:
    p = Path(rel)
    return (
        rel.startswith(f"{USER_ROOT}/{ENVINFO_ROOT}/{CENTRAL_FOLDER}/")
        or "ENVINFO_공개근거" in p.parts
        or p.name.startswith("ENVINFO공개연도_")
    )


def _canonical_rank(rel: str):
    """Prefer canonical company-document locations over generated ENV-INFO copies."""
    if rel.startswith(f"{USER_ROOT}/04_지속가능경영보고서/"):
        return (0, len(rel), rel)
    if rel.startswith(f"{USER_ROOT}/06_회사환경정책/") and "ENVINFO_공개근거" not in Path(rel).parts:
        return (1, len(rel), rel)
    if rel.startswith(f"{USER_ROOT}/05_사업보고서_공시/"):
        return (2, len(rel), rel)
    if rel.startswith(f"{USER_ROOT}/{ENVINFO_ROOT}/{CENTRAL_FOLDER}/"):
        return (3, len(rel), rel)
    if _is_envinfo_generated_copy(rel):
        return (8, len(rel), rel)
    return (4, len(rel), rel)


def _neutral_attachment_name(path: Path, digest: str) -> str:
    name = re.sub(r"^(?:19|20)\d{2}_", "", path.name)
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", name).strip(" ._") or path.name
    return f"{digest[:12]}_{name}"


def _source_context(rel: str) -> tuple[str, str]:
    parts = Path(rel).parts
    site = parts[2] if len(parts) >= 5 and parts[0] == USER_ROOT and parts[1] == ENVINFO_ROOT else ""
    match = re.match(r"((?:19|20)\d{2})_", Path(rel).name)
    return site, match.group(1) if match else ""


def _write_reference_xlsx(path: Path, rows: list[dict]) -> None:
    if xlsxwriter is None:
        raise RuntimeError("xlsxwriter is required for ENV-INFO attachment reference export")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(str(path), {"constant_memory": True})
    ws = wb.add_worksheet("ENVINFO 첨부자료")
    header = wb.add_format({"bold": True, "bg_color": "#E7E6E6", "border": 1, "align": "center", "valign": "vcenter"})
    text = wb.add_format({"valign": "top", "text_wrap": True})
    fields = ["사업장", "공개연도", "원래_사용자경로", "최종_보존경로", "파일명", "용량_bytes", "SHA256", "처리"]
    for c, field in enumerate(fields):
        ws.write(0, c, field, header)
    for r_idx, row in enumerate(rows, 1):
        for c, field in enumerate(fields):
            ws.write(r_idx, c, row.get(field, ""), text)
    ws.freeze_panes(1, 0)
    ws.autofilter(0, 0, max(1, len(rows)), len(fields) - 1)
    widths = [24, 12, 78, 78, 52, 16, 68, 34]
    for c, width in enumerate(widths):
        ws.set_column(c, c, width)
    wb.close()


def _remove_empty_dirs(root: Path) -> None:
    for d in sorted([p for p in root.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass


def canonicalize_user_envinfo(archive_root: str | Path) -> dict:
    archive_root = Path(archive_root)
    user = archive_root / USER_ROOT
    if not user.exists():
        return {
            "envinfo_attachment_occurrences": 0,
            "envinfo_attachment_unique_files": 0,
            "envinfo_attachment_duplicate_files_removed": 0,
            "envinfo_attachment_duplicate_bytes_saved": 0,
            "envinfo_generated_crossfolder_files_removed": 0,
            "envinfo_generated_crossfolder_bytes_saved": 0,
            "envinfo_attachment_reference_file": "",
        }

    attachment_files = [
        p for p in sorted(user.rglob("*"))
        if p.is_file() and _is_envinfo_attachment_path(_rel(p, archive_root))
    ]
    by_hash: dict[str, list[Path]] = {}
    for p in attachment_files:
        by_hash.setdefault(core.sha256(p), []).append(p)

    central = user / ENVINFO_ROOT / CENTRAL_FOLDER
    central.mkdir(parents=True, exist_ok=True)
    refs: list[dict] = []
    duplicate_files = 0
    duplicate_bytes = 0

    for digest, group in sorted(by_hash.items()):
        group = sorted(group)
        source = group[0]
        target = central / _neutral_attachment_name(source, digest)
        if target.exists():
            if core.sha256(target) != digest:
                raise RuntimeError(f"ENVINFO canonical target collision: {target}")
        else:
            shutil.move(str(source), str(target))

        for original in group:
            rel_original = _rel(original, archive_root)
            site, year = _source_context(rel_original)
            size = target.stat().st_size if original == source else original.stat().st_size
            refs.append({
                "사업장": site,
                "공개연도": year,
                "원래_사용자경로": rel_original,
                "최종_보존경로": _rel(target, archive_root),
                "파일명": original.name,
                "용량_bytes": size,
                "SHA256": digest,
                "처리": "CONTENT_HASH_CANONICALIZED" if original == source else "IDENTICAL_SHA256_DUPLICATE",
            })
            if original != source and original.exists():
                duplicate_files += 1
                duplicate_bytes += original.stat().st_size
                original.unlink()

    _remove_empty_dirs(user / ENVINFO_ROOT)

    # Remove exact generated ENV-INFO copies that are also present in a more canonical
    # company-document location.  Never deduplicate arbitrary corporate documents;
    # at least one member of the hash group must be an ENV-INFO generated copy.
    all_user_files = [p for p in sorted(user.rglob("*")) if p.is_file()]
    global_hash: dict[str, list[Path]] = {}
    for p in all_user_files:
        global_hash.setdefault(core.sha256(p), []).append(p)

    cross_files = 0
    cross_bytes = 0
    path_redirects: dict[str, str] = {}
    for digest, group in sorted(global_hash.items()):
        if len(group) < 2:
            continue
        rels = [_rel(p, archive_root) for p in group]
        if not any(_is_envinfo_generated_copy(rel) for rel in rels):
            continue
        retained = min(group, key=lambda p: _canonical_rank(_rel(p, archive_root)))
        retained_rel = _rel(retained, archive_root)
        for p in sorted(group):
            if p == retained:
                continue
            rel_p = _rel(p, archive_root)
            if not _is_envinfo_generated_copy(rel_p):
                continue
            path_redirects[rel_p] = retained_rel
            size = p.stat().st_size
            refs.append({
                "사업장": "",
                "공개연도": "",
                "원래_사용자경로": rel_p,
                "최종_보존경로": retained_rel,
                "파일명": p.name,
                "용량_bytes": size,
                "SHA256": digest,
                "처리": "IDENTICAL_SHA256_CANONICAL_DOCUMENT",
            })
            p.unlink()
            cross_files += 1
            cross_bytes += size

    if path_redirects:
        for row in refs:
            current = row["최종_보존경로"]
            seen = set()
            while current in path_redirects and current not in seen:
                seen.add(current)
                current = path_redirects[current]
            row["최종_보존경로"] = current

    _remove_empty_dirs(user)
    refs.sort(key=lambda r: (str(r["사업장"]), str(r["공개연도"]), str(r["원래_사용자경로"])))
    ref_path = archive_root / "00_자료목록" / REFERENCE_XLSX
    if refs:
        _write_reference_xlsx(ref_path, refs)

    readme = archive_root / "00_자료목록" / "README_먼저읽기.txt"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        note = (
            "\n6) ENV-INFO 첨부 원문은 내용 SHA-256 기준으로 1회만 보존합니다. "
            f"사업장/연도별 원래 위치와 최종 보존경로는 {REFERENCE_XLSX}에서 확인하십시오.\n"
        )
        if REFERENCE_XLSX not in text:
            readme.write_text(text.rstrip() + note, encoding="utf-8")

    stats = {
        "envinfo_attachment_occurrences": len(attachment_files),
        "envinfo_attachment_unique_files": len(by_hash),
        "envinfo_attachment_duplicate_files_removed": duplicate_files,
        "envinfo_attachment_duplicate_bytes_saved": duplicate_bytes,
        "envinfo_generated_crossfolder_files_removed": cross_files,
        "envinfo_generated_crossfolder_bytes_saved": cross_bytes,
        "envinfo_attachment_reference_file": str(ref_path.relative_to(archive_root)) if refs else "",
    }

    idx_manifest = archive_root / "00_자료목록" / "Archive_Manifest.json"
    if idx_manifest.exists():
        data = core.read_json(idx_manifest, {}) or {}
        data["envinfo_user_attachment_dedup"] = stats
        idx_manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def _persist_pre_stats(package_root: Path, archive_root: Path, stats: dict) -> None:
    summary_path = package_root / "Archive_Summary.json"
    summary = core.read_json(summary_path, {}) or {}
    summary["envinfo_user_attachment_dedup"] = stats
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = package_root / "Master_Manifest.json"
    manifest = core.read_json(manifest_path, {}) or {}
    manifest.setdefault("human_archive", {})["envinfo_user_attachment_dedup"] = stats
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    idx = archive_root / "00_자료목록"
    if (idx / "Master_Manifest.json").exists():
        shutil.copy2(manifest_path, idx / "Master_Manifest.json")
    system_manifest = archive_root / "90_시스템원본" / "control_plane" / "Master_Manifest.json"
    if system_manifest.parent.exists():
        shutil.copy2(manifest_path, system_manifest)


def run(package_root: str | Path = "assembled") -> dict:
    package_root = Path(package_root).resolve()
    zip_path = package_root / "Human_Archive.zip"
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)
    original_zip_bytes = zip_path.stat().st_size

    with tempfile.TemporaryDirectory(prefix="human-archive-user-dedup-") as td:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad:
                raise RuntimeError(f"ZIP integrity failure before user dedup: {bad}")
            zf.extractall(td)
        archive_root = core._find_archive_root(td)
        stats = canonicalize_user_envinfo(archive_root)
        core.refresh_user_indexes(archive_root)
        _persist_pre_stats(package_root, archive_root, stats)
        core._rewrite_zip(zip_path, archive_root)

    core_result = core.run(package_root)
    final_bytes = zip_path.stat().st_size
    result = {
        **core_result,
        **stats,
        "zip_bytes_before_user_dedup": original_zip_bytes,
        "zip_bytes_after_all_dedup": final_bytes,
        "zip_bytes_saved_total": original_zip_bytes - final_bytes,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", default="assembled")
    args = ap.parse_args()
    run(args.package)
