"""Fail-closed SITE_SET export guard for unresolved public-source site identities.

The raw collector and integration layers keep every source row. The user-facing
workbook must not display a REVIEW_REQUIRED source ID from an unrelated site
merely because it belongs to the same legal entity. COMPANY-mode workbooks keep
their existing review inventory. Source IDs explicitly authorized for a SITE_SET
may still be presented in its review sheets.
"""
from __future__ import annotations

import json
from functools import wraps
from pathlib import Path


def guard_build_human_excels(build_human_excels):
    """Limit review workbooks to the resolved requested-site source-ID boundary."""
    @wraps(build_human_excels)
    def guarded(package_root, archive_root, scope):
        scope_path = Path(package_root) / 'Requested_Scope.json'
        if not scope_path.is_file():
            raise RuntimeError('Requested_Scope.json missing before user workbook export')
        request_scope = json.loads(scope_path.read_text(encoding='utf-8'))
        if request_scope.get('mode') != 'SITE_SET':
            return build_human_excels(package_root, archive_root, scope)

        # The archive builder passes the resolved, source-native target IDs. They
        # are the sole admission rule for SITE_SET review rows. Do not infer site
        # membership from a company-name prefix or other site names in the raw.
        authorized = {
            source: {str(sid) for sid in ids if str(sid)}
            for source, ids in scope.items()
        }
        original_identity_map = build_human_excels.__globals__['_identity_review_map']

        def scoped_identity_review_map(root, source):
            candidates = original_identity_map(root, source)
            allowed = authorized.get(source, set())
            return {sid: row for sid, row in candidates.items() if sid in allowed}

        build_human_excels.__globals__['_identity_review_map'] = scoped_identity_review_map
        try:
            return build_human_excels(package_root, archive_root, scope)
        finally:
            build_human_excels.__globals__['_identity_review_map'] = original_identity_map

    return guarded
