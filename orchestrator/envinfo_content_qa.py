"""Lightweight content-fidelity QA for ENV-INFO human PDFs.

This is intentionally not OCR or a full visual-comparison system. It compares the
text disclosed inside the captured official inquiry sections with text extractable
from the reconstructed user PDF. The check is cheap enough to run on every archive
build and catches major content loss or fragmented rendering while the raw captured
HTML remains the provenance source.

Visual sampling remains a separate Golden Company regression because semantic text
coverage alone cannot prove every CSS/layout detail.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

PASS_THRESHOLD = 0.97
FAIL_THRESHOLD = 0.95

FIELDS = [
    "사업장", "연도", "원문_섹션수", "원문_고유토큰수", "PDF_페이지수",
    "PDF_고유토큰수", "원문토큰_보존율", "판정", "검사기준",
    "미확인토큰_예시", "원문HTML", "사용자PDF",
]


def _safe(value):
    text = re.sub(r'[\\/:*?"<>|\\x00-\\x1f]+', "_", str(value or "")).strip(" ._")
    return text[:160] or "자료"


def _norm_site(value):
    text = str(value or "")
    for pattern in [r"주식회사", r"\\(주\\)", r"㈜", r"사업장"]:
        text = re.sub(pattern, "", text, flags=re.I)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).casefold()


def _tokens(text):
    found = re.findall(
        r"[0-9A-Za-z가-힣]+(?:[._%/\\-][0-9A-Za-z가-힣]+)*",
        str(text or "").casefold(),
    )
    return {
        token
        for token in found
        if len(token) >= 2 or (token.isdigit() and len(token) >= 4)
    }


def compare_text(source_text, pdf_text):
    source_tokens = _tokens(source_text)
    pdf_tokens = _tokens(pdf_text)
    if not source_tokens:
        return {
            "source_tokens": 0,
            "pdf_tokens": len(pdf_tokens),
            "coverage": 1.0,
            "missing": [],
            "verdict": "WARN",
            "reason": "원문 공개항목에서 비교 가능한 토큰을 찾지 못함",
        }
    coverage = len(source_tokens & pdf_tokens) / len(source_tokens)
    missing = sorted(source_tokens - pdf_tokens)
    if coverage >= PASS_THRESHOLD:
        verdict = "PASS"
        reason = f"원문 고유토큰의 {coverage:.1%}가 사용자 PDF에서 확인됨"
    elif coverage >= FAIL_THRESHOLD:
        verdict = "WARN"
        reason = f"원문 고유토큰 보존율 {coverage:.1%}; 자동 차단 기준 이상이나 표본 확인 권장"
    else:
        verdict = "FAIL"
        reason = f"원문 고유토큰 보존율 {coverage:.1%}; {FAIL_THRESHOLD:.0%} 미만"
    return {
        "source_tokens": len(source_tokens),
        "pdf_tokens": len(pdf_tokens),
        "coverage": coverage,
        "missing": missing,
        "verdict": verdict,
        "reason": reason,
    }


def _source_text(path):
    from bs4 import BeautifulSoup

    html = Path(path).read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    sections = soup.select(".inquiry_cont")
    text = "\n".join(section.get_text(" ", strip=True) for section in sections)
    return text, len(sections)


def _pdf_text(path):
    from pypdf import PdfReader

    reader = PdfReader(str(path), strict=False)
    return "\n".join((page.extract_text() or "") for page in reader.pages), len(reader.pages)


def _write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def evaluate(package_root, archive_root, envinfo_scope, labels=None, site_tokens=None):
    """Evaluate scoped ENV-INFO reconstructions and write a human-readable QA table."""
    package_root = Path(package_root)
    archive_root = Path(archive_root)
    env = package_root / "output" / "ENVINFO"
    labels = labels or {}
    site_tokens = site_tokens or []
    scoped_ids = {str(x) for x in (envinfo_scope or set())}

    discovery = []
    disc = env / "discovery.csv"
    if disc.exists() and disc.stat().st_size:
        with disc.open(encoding="utf-8-sig", newline="") as f:
            discovery = list(csv.DictReader(f))

    rows = []
    expected = 0
    for item in discovery:
        comp = str(item.get("compId") or "")
        if comp not in scoped_ids:
            continue
        expected += 1
        year = str(item.get("year") or "연도미상")
        raw_name = str(item.get("compNm") or labels.get(("ENVINFO", comp), comp))
        raw_norm = _norm_site(raw_name)
        display = next(
            (
                name for name, token in site_tokens
                if token and (
                    token in raw_norm
                    or raw_norm in token
                    or _norm_site(name) in raw_norm
                    or raw_norm in _norm_site(name)
                )
            ),
            raw_name,
        )
        raw_matches = sorted((env / "raw_detail").glob(f"{year}_{_safe(comp)}_*.html"))
        pdf = (
            archive_root / "01_사용자자료" / "03_환경정보공개시스템" / _safe(display)
            / f"환경정보공개_{_safe(display)}_{year}_전체내용정적재현본.pdf"
        )

        base = {
            "사업장": display,
            "연도": year,
            "원문HTML": str(raw_matches[0].relative_to(package_root)) if raw_matches else "",
            "사용자PDF": str(pdf.relative_to(archive_root)) if pdf.exists() else "",
        }
        if not raw_matches or not pdf.exists():
            rows.append({
                **base,
                "원문_섹션수": 0,
                "원문_고유토큰수": 0,
                "PDF_페이지수": 0,
                "PDF_고유토큰수": 0,
                "원문토큰_보존율": "",
                "판정": "FAIL",
                "검사기준": "원문 HTML 또는 사용자 PDF 누락",
                "미확인토큰_예시": "",
            })
            continue

        try:
            source_text, sections = _source_text(raw_matches[0])
            pdf_text, pages = _pdf_text(pdf)
            result = compare_text(source_text, pdf_text)
            rows.append({
                **base,
                "원문_섹션수": sections,
                "원문_고유토큰수": result["source_tokens"],
                "PDF_페이지수": pages,
                "PDF_고유토큰수": result["pdf_tokens"],
                "원문토큰_보존율": round(result["coverage"], 4),
                "판정": result["verdict"],
                "검사기준": result["reason"],
                "미확인토큰_예시": ", ".join(result["missing"][:20]),
            })
        except Exception as exc:
            rows.append({
                **base,
                "원문_섹션수": "",
                "원문_고유토큰수": "",
                "PDF_페이지수": "",
                "PDF_고유토큰수": "",
                "원문토큰_보존율": "",
                "판정": "FAIL",
                "검사기준": f"Content QA 실행 오류: {type(exc).__name__}: {exc}",
                "미확인토큰_예시": "",
            })

    out = archive_root / "00_자료목록" / "ENVINFO_Content_QA.csv"
    _write_csv(out, rows)
    fail_count = sum(1 for row in rows if row.get("판정") == "FAIL")
    warn_count = sum(1 for row in rows if row.get("판정") == "WARN")
    pass_count = sum(1 for row in rows if row.get("판정") == "PASS")
    complete = len(rows) == expected
    return {
        "status": "PASS" if complete and fail_count == 0 else "FAIL",
        "pass": bool(complete and fail_count == 0),
        "expected_items": expected,
        "checked_items": len(rows),
        "pass_items": pass_count,
        "warn_items": warn_count,
        "fail_items": fail_count,
        "minimum_pass_coverage": PASS_THRESHOLD,
        "blocking_fail_coverage": FAIL_THRESHOLD,
        "qa_file": str(out.relative_to(archive_root)),
        "principle": (
            "원문 공개항목의 의미 있는 토큰이 사용자 PDF에도 보존되는지 전수 검사한다. "
            "95% 미만은 차단, 95~97%는 검토 권고, 97% 이상은 PASS로 표시한다. "
            "시각적 레이아웃 표본 검증은 Golden Company 회귀에서 별도로 수행한다."
        ),
    }
