from pathlib import Path

p=Path('orchestrator/collection_completeness.py')
s=p.read_text(encoding='utf-8')
needle='''def safe(value):\n    return re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", str(value or "")).strip("_")\n'''
replace=needle+'''\n\ndef collector_term_key(source, value):\n    """Mirror each collector's on-disk search-term filename normalization.\n\n    Query completeness is checked against retained raw responses. PRTR and\n    SOOSIRO intentionally strip punctuation from their filenames, while\n    ENV-INFO and Chemical Statistics preserve dot/underscore/hyphen. Keeping\n    this mapping explicit prevents false UNQUERIED_PERIOD results when the\n    auditor and collector sanitize the same exact search term differently.\n    """\n    if source in {"PRTR", "SOOSIRO_WATER"}:\n        return re.sub(r"[^0-9A-Za-z가-힣]+", "_", str(value or "")).strip("_")\n    return safe(value)\n'''
if needle not in s:
    raise SystemExit('safe() insertion point not found')
s=s.replace(needle,replace,1)
s=s.replace('f"{year}_{safe(term)}_p1.html" for term in terms', 'f"{year}_{collector_term_key(source, term)}_p1.html" for term in terms')
s=s.replace('f"{year}_{safe(term)}.json" for term in terms', 'f"{year}_{collector_term_key(source, term)}.json" for term in terms')
p.write_text(s,encoding='utf-8')

t=Path('tests/test_collection_completeness.py')
ts=t.read_text(encoding='utf-8')
insert='''\n    def test_prtr_uses_collector_filename_normalization(self):\n        with tempfile.TemporaryDirectory() as td:\n            output=Path(td); root=output/"PRTR"; (root/"raw_search").mkdir(parents=True)\n            (root/"raw_search"/"2024_Samsung_Electronics_Co_Ltd_p1.html").write_text("ok", encoding="utf-8")\n            write_json(root/"status.json", {"status":"NO_MATCH","rows":0,"detail_ok":0})\n            rows=audit_prtr(output, {\n                "start_year":2024,"end_year":2024,\n                "search_terms":[{"term":"Samsung Electronics Co., Ltd.","year_start":2024,"year_end":2024}],\n            })\n            self.assertEqual(rows[0]["completeness_state"], "NO_DATA_CONFIRMED")\n\n    def test_soosiro_uses_collector_filename_normalization(self):\n        from orchestrator.collection_completeness import audit_soosiro\n        with tempfile.TemporaryDirectory() as td:\n            output=Path(td); root=output/"SOOSIRO_WATER"; (root/"raw_annual").mkdir(parents=True)\n            (root/"raw_annual"/"2024_Samsung_Electronics_Co_Ltd.json").write_text("{}", encoding="utf-8")\n            write_json(root/"status.json", {"status":"NO_MATCH","annual_rows":0,"errors":0})\n            write_json(root/"fact_candidates.json", [])\n            rows=audit_soosiro(output, {\n                "annual_years":[2024],"daily_years":[],\n                "search_terms":["Samsung Electronics Co., Ltd."],\n            })\n            self.assertEqual(rows[0]["completeness_state"], "NO_DATA_CONFIRMED")\n'''
marker='''\n\nif __name__ == "__main__":\n    unittest.main()\n'''
if insert.strip() not in ts:
    if marker not in ts: raise SystemExit('test insertion point not found')
    ts=ts.replace(marker,insert+marker,1)
t.write_text(ts,encoding='utf-8')
