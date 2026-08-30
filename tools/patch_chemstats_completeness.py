from pathlib import Path

p=Path('orchestrator/collection_completeness.py')
s=p.read_text(encoding='utf-8')
start=s.index('def audit_chem(output, cfg):')
end=s.index('\ndef audit_cleansys(output, cfg):', start)
new='''def audit_chem(output, cfg):
    source = "CHEM_STATS"; root = output/source; status = read_json(root/"status.json", {}) or {}
    data_years = discovery_years(root/"discovery.csv", ["search_year", "reportYear"])
    failures = error_years(root/"errors.log", {"DISCOVERY"}); rows = []
    for year in [as_year(x) for x in cfg.get("years", [])]:
        if year is None: continue
        terms = terms_for_year(cfg, year)
        files = [root/"raw_discovery"/f"{year}_{safe(term)}_p1.json" for term in terms]
        complete = bool(terms) and all(p.exists() and p.stat().st_size > 0 for p in files)
        failed = year in failures or (status.get("status") in TERMINAL_FAILURES and not complete)
        rows.append(query_row(source, year, complete, failed, year in data_years,
                              f"terms={len(terms)}; page1={sum(p.exists() for p in files)}; search_error={year in failures}; status={status.get('status')}"))

    # A source-native facility ID can remain valid in an older survey round even
    # when that round's name index no longer exposes the facility.  The collector
    # probes such missing ID-year pairs and writes an explicit audit trail.  Count
    # successful empty probes as NO_DATA_CONFIRMED, not as a collection omission.
    backfill_path = root/"source_id_backfill_audit.jsonl"
    for item in read_jsonl(backfill_path):
        year=as_year(item.get("search_year")); bid=str(item.get("bplcId") or "")
        if year is None or not bid: continue
        state=str(item.get("query_status") or "").upper(); period=f"{year}:{bid}"
        evidence=f"anchor_year={item.get('identity_anchor_year','')}; substantive_rows={item.get('substantive_rows','')}; http={item.get('http_status','')}"
        if state=="DATA_PRESENT":
            rows.append(row("CHEM_STATS_SOURCE_ID","SOURCE_ID_YEAR",period,"DATA_PRESENT",query_state="COMPLETE",data=True,evidence=evidence))
        elif state=="NO_DATA_CONFIRMED":
            rows.append(row("CHEM_STATS_SOURCE_ID","SOURCE_ID_YEAR",period,"NO_DATA_CONFIRMED",query_state="COMPLETE",data=False,evidence=evidence,note="동일 source-native 사업장 ID를 해당 조사연도에 정상 조회했으나 공개 상세자료가 없음"))
        else:
            rows.append(row("CHEM_STATS_SOURCE_ID","SOURCE_ID_YEAR",period,"QUERY_FAILED",query_state="FAILED",data=False,evidence=evidence or str(item.get('error') or ''),note="source-native 사업장 ID의 조사연도 역추적 조회 실패"))

    expected_backfills=int(status.get("source_id_backfill_attempts") or 0)
    if expected_backfills and len(read_jsonl(backfill_path)) != expected_backfills:
        rows.append(row(source,"ARTIFACT","SOURCE_ID_BACKFILL_AUDIT","ARTIFACT_INCOMPLETE",query_state="COMPLETE",data=backfill_path.exists(),evidence=f"declared_attempts={expected_backfills}; audit_rows={len(read_jsonl(backfill_path))}",note="source-native ID 역추적 시도 기록이 완전하지 않음"))

    discovered = int(status.get("rows") or 0); detail_ok = int(status.get("detail_ok") or 0)
    if cfg.get("collect_details", True) and discovered and detail_ok != discovered:
        rows.append(row(source, "ARTIFACT", "DETAILS", "ARTIFACT_INCOMPLETE", query_state="COMPLETE",
                        data=detail_ok > 0, evidence=f"discovery_rows={discovered}; detail_ok={detail_ok}; detail_fail={status.get('detail_fail',0)}",
                        note="검색 또는 source-native ID 역추적으로 확인된 사업장-연도 중 화학물질통계 상세 원문이 전부 확보되지 않음"))
    return rows

'''
s=s[:start]+new+s[end+1:]
p.write_text(s,encoding='utf-8')

t=Path('tests/test_collection_completeness.py')
ts=t.read_text(encoding='utf-8')
insert='''
    def test_chem_source_id_backfill_is_audited_per_round(self):
        from orchestrator.collection_completeness import audit_chem
        with tempfile.TemporaryDirectory() as td:
            output=Path(td); root=output/"CHEM_STATS"; (root/"raw_discovery").mkdir(parents=True)
            for year in [2020,2022]:
                (root/"raw_discovery"/f"{year}_기업_p1.json").write_text("{}", encoding="utf-8")
            write_csv(root/"discovery.csv", [
                {"search_year":2020,"bplcId":"SITE1"},
                {"search_year":2022,"bplcId":"SITE1"},
            ])
            write_json(root/"status.json", {"status":"DATA_FOUND","rows":2,"detail_ok":2,"source_id_backfill_attempts":1})
            (root/"source_id_backfill_audit.jsonl").write_text(json.dumps({
                "search_year":2020,"bplcId":"SITE1","identity_anchor_year":2022,
                "query_status":"DATA_PRESENT","substantive_rows":30,"http_status":200,
            },ensure_ascii=False)+"\\n",encoding="utf-8")
            rows=audit_chem(output,{"years":[2020,2022],"search_terms":["기업"],"collect_details":True})
            found=[r for r in rows if r["source"]=="CHEM_STATS_SOURCE_ID" and r["period"]=="2020:SITE1"]
            self.assertEqual(found[0]["completeness_state"],"DATA_PRESENT")

    def test_chem_source_id_empty_probe_is_no_data_confirmed(self):
        from orchestrator.collection_completeness import audit_chem
        with tempfile.TemporaryDirectory() as td:
            output=Path(td); root=output/"CHEM_STATS"; (root/"raw_discovery").mkdir(parents=True)
            (root/"raw_discovery"/"2020_기업_p1.json").write_text("{}", encoding="utf-8")
            write_json(root/"status.json", {"status":"NO_MATCH","rows":0,"detail_ok":0,"source_id_backfill_attempts":1})
            (root/"source_id_backfill_audit.jsonl").write_text(json.dumps({
                "search_year":2020,"bplcId":"SITE1","identity_anchor_year":2022,
                "query_status":"NO_DATA_CONFIRMED","substantive_rows":0,"http_status":200,
            },ensure_ascii=False)+"\\n",encoding="utf-8")
            rows=audit_chem(output,{"years":[2020],"search_terms":["기업"],"collect_details":True})
            found=[r for r in rows if r["source"]=="CHEM_STATS_SOURCE_ID"]
            self.assertEqual(found[0]["completeness_state"],"NO_DATA_CONFIRMED")
'''
marker='\n\nif __name__ == "__main__":\n    unittest.main()\n'
if insert.strip() not in ts:
    ts=ts.replace(marker,insert+marker,1)
t.write_text(ts,encoding='utf-8')
