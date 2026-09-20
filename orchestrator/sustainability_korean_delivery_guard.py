"""Acceptance check for the actual user-facing annual-report PDFs.

Discovery labels and filenames are hints only.  This gate reads the materialized
PDF bytes after archive construction and before the accepted ZIP is written.
Ambiguous/scanned reports must be reviewed rather than counted as Korean originals.
"""
from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path


def _annual_source_rows(package_root):
    p = Path(package_root) / 'output' / 'CORP_DOCS' / 'document_index.csv'
    if not p.is_file():
        return []
    with p.open(encoding='utf-8-sig', newline='') as f:
        return [r for r in csv.DictReader(f)
                if r.get('document_type') == 'SUSTAINABILITY_REPORT'
                and r.get('collection_status') == 'DOWNLOADED']


def _year(text):
    m = re.search(r'(?<!\d)(?:19|20)\d{2}(?!\d)', str(text or ''))
    return int(m.group()) if m else None


def _inspect_pdf(path):
    from pypdf import PdfReader
    pdf = PdfReader(str(path), strict=False)
    if not pdf.pages:
        raise ValueError('annual report has no pages')
    # Inspect every page: a Korean cover cannot make an English full report pass.
    hangul = latin = korean_pages = meaningful_pages = 0
    first_six_hangul = 0
    for n, page in enumerate(pdf.pages):
        text = page.extract_text() or ''
        ko = len(re.findall('[가-힣]', text))
        en = len(re.findall('[A-Za-z]', text))
        hangul += ko; latin += en
        if n < 6:
            first_six_hangul += ko
        if ko + en >= 80:
            meaningful_pages += 1
            korean_pages += int(ko >= 30)
    # Treat non-extractable scanned content as unverified, not as English.
    if first_six_hangul < 100 or hangul < 400 or meaningful_pages == 0:
        raise ValueError('Korean text cannot be verified throughout annual report')
    if korean_pages / meaningful_pages < 0.30 or hangul * 2 < latin:
        raise ValueError('annual report is not verifiably Korean-primary')
    return {'pages': len(pdf.pages), 'hangul_chars': hangul,
            'latin_chars': latin, 'meaningful_pages': meaningful_pages,
            'korean_pages': korean_pages}


def evaluate(package_root, archive_root):
    """Return evidence and PASS only for independently examined Korean archive PDFs.

    Source-derived document index and the user archive are cross-checked by year and
    SHA.  Missing source rows when the archive claims a report are not accepted.
    """
    package_root = Path(package_root)
    archive_root = Path(archive_root)
    sources = _annual_source_rows(package_root)
    folders = [x for x in archive_root.rglob('04_지속가능경영보고서') if x.is_dir()]
    files = sorted(p for d in folders for p in d.rglob('*.pdf') if p.is_file())
    if not sources and not files:
        return {'status': 'NOT_APPLICABLE', 'pass': True, 'checked': 0, 'items': [],
                'principle': 'No annual report is asserted; discovery/coverage checks remain independent.'}
    source_by_year = {}
    for row in sources:
        year = _year(row.get('report_year'))
        digest = str(row.get('sha256') or '').lower()
        if year and re.fullmatch(r'[0-9a-f]{64}', digest):
            source_by_year.setdefault(year, set()).add(digest)
    items = []
    failures = []
    seen_years = set()
    for path in files:
        year = _year(path.name)
        item = {'path': str(path.relative_to(archive_root)), 'report_year': year,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        try:
            if year is None:
                raise ValueError('report year missing from delivered filename')
            if year in seen_years:
                raise ValueError('multiple annual report PDFs for one year: review required')
            seen_years.add(year)
            if item['sha256'] not in source_by_year.get(year, set()):
                raise ValueError('delivered report does not match a downloaded annual-report source SHA for this year')
            item.update(_inspect_pdf(path))
            item['status'] = 'PASS'
        except Exception as exc:
            item['status'] = 'REVIEW_REQUIRED'
            item['reason'] = f'{type(exc).__name__}: {exc}'
            failures.append(item)
        items.append(item)
    # A downloaded official report must not be omitted from the human report lane.
    missing_years = sorted(set(source_by_year) - seen_years)
    if missing_years:
        failures.append({'reason': 'downloaded report missing from user delivery', 'years': missing_years})
    if not files:
        failures.append({'reason': 'official annual report collected but none delivered'})
    return {'status': 'PASS' if not failures else 'REVIEW_REQUIRED', 'pass': not failures,
            'checked': len(files), 'items': items, 'failures': failures,
            'principle': 'Korean PDF body, full-document language distribution, source-year and exact original SHA are required; filenames and webpage labels alone never count.'}
