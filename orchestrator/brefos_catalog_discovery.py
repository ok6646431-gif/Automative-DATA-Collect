"""Discover the complete current BREFOS standard-document catalog.

BREFOS is the current NIER BAT Reference Document Operation System. Unlike the legacy
IEPS board feed, its standard-document list is paginated and exposes stable document
metadata through JavaScript actions:

  fn_docView(atchFileId, stdrdocOrginlId, nttId)
  fn_zipDown(atchFileId, fileCn)

This module walks every advertised page, normalizes those identifiers and emits a
read-only discovery snapshot. It never edits bat_master_catalog.json.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

BREFOS_LIST = 'https://ieps.nier.go.kr/brefos/home/board/standardDoc/list.do'
BREFOS_PDF = 'https://ieps.nier.go.kr/brefos/common/file/pdfDocPdf.do?atchFileId={atch_file_id}'
BREFOS_ZIP = 'https://ieps.nier.go.kr/brefos/common/file/zipDownloadProcess.do'

DOC_VIEW_RE = re.compile(
    r"fn_docView\(\s*(\d+)\s*,\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]?(\d+)['\"]?\s*\)",
    re.I,
)
ZIP_RE = re.compile(
    r"fn_zipDown\(\s*['\"]?(\d+)['\"]?\s*,\s*['\"]([^'\"]+)['\"]\s*\)",
    re.I,
)
PAGING_RE = re.compile(
    r"new\s+pagingView\(\s*['\"]?(\d+)['\"]?\s*,\s*['\"]?(\d+)['\"]?\s*,\s*['\"]?(\d+)['\"]?\s*\)",
    re.I,
)


def _session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    retry = Retry(
        total=2,
        connect=2,
        read=1,
        status=1,
        backoff_factor=0.6,
        status_forcelist=(408, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({'GET', 'POST'}),
        raise_on_status=False,
    )
    s = requests.Session()
    s.headers.update({'User-Agent': 'Mozilla/5.0 (BREFOSCatalogDiscovery/1.0; official-public-reference)'})
    adapter = HTTPAdapter(max_retries=retry)
    s.mount('https://', adapter)
    return s


def parse_page(html: str, page_index: int = 1) -> Dict[str, Any]:
    """Parse one BREFOS list page into stable document metadata."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'html.parser')
    views: Dict[str, Dict[str, str]] = {}
    titles: Dict[str, str] = {}
    row_text: Dict[str, str] = {}

    for a in soup.find_all('a'):
        onclick = str(a.get('onclick') or '')
        vm = DOC_VIEW_RE.search(onclick)
        if vm:
            atch, origin, ntt = vm.groups()
            views[atch] = {
                'atch_file_id': atch,
                'stdrdoc_origin_id': origin,
                'ntt_id': ntt,
            }
            tr = a.find_parent('tr')
            if tr:
                row_text[atch] = ' '.join(tr.stripped_strings).strip()
        zm = ZIP_RE.search(onclick)
        if zm:
            atch, title = zm.groups()
            titles[atch] = ' '.join(title.split()).strip()
            tr = a.find_parent('tr')
            if tr:
                row_text[atch] = ' '.join(tr.stripped_strings).strip()

    documents = []
    for atch in sorted(set(views) | set(titles), key=lambda x: int(x), reverse=True):
        doc = dict(views.get(atch) or {
            'atch_file_id': atch,
            'stdrdoc_origin_id': '',
            'ntt_id': '',
        })
        doc.update({
            'title': titles.get(atch, ''),
            'list_page_index': page_index,
            'row_text': row_text.get(atch, ''),
            'viewer_pdf_url': BREFOS_PDF.format(atch_file_id=atch),
            'zip_download_url': BREFOS_ZIP,
        })
        documents.append(doc)

    paging = None
    m = PAGING_RE.search(html)
    if m:
        current, total, per_page = (int(x) for x in m.groups())
        paging = {
            'current_page': current,
            'total_records': total,
            'records_per_page': per_page,
            'total_pages': math.ceil(total / per_page) if per_page else 1,
        }
    return {
        'documents': documents,
        'paging': paging,
        'page_document_count': len(documents),
    }


