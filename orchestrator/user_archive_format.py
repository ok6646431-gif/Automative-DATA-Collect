"""Normalize the human-facing archive to readable document formats.

Raw collector HTML/JSON remains in 90_시스템원본. The user layer should expose
source tables as XLS/XLSX and source pages as PDF, not implementation artifacts.
"""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

import archive_builder


MACHINE_REVIEW_SUFFIXES = {".html", ".json", ".jsonl", ".md"}
PROHIBITED_USER_SUFFIXES = {".html", ".json", ".jsonl"}


def _safe_title(value: str) -> str:
    return archive_builder.safe(value)[:100]


def _static_html_for_pdf(src: Path) -> tuple[str, str]:
    soup = BeautifulSoup(src.read_text(encoding="utf-8", errors="replace"), "html.parser")
    wrapper = soup.select_one("div.wrapper.ESG") or soup.select_one("main") or soup.body
    if wrapper is None:
        raise RuntimeError(f"no renderable body in corporate HTML: {src}")
    for tag in wrapper.select("script,style,noscript,iframe,video,source,img,header,footer,nav"):
        tag.decompose()
    title_tag = wrapper.find(["h2", "h3", "h1"])
    title = title_tag.get_text(" ", strip=True) if title_tag else src.stem
    html = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>
@page {{ size:A4; margin:18mm 16mm; }}
body {{ font-family:"Noto Sans CJK KR","NanumGothic",sans-serif; color:#111; font-size:10.5pt; line-height:1.65; }}
h1,h2,h3,h4 {{ break-after:avoid; line-height:1.3; margin-top:1.2em; }}
h2,h3 {{ font-size:18pt; }} h4 {{ font-size:13pt; }}
ul,ol {{ padding-left:1.4em; }} li {{ margin:.2em 0; }}
table {{ border-collapse:collapse; width:100%; margin:1em 0; font-size:9pt; }}
th,td {{ border:1px solid #bbb; padding:5px; vertical-align:top; }} th {{ font-weight:700; }}
a {{ color:#111; text-decoration:none; }}
.btn,.tab,.tabs,.breadcrumb,.location,.share,.paging,.swiper-button-next,.swiper-button-prev {{ display:none !important; }}
</style></head><body>{str(wrapper)}</body></html>'''
    return title, html


def _unique_pdf_path(directory: Path, stem: str) -> Path:
    target = directory / f"{stem}.pdf"
    if not target.exists():
        return target
    n = 2
    while True:
        candidate = directory / f"{stem}__{n}.pdf"
        if not candidate.exists():
            return candidate
        n += 1


def _render_corporate_html(user_root: Path) -> int:
    folder = user_root / "06_회사환경정책" / "기타_공식자료"
    if not folder.exists():
        return 0
    converted = 0
    for src in sorted(folder.glob("*.html")):
        title, static_html = _static_html_for_pdf(src)
        year_match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", src.name)
        prefix = f"{year_match.group(1)}_" if year_match else ""
        target = _unique_pdf_path(folder, prefix + _safe_title(title))
        temp = folder / f".{src.stem}.user-print.html"
        temp.write_text(static_html, encoding="utf-8")
        try:
            ok, error = archive_builder.render_html_pdf(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        if not ok:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"corporate HTML -> PDF failed for {src.name}: {error}")
        src.unlink()
        converted += 1
    return converted


def _remove_review_machine_variants(user_root: Path) -> int:
    folder = user_root / "00_환경관리검토"
    if not folder.exists():
        return 0
    removed = 0
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() in MACHINE_REVIEW_SUFFIXES:
            p.unlink()
            removed += 1
    return removed


def _refresh_user_indexes(archive_root: Path) -> int:
    user = archive_root / archive_builder.USER_ROOT
    idx = archive_root / "00_자료목록"
    rows = []
    for p in sorted(user.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(archive_root)
        rows.append({
            "구분": rel.parts[1] if len(rel.parts) > 1 else "",
            "파일명": p.name,
            "상대경로": str(rel),
            "용량_MB": round(p.stat().st_size / 1024 / 1024, 3),
        })
    archive_builder.write_csv(idx / "사용자자료_목록.csv", rows, ["구분", "파일명", "상대경로", "용량_MB"])
    archive_builder.dict_rows_to_xlsx(idx / "전체자료목록.xlsx", [("사용자자료", rows)])
    return len(rows)


def normalize_user_archive(archive_root: str | Path) -> dict[str, int]:
    root = Path(archive_root)
    user = root / archive_builder.USER_ROOT
    converted = _render_corporate_html(user)
    removed = _remove_review_machine_variants(user)

    leaked = [str(p.relative_to(root)) for p in user.rglob("*") if p.is_file() and p.suffix.lower() in PROHIBITED_USER_SUFFIXES]
    if leaked:
        raise RuntimeError("machine-readable implementation artifacts leaked into user layer: " + ", ".join(leaked[:10]))

    user_files = _refresh_user_indexes(root)
    return {
        "corporate_html_rendered_to_pdf": converted,
        "review_machine_variants_removed": removed,
        "user_files": user_files,
    }
