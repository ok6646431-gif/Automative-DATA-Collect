"""Keep company-wide raw evidence outside the human-facing archive.

Collectors intentionally preserve broad/company-wide evidence under ``package_root/output``.
The Human Archive is a different product boundary: it contains only requested-scope,
human-readable material plus user-facing indexes/reference material.  Raw collector
HTML/JSON/attachments must therefore remain in the final orchestrated package/source
artifacts and must never be copied into ``Human_Archive.zip``.
"""

from __future__ import annotations

from pathlib import Path


LEGACY_SYSTEM_ROOT = "90_시스템원본"


def raw_preservation_stats(package_root: str | Path) -> dict[str, object]:
    """Describe the externally preserved collector tree without copying it."""
    root = Path(package_root).resolve()
    output = root / "output"
    files = [p for p in output.rglob("*") if p.is_file()] if output.exists() else []
    return {
        "policy": "EXTERNAL_TO_HUMAN_ARCHIVE",
        "package_raw_root": "output",
        "raw_files": len(files),
        "raw_bytes": sum(p.stat().st_size for p in files),
        "preserved_in_final_package": output.exists(),
        "human_archive_system_raw_root": "ABSENT",
    }


def suppress_system_raw_copy(package_root: str | Path, archive_root: str | Path) -> dict[str, object]:
    """Compatibility replacement for archive_builder.copy_system_raw.

    The caller used to duplicate the complete ``output`` tree under
    ``Human_Archive/90_시스템원본``.  Do not copy anything.  The authoritative raw
    evidence remains untouched at ``package_root/output`` and is uploaded separately
    with the final orchestrated/source artifacts.
    """
    return raw_preservation_stats(package_root)


def assert_human_archive_raw_separated(archive_root: str | Path) -> bool:
    """Fail closed if collector/system raw files leak into the Human Archive."""
    root = Path(archive_root)
    legacy = root / LEGACY_SYSTEM_ROOT
    leaked = [p for p in legacy.rglob("*") if p.is_file()] if legacy.exists() else []
    if leaked:
        sample = ", ".join(str(p.relative_to(root)) for p in leaked[:10])
        raise RuntimeError(
            "HUMAN_ARCHIVE_SYSTEM_RAW_LEAK: collector/system raw files must remain "
            f"outside Human_Archive.zip; leaked={len(leaked)}; sample={sample}"
        )
    if legacy.exists():
        # Empty compatibility directories add no value and make the product boundary
        # ambiguous. Remove the empty tree as well.
        for directory in sorted(
            [p for p in legacy.rglob("*") if p.is_dir()],
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            legacy.rmdir()
        except OSError:
            pass
    return True


def rewrite_human_archive_raw_references(archive_root: str | Path) -> int:
    """Update legacy README/notice wording after raw storage is externalized."""
    root = Path(archive_root)
    candidates = [root / "00_자료목록" / "README_먼저읽기.txt"]
    user = root / "01_사용자자료"
    if user.exists():
        candidates.extend(p for p in user.rglob("*.txt") if p.is_file())

    replacements = {
        "HTML/JSON/JSONL/실행로그 등 재현·개발용 원본은 90_시스템원본에 분리했습니다.":
            "HTML/JSON/JSONL/실행로그 등 재현·개발용 원본은 Human Archive에 포함하지 않으며, 최종 전체 패키지의 output 및 소스 artifact에 별도 보존합니다.",
        "원본 바이트는 90_시스템원본에 그대로 보존합니다.":
            "원본 바이트는 Human Archive 외부의 최종 전체 패키지 output에 그대로 보존합니다.",
        "원본 바이트는 수정하지 않았으며 시스템 원본 영역에 그대로 보존됩니다.":
            "원본 바이트는 수정하지 않았으며 Human Archive 외부의 최종 전체 패키지 output에 그대로 보존됩니다.",
        "90_시스템원본에서 원본 경로를 확인하십시오.":
            "최종 전체 패키지의 output에서 원본 경로를 확인하십시오.",
    }

    changed = 0
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        updated = text
        for before, after in replacements.items():
            updated = updated.replace(before, after)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    return changed
