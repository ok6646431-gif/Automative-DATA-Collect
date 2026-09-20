"""Fail-closed Korean annual-report delivery QA for original company reports.

ENV-INFO attachment copies can appear in the same display folder; their distinct
source-native provenance must not turn an ESH booklet into an annual company report.
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
    hangul = latin = korean_pages = meaningful_pages = first_six_hangul = 0
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
    if first_six_hangul < 100 or hangul < 400 or meaningful_pages == 0:
        raise ValueError('Korean text cannot be verified throughout annual report')
    if korean_pages / meaningful_pages < .30 or hangul * 2 < latin:
        raise ValueError('annual report is not verifiably Korean-primary')
    return {'pages': len(pdf.pages), 'hangul_chars': hangul,
            'latin_chars': latin, 'meaningful_pages': meaningful_pages,
            'korean_pages': korean_pages}


def evaluate(package_root, archive_root):
    package_root = Path(package_root)
    archive_root = Path(archive_root)
    sources = _annual_source_rows(package_root)
    folders = [p for p in archive_root.rglob('04_지속가능경영보고서') if p.is_dir()]
    all_pdfs = sorted(p for d in folders for p in d.rglob('*.pdf') if p.is_file())
    # Files copied out of ENV-INFO carry this generated source prefix. They are
    # disclosed attachments, not independent corporate annual-report originals.
    # Record them separately; NEVER use them to satisfy corporate annual coverage.
    attachments = [p for p in all_pdfs if p.name.startswith('ENVINFO공개연도_')]
    files = [p for p in all_pdfs if p not in attachments]
    extras = [str(p.relative_to(archive_root)) for p in attachments]
    if not sources and not files:
        return {'status': 'NOT_APPLICABLE', 'pass': True, 'checked': 0, 'items': [],
                'separately_classified_envinfo_attachments': extras,
                'principle': 'No annual original asserted; discovery/coverage checks are independent.'}
    source_by_year = {}
    for row in sources:
        year = _year(row.get('report_year'))
        digest = str(row.get('sha256') or '').lower()
        if year and re.fullmatch(r'[0-9a-f]{64}', digest):
            source_by_year.setdefault(year, set()).add(digest)
    items, failures, seen_years = [], [], set()
    for path in files:
        year = _year(path.name)
        item = {'path': str(path.relative_to(archive_root)), 'report_year': year,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        try:
            if year is None:
                raise ValueError('report year missing from delivered filename')
            if year in seen_years:
                raise ValueError('multiple independently delivered official annual PDFs for one year')
            seen_years.add(year)
            if item['sha256'] not in source_by_year.get(year, set()):
                raise ValueError('delivered original does not match official annual source SHA for this year')
            item.update(_inspect_pdf(path))
            item['status'] = 'PASS'
        except Exception as exc:
            item['status'] = 'REVIEW_REQUIRED'
            item['reason'] = f'{type(exc).__name__}: {exc}'
            failures.append(item)
        items.append(item)
    missing_years = sorted(set(source_by_year) - seen_years)
    if missing_years:
        failures.append({'reason': 'downloaded official annual original missing from delivery', 'years': missing_years})
    if not files:
        failures.append({'reason': 'official annual originals collected but none delivered'})
    return {'status': 'PASS' if not failures else 'REVIEW_REQUIRED', 'pass': not failures,
            'checked': len(files), 'items': items, 'failures': failures,
            'separately_classified_envinfo_attachments': extras,
            'principle': 'Only source-matched original annual PDFs count for annual coverage; ENVINFO-promoted attachments are recorded separately; actual Korean body is validated on every page.'}
