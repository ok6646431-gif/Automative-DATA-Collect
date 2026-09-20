"""Distinguish a verified empty disclosure scope from an empty QA execution.

The content-fidelity checker measures discovered scoped HTML/PDF pairs.  Its zero
pairs are not evidence of an exhaustive no-result query.  That evidence must come
from a separate requested-period source audit.  Never report 0/0 as QA PASS.
"""
from __future__ import annotations
import csv
from pathlib import Path


def reconcile(package_root, scoped_source_ids, content_qa):
    result = dict(content_qa or {})
    count = int(result.get('expected_items') or 0)
    if count:
        return result
    scope = {str(s) for s in (scoped_source_ids or set()) if str(s)}
    p = Path(package_root) / 'Collection_Completeness.csv'
    rows = []
    if p.is_file():
        with p.open(encoding='utf-8-sig', newline='') as f:
            rows = [r for r in csv.DictReader(f)
                    if str(r.get('source') or '').upper() == 'ENVINFO'
                    and str(r.get('period_kind') or '').upper() == 'YEAR'
                    and str(r.get('expected') or '').upper() == 'Y']
    no_data = bool(rows) and all(
        str(r.get('completeness_state') or '').upper() == 'NO_DATA_CONFIRMED'
        and str(r.get('query_state') or '').upper() not in {'', 'UNQUERIED_PERIOD', 'QUERY_FAILED'}
        for r in rows
    )
    if scope:
        no_data = False  # A scoped source ID with no discovered disclosure needs investigation.
    if no_data:
        result.update(status='NOT_APPLICABLE_VERIFIED_NO_DATA', **{'pass': True},
                      zero_evidence_state='EXPLICIT_PERIOD_NO_DATA',
                      reason='No scoped ENVINFO rows and all requested periods independently confirmed NO_DATA.')
    else:
        result.update(status='REVIEW_REQUIRED_ZERO_EVIDENCE', **{'pass': False},
                      zero_evidence_state='NO_POSITIVE_CONTENT_EVIDENCE',
                      reason='0/0 is not content QA PASS; independent source and scope discovery require review.')
    result['requested_envinfo_year_checks'] = len(rows)
    result['scoped_envinfo_source_ids'] = len(scope)
    return result
