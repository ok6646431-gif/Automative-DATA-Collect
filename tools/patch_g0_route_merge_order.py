from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runner_path = ROOT / "orchestrator" / "zero_touch_runner.py"
test_path = ROOT / "tests" / "test_g0_report_finalizer.py"

runner = runner_path.read_text(encoding="utf-8")

old_tail = '''    # Fresh Discovery owns document identity/coverage, but a stronger transport route
    # already byte-verified for the same DART-anchored legal entity must not disappear
    # merely because a later crawl rediscovers a weaker company-hosted URL.
    try:
        from orchestrator.document_route_merge import merge_document_routes
        existing_company_path = ROOT / 'requests/company_discovery.json'
        existing_documents_path = ROOT / 'requests/document_evidence.json'
        if existing_company_path.exists() and existing_documents_path.exists():
            existing_company = json.loads(existing_company_path.read_text(encoding='utf-8'))
            existing_documents = json.loads(existing_documents_path.read_text(encoding='utf-8'))
            before = [str(x.get('source_url') or '') for x in documents.get('documents', []) or [] if isinstance(x, dict)]
            documents = merge_document_routes(existing_company, existing_documents, discovery, documents)
            after = [str(x.get('source_url') or '') for x in documents.get('documents', []) or [] if isinstance(x, dict)]
            audit.setdefault('stages', {})['document_route_merge'] = {
                'status': 'APPLIED',
                'primary_routes_changed': sum(1 for a, b in zip(before, after) if a != b),
            }
    except Exception as exc:
        audit.setdefault('stages', {})['document_route_merge'] = {
            'status': 'SKIPPED_ERROR',
            'error': f'{type(exc).__name__}: {exc}',
        }
    return discovery, documents, audit
'''

helper = '''def _merge_verified_document_routes(discovery, documents, audit):
    """Restore same-entity byte-verified routes before final coverage decisions.

    Fresh Discovery owns document identity and coverage.  A previously byte-verified
    route for the same DART-anchored legal entity may restore a concrete annual file,
    but that restored evidence still has to pass the normal finalizer, catalog-cadence,
    entity-window and promotion policies.  Therefore route restoration belongs before
    those final coverage decisions, not after them.
    """
    try:
        from orchestrator.document_route_merge import merge_document_routes

        existing_company_path = ROOT / "requests/company_discovery.json"
        existing_documents_path = ROOT / "requests/document_evidence.json"
        if existing_company_path.exists() and existing_documents_path.exists():
            existing_company = json.loads(existing_company_path.read_text(encoding="utf-8"))
            existing_documents = json.loads(existing_documents_path.read_text(encoding="utf-8"))
            before = [
                str(x.get("source_url") or "")
                for x in documents.get("documents", []) or []
                if isinstance(x, dict)
            ]
            documents = merge_document_routes(
                existing_company, existing_documents, discovery, documents
            )
            after = [
                str(x.get("source_url") or "")
                for x in documents.get("documents", []) or []
                if isinstance(x, dict)
            ]
            audit.setdefault("stages", {})["document_route_merge"] = {
                "status": "APPLIED",
                "primary_routes_changed": sum(
                    1 for a, b in zip(before, after) if a != b
                ),
            }
    except Exception as exc:
        audit.setdefault("stages", {})["document_route_merge"] = {
            "status": "SKIPPED_ERROR",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return documents


'''

anchor = "def _enriched_discover(company: str, start_year: int = 2020, max_pages: int = 90):\n"
if helper not in runner:
    if anchor not in runner:
        raise SystemExit("runner helper insertion anchor not found")
    runner = runner.replace(anchor, helper + anchor, 1)

if old_tail in runner:
    runner = runner.replace(old_tail, "    return discovery, documents, audit\n", 1)
elif "# Fresh Discovery owns document identity/coverage" in runner:
    raise SystemExit("unexpected trailing route-merge block shape")

old_order = '''    documents = g0_report_entity_policy.normalize(discovery, documents, audit)
    documents = g0_report_finalizer.finalize(discovery, documents, audit)
'''
new_order = '''    documents = g0_report_entity_policy.normalize(discovery, documents, audit)
    documents = _merge_verified_document_routes(discovery, documents, audit)
    documents = g0_report_finalizer.finalize(discovery, documents, audit)
'''
if new_order not in runner:
    if old_order not in runner:
        raise SystemExit("report policy insertion anchor not found")
    runner = runner.replace(old_order, new_order, 1)

runner_path.write_text(runner, encoding="utf-8")

tests = test_path.read_text(encoding="utf-8")
method = '''    def test_verified_route_merge_precedes_final_coverage_policies(self):
        runner_path = Path(__file__).resolve().parents[1] / "orchestrator" / "zero_touch_runner.py"
        source = runner_path.read_text(encoding="utf-8")
        start = source.index("def _enriched_discover")
        merge_pos = source.index(
            "documents = _merge_verified_document_routes(discovery, documents, audit)", start
        )
        finalizer_pos = source.index(
            "documents = g0_report_finalizer.finalize(discovery, documents, audit)", start
        )
        catalog_pos = source.index(
            "documents = g0_report_catalog_policy.normalize_verified_catalog_gaps(", start
        )
        promotion_pos = source.index(
            "discovery, documents, audit = g0_promotion_policy.apply(", start
        )
        self.assertLess(merge_pos, finalizer_pos)
        self.assertLess(finalizer_pos, catalog_pos)
        self.assertLess(catalog_pos, promotion_pos)

'''
if "test_verified_route_merge_precedes_final_coverage_policies" not in tests:
    if "import unittest\n" not in tests:
        raise SystemExit("test import anchor not found")
    tests = tests.replace("import unittest\n", "import unittest\nfrom pathlib import Path\n", 1)
    class_anchor = "class ReportCatalogCurrentYearTests(unittest.TestCase):\n"
    if class_anchor not in tests:
        raise SystemExit("test class anchor not found")
    tests = tests.replace(class_anchor, class_anchor + method, 1)

test_path.write_text(tests, encoding="utf-8")

print("patched route restoration order before final report coverage policies")
