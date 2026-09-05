"""Create chat/download-sized delivery ZIPs from a validated Human Archive.

The output is a byte-preserving subset of the already validated archive, never a
second ad-hoc packaging implementation. Every delivered member is verified against
its source member and the manifest records source and part SHA-256 values.

Delivery contains three human-facing areas from the validated source archive:
- 00_자료목록 human-readable indexes
- 01_사용자자료 company/public environmental evidence
- 02_BAT_참고자료 separately packaged BAT reference material

90_시스템원본 remains excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator"))

from archive_acceptance import assert_pass, validate_archive_zip  # noqa: E402

HUMAN_INDEX_SUFFIXES = {".xlsx", ".xls", ".csv", ".txt", ".pdf"}
HUMAN_DELIVERY_ROOTS = ("01_사용자자료/", "02_BAT_참고자료/")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _select_members(zf: zipfile.ZipFile, archive_root: str) -> list[zipfile.ZipInfo]:
    selected = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        rel = Path(info.filename).relative_to(archive_root).as_posix()
        if rel.startswith(HUMAN_DELIVERY_ROOTS):
            selected.append(info)
        elif rel.startswith("00_자료목록/") and Path(rel).suffix.lower() in HUMAN_INDEX_SUFFIXES:
            selected.append(info)
    return sorted(selected, key=lambda x: x.filename)


def _plan_parts(infos: list[zipfile.ZipInfo], max_bytes: int) -> list[list[zipfile.ZipInfo]]:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    parts: list[list[zipfile.ZipInfo]] = []
    current: list[zipfile.ZipInfo] = []
    estimated = 0
    for info in infos:
        size = max(1, info.compress_size)
        if current and estimated + size > max_bytes:
            parts.append(current)
            current = []
            estimated = 0
        current.append(info)
        estimated += size
    if current:
        parts.append(current)
    return parts


def prepare(source_zip: Path, out_dir: Path, prefix: str, max_bytes: int) -> dict:
    acceptance = assert_pass(validate_archive_zip(source_zip), "source Human Archive ZIP")
    source_sha = sha256_file(source_zip)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{prefix}_part_*.zip"):
        old.unlink()

    with zipfile.ZipFile(source_zip, "r") as src:
        roots = {Path(i.filename).parts[0] for i in src.infolist() if not i.is_dir() and Path(i.filename).parts}
        if len(roots) != 1:
            raise RuntimeError(f"source archive has invalid root set: {sorted(roots)}")
        archive_root = next(iter(roots))
        selected = _select_members(src, archive_root)
        if not selected:
            raise RuntimeError("no human-delivery members found")
        source_digests = {info.filename: sha256_bytes(src.read(info)) for info in selected}
        plans = _plan_parts(selected, max_bytes)

        part_rows = []
        delivered = set()
        for idx, infos in enumerate(plans, 1):
            part = out_dir / f"{prefix}_part_{idx:02d}.zip"
            with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as dst:
                for info in infos:
                    dst.writestr(info.filename, src.read(info))
            if part.stat().st_size > max_bytes:
                raise RuntimeError(f"delivery part exceeds max_bytes after compression: {part.name} {part.stat().st_size}>{max_bytes}")

            with zipfile.ZipFile(part, "r") as check:
                if check.testzip() is not None:
                    raise RuntimeError(f"delivery ZIP integrity failed: {part.name}")
                actual_names = [i.filename for i in check.infolist() if not i.is_dir()]
                expected_names = [i.filename for i in infos]
                if actual_names != expected_names:
                    raise RuntimeError(f"delivery member list drifted in {part.name}")
                for name in actual_names:
                    if sha256_bytes(check.read(name)) != source_digests[name]:
                        raise RuntimeError(f"delivery member bytes drifted: {part.name}:{name}")
                    delivered.add(name)

            part_rows.append({
                "name": part.name,
                "bytes": part.stat().st_size,
                "sha256": sha256_file(part),
                "member_count": len(infos),
                "members": [
                    {"path": info.filename, "sha256": source_digests[info.filename], "bytes": info.file_size}
                    for info in infos
                ],
            })

    expected = set(source_digests)
    if delivered != expected:
        missing = sorted(expected - delivered)
        extra = sorted(delivered - expected)
        raise RuntimeError(f"delivery union mismatch; missing={missing[:10]}; extra={extra[:10]}")

    bat_members = sorted(name for name in expected if "/02_BAT_참고자료/" in name)
    manifest = {
        "schema_version": "human-archive-delivery-1.1",
        "status": "PASS",
        "policy": "BYTE_PRESERVING_VALIDATED_SUBSET",
        "source_archive": source_zip.name,
        "source_archive_sha256": source_sha,
        "source_archive_acceptance": acceptance,
        "selection": "01_사용자자료 + 02_BAT_참고자료 + human-readable 00_자료목록 files",
        "selected_member_count": len(expected),
        "bat_reference_member_count": len(bat_members),
        "bat_reference_members": bat_members,
        "parts": part_rows,
    }
    (out_dir / "Delivery_Manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--prefix", default="환경자료")
    ap.add_argument("--max-mib", type=int, default=450)
    args = ap.parse_args()
    manifest = prepare(args.source, args.out_dir, args.prefix, args.max_mib * 1024 * 1024)
    print(json.dumps({
        "status": manifest["status"],
        "parts": len(manifest["parts"]),
        "source_sha256": manifest["source_archive_sha256"],
        "bat_reference_members": manifest["bat_reference_member_count"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