def _request_page(session, page_index: int, timeout=(10, 40)):
    if page_index == 1:
        return session.get(BREFOS_LIST, timeout=timeout, allow_redirects=True)
    data = {
        'nttId': '',
        'pageIndex': str(page_index),
        'pageSize': '10',
        'recordCountPerPage': '10',
        'srchNttSeCode': '',
        'searchWrd': '',
    }
    return session.post(BREFOS_LIST, data=data, timeout=timeout, allow_redirects=True)


def discover(max_pages: int = 20, timeout=(10, 40)) -> Dict[str, Any]:
    session = _session()
    attempts: List[Dict[str, Any]] = []
    documents_by_attachment: Dict[str, Dict[str, Any]] = {}
    advertised_total = None
    advertised_pages = None

    for page_index in range(1, max_pages + 1):
        if advertised_pages is not None and page_index > advertised_pages:
            break
        try:
            r = _request_page(session, page_index, timeout=timeout)
            r.raise_for_status()
        except Exception as exc:
            attempts.append({
                'page_index': page_index,
                'state': 'SOURCE_UNREACHABLE',
                'error': f'{type(exc).__name__}: {exc}',
            })
            if page_index == 1:
                return {
                    'schema_version': '1.0',
                    'checked_at': datetime.now(timezone.utc).isoformat(),
                    'status': 'SOURCE_UNREACHABLE',
                    'source_url': BREFOS_LIST,
                    'attempts': attempts,
                    'documents': [],
                }
            continue

        parsed = parse_page(r.text, page_index)
        paging = parsed.get('paging') or {}
        if page_index == 1 and paging:
            advertised_total = int(paging.get('total_records') or 0)
            advertised_pages = int(paging.get('total_pages') or 1)
        attempts.append({
            'page_index': page_index,
            'state': 'OK',
            'http_status': r.status_code,
            'final_url': r.url,
            'bytes': len(r.content),
            'page_document_count': parsed['page_document_count'],
            'paging': paging,
        })
        for doc in parsed['documents']:
            documents_by_attachment[str(doc['atch_file_id'])] = doc

        if advertised_pages is None and parsed['page_document_count'] == 0:
            break

    documents = sorted(
        documents_by_attachment.values(),
        key=lambda x: (int(x.get('ntt_id') or 0), int(x.get('atch_file_id') or 0)),
        reverse=True,
    )
    actual = len(documents)
    if advertised_total is None:
        status = 'PAGING_METADATA_MISSING'
    elif actual == advertised_total:
        status = 'PASS'
    else:
        status = 'INCOMPLETE_DISCOVERY'

    return {
        'schema_version': '1.0',
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'status': status,
        'source_url': BREFOS_LIST,
        'advertised_total_records': advertised_total,
        'advertised_total_pages': advertised_pages,
        'discovered_document_count': actual,
        'attempts': attempts,
        'documents': documents,
        'identity_key': 'atch_file_id',
        'principle': 'BREFOS page count is authoritative for discovery completeness. Viewer PDF endpoints are candidates until byte verification succeeds.',
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='BREFOS_Catalog_Discovery.json')
    ap.add_argument('--max-pages', type=int, default=20)
    args = ap.parse_args()
    payload = discover(max_pages=args.max_pages)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'status': payload.get('status'),
        'advertised_total_records': payload.get('advertised_total_records'),
        'advertised_total_pages': payload.get('advertised_total_pages'),
        'discovered_document_count': payload.get('discovered_document_count', 0),
    }, ensure_ascii=False, indent=2))
    if payload.get('status') in {'INCOMPLETE_DISCOVERY', 'PAGING_METADATA_MISSING'}:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
