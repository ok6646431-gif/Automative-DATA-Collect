from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new):
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"expected patch anchor missing: {path}: {old[:120]!r}")
    text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")
    print(f"patched {path}")


# ENV-INFO: broad name search remains audit metadata; detail/attachments are current-entity/site only.
replace(
    "collectors/envinfo_collect.py",
    '''try:\n    from .name_filter import matching_exclusion\nexcept ImportError:\n    from name_filter import matching_exclusion\n''',
    '''try:\n    from .name_filter import matching_exclusion\n    from .entity_scope_gate import split_candidates\nexcept ImportError:\n    from name_filter import matching_exclusion\n    from entity_scope_gate import split_candidates\n''',
)
replace(
    "collectors/envinfo_collect.py",
    '''        rows=list(dedup.values())\n        all_keys=sorted({k for r in rows for k in r})\n''',
    '''        search_candidate_rows=list(dedup.values())\n        rows,scope_rejected_rows=split_candidates(\n            search_candidate_rows,\n            name_getter=lambda r: r.get("compNm", ""),\n            gate=cfg.get("identity_gate"),\n        )\n        all_keys=sorted({k for r in rows for k in r})\n''',
)
replace(
    "collectors/envinfo_collect.py",
    '''        with (out/"excluded_rows.jsonl").open("w",encoding="utf-8") as f:\n            for r in excluded_rows: f.write(json.dumps(r,ensure_ascii=False)+"\\n")\n        detail_ok=0; detail_fail=0\n''',
    '''        with (out/"excluded_rows.jsonl").open("w",encoding="utf-8") as f:\n            for r in excluded_rows: f.write(json.dumps(r,ensure_ascii=False)+"\\n")\n        with (out/"scope_rejected_rows.jsonl").open("w",encoding="utf-8") as f:\n            for r in scope_rejected_rows: f.write(json.dumps(r,ensure_ascii=False)+"\\n")\n        detail_ok=0; detail_fail=0\n''',
)
replace(
    "collectors/envinfo_collect.py",
    '''        status.update({"status":"DATA_FOUND" if rows else "NO_MATCH","rows":len(rows),"excluded_rows":len(excluded_rows),"unique_comp_ids":len({r.get('compId') for r in rows}),"detail_ok":detail_ok,"detail_fail":detail_fail,"attachments_discovered":len(attachment_rows),"attachment_ok":attachment_ok,"attachment_fail":attachment_fail,"attachment_bytes":attachment_bytes})\n''',
    '''        status.update({"status":"DATA_FOUND" if rows else "NO_MATCH","search_candidate_rows":len(search_candidate_rows),"rows":len(rows),"scope_rejected_rows":len(scope_rejected_rows),"excluded_rows":len(excluded_rows),"unique_comp_ids":len({r.get('compId') for r in rows}),"detail_ok":detail_ok,"detail_fail":detail_fail,"attachments_discovered":len(attachment_rows),"attachment_ok":attachment_ok,"attachment_fail":attachment_fail,"attachment_bytes":attachment_bytes})\n''',
)

# PRTR: address/site/name metadata is enough to gate detail popup collection.
replace(
    "collectors/prtr_collect.py",
    '''try:\n    from .name_filter import matching_exclusion\nexcept ImportError:\n    from name_filter import matching_exclusion\n''',
    '''try:\n    from .name_filter import matching_exclusion\n    from .entity_scope_gate import evaluate_candidate\nexcept ImportError:\n    from name_filter import matching_exclusion\n    from entity_scope_gate import evaluate_candidate\n''',
)
replace(
    "collectors/prtr_collect.py",
    '''    s=session(); dedup={}; successful=0; excluded_rows=[]\n''',
    '''    s=session(); dedup={}; successful=0; excluded_rows=[]; scope_rejected_rows=[]\n''',
)
replace(
    "collectors/prtr_collect.py",
    '''                        hits=match_sites(row["address_raw"],cfg.get("site_address_anchors",{})); key=(y,row["entrps_id"])\n''',
    '''                        decision=evaluate_candidate(row["company_name_raw"],row["address_raw"],cfg.get("identity_gate"))\n                        if not decision["allowed"]:\n                            scope_rejected_rows.append({"search_year":y,"search_term":term,**row,"detail_scope_decision":decision["decision"],"detail_scope_reason":decision["reason"]})\n                            continue\n                        hits=match_sites(row["address_raw"],cfg.get("site_address_anchors",{})); key=(y,row["entrps_id"])\n''',
)
replace(
    "collectors/prtr_collect.py",
    '''        with (out/"excluded_rows.jsonl").open("w",encoding="utf-8") as f:\n            for row in excluded_rows: f.write(json.dumps(row,ensure_ascii=False)+"\\n")\n        detail_ok=0; detail_fail=0; flat=[]\n''',
    '''        with (out/"excluded_rows.jsonl").open("w",encoding="utf-8") as f:\n            for row in excluded_rows: f.write(json.dumps(row,ensure_ascii=False)+"\\n")\n        with (out/"scope_rejected_rows.jsonl").open("w",encoding="utf-8") as f:\n            for row in scope_rejected_rows: f.write(json.dumps(row,ensure_ascii=False)+"\\n")\n        detail_ok=0; detail_fail=0; flat=[]\n''',
)
replace(
    "collectors/prtr_collect.py",
    '''        status.update({"status":"DATA_FOUND" if rows else "NO_MATCH","rows":len(rows),"years":years,"successful_responses":successful,"excluded_rows":len(excluded_rows),"detail_ok":detail_ok,"detail_fail":detail_fail,"detail_table_rows":len(flat)})\n''',
    '''        status.update({"status":"DATA_FOUND" if rows else "NO_MATCH","rows":len(rows),"years":years,"successful_responses":successful,"scope_rejected_rows":len(scope_rejected_rows),"excluded_rows":len(excluded_rows),"detail_ok":detail_ok,"detail_fail":detail_fail,"detail_table_rows":len(flat)})\n''',
)

# Chemical Statistics: only verified current-entity/site IDs may seed cross-year backfill.
replace(
    "collectors/chem_stats_collect.py",
    '''try:\n    from .name_filter import matching_exclusion\nexcept ImportError:\n    from name_filter import matching_exclusion\n''',
    '''try:\n    from .name_filter import matching_exclusion\n    from .entity_scope_gate import evaluate_candidate\nexcept ImportError:\n    from name_filter import matching_exclusion\n    from entity_scope_gate import evaluate_candidate\n''',
)
replace(
    "collectors/chem_stats_collect.py",
    '''    status={"source_key":"CHEM_STATS","status":"RUNNING","requests":0,"errors":0,"years":years,"terms":terms}; dedup={}; successful=0; excluded_rows=[]\n''',
    '''    status={"source_key":"CHEM_STATS","status":"RUNNING","requests":0,"errors":0,"years":years,"terms":terms}; dedup={}; successful=0; excluded_rows=[]; scope_rejected_rows=[]\n''',
)
replace(
    "collectors/chem_stats_collect.py",
    '''                        key=(y,str(bid))\n                        if key not in dedup:\n''',
    '''                        decision=evaluate_candidate(field_ci(source_row,"bplcnm",""),field_ci(source_row,"locplcadres",""),cfg.get("identity_gate"))\n                        if not decision["allowed"]:\n                            scope_rejected_rows.append({"search_year":y,"search_term":term,**source_row,"detail_scope_decision":decision["decision"],"detail_scope_reason":decision["reason"]})\n                            continue\n                        key=(y,str(bid))\n                        if key not in dedup:\n''',
)
replace(
    "collectors/chem_stats_collect.py",
    '''        write_jsonl(out/"excluded_rows.jsonl",excluded_rows)\n        write_jsonl(out/"source_id_backfill_audit.jsonl",backfill_audit)\n''',
    '''        write_jsonl(out/"excluded_rows.jsonl",excluded_rows)\n        write_jsonl(out/"scope_rejected_rows.jsonl",scope_rejected_rows)\n        write_jsonl(out/"source_id_backfill_audit.jsonl",backfill_audit)\n''',
)
replace(
    "collectors/chem_stats_collect.py",
    '''            "successful_responses":successful,"excluded_rows":len(excluded_rows),"unique_bplc_ids":len({x for x in ids if x}),\n''',
    '''            "successful_responses":successful,"scope_rejected_rows":len(scope_rejected_rows),"excluded_rows":len(excluded_rows),"unique_bplc_ids":len({x for x in ids if x}),\n''',
)

# CleanSYS: short company substring may discover candidates, but only verified entity/site labels are queried.
replace(
    "collectors/cleansys_collect.py",
    '''try:\n    from .name_filter import matching_exclusion\nexcept ImportError:\n    from name_filter import matching_exclusion\n''',
    '''try:\n    from .name_filter import matching_exclusion\n    from .entity_scope_gate import evaluate_candidate\nexcept ImportError:\n    from name_filter import matching_exclusion\n    from entity_scope_gate import evaluate_candidate\n''',
)
replace(
    "collectors/cleansys_collect.py",
    '''        soup=BeautifulSoup(r.text,"html.parser"); candidates=[]; excluded_candidates=[]\n''',
    '''        soup=BeautifulSoup(r.text,"html.parser"); candidates=[]; excluded_candidates=[]; scope_rejected_candidates=[]\n''',
)
replace(
    "collectors/cleansys_collect.py",
    '''            if exclusion:\n                excluded_candidates.append({**row,"excluded_by":exclusion})\n            else:\n                candidates.append(row)\n''',
    '''            if exclusion:\n                excluded_candidates.append({**row,"excluded_by":exclusion})\n            else:\n                decision=evaluate_candidate(name,"",cfg.get("identity_gate"))\n                if decision["allowed"]:\n                    candidates.append({**row,"detail_scope_decision":decision["decision"]})\n                else:\n                    scope_rejected_candidates.append({**row,"detail_scope_decision":decision["decision"],"detail_scope_reason":decision["reason"]})\n''',
)
replace(
    "collectors/cleansys_collect.py",
    '''        (out/"excluded_candidates.json").write_text(json.dumps(excluded_candidates,ensure_ascii=False,indent=2),encoding="utf-8")\n''',
    '''        (out/"excluded_candidates.json").write_text(json.dumps(excluded_candidates,ensure_ascii=False,indent=2),encoding="utf-8")\n        (out/"scope_rejected_candidates.json").write_text(json.dumps(scope_rejected_candidates,ensure_ascii=False,indent=2),encoding="utf-8")\n''',
)
replace(
    "collectors/cleansys_collect.py",
    '''        status.update({"status":"DATA_FOUND" if rows else ("RESPONSE_OK_NO_TERM_MATCH" if not candidates else "REQUEST_OR_PARSE_FAILED"),"candidate_count":len(candidates),"excluded_candidates":len(excluded_candidates),"annual_rows":len(rows),"annual_years":sorted({str(r.get('examin_year')) for r in rows}),"errors":errors,"tls_verification":verify,"tls_verification_exception":tls_error})\n''',
    '''        status.update({"status":"DATA_FOUND" if rows else ("RESPONSE_OK_NO_TERM_MATCH" if not candidates else "REQUEST_OR_PARSE_FAILED"),"candidate_count":len(candidates),"scope_rejected_candidates":len(scope_rejected_candidates),"excluded_candidates":len(excluded_candidates),"annual_rows":len(rows),"annual_years":sorted({str(r.get('examin_year')) for r in rows}),"errors":errors,"tls_verification":verify,"tls_verification_exception":tls_error})\n''',
)

# SOOSIRO: both address-seeded and name-searched FACT candidates must pass the same gate.
replace(
    "collectors/soosiro_collect.py",
    '''try:\n    from .name_filter import matching_exclusion\nexcept ImportError:\n    from name_filter import matching_exclusion\n''',
    '''try:\n    from .name_filter import matching_exclusion\n    from .entity_scope_gate import evaluate_candidate\nexcept ImportError:\n    from name_filter import matching_exclusion\n    from entity_scope_gate import evaluate_candidate\n''',
)
replace(
    "collectors/soosiro_collect.py",
    '''    dedup={}; candidates={}; excluded_rows=[]\n''',
    '''    dedup={}; candidates={}; excluded_rows=[]; scope_rejected_rows=[]\n''',
)
replace(
    "collectors/soosiro_collect.py",
    '''            fc=str(row.get("FACT_CODE","") or ""); wn=str(row.get("WAST_NO","") or ""); key=(str(row.get("YEAR",y)),fc,wn)\n''',
    '''            decision=evaluate_candidate(source_name,row.get("FACT_ADDR",""),cfg.get("identity_gate"))\n            if not decision["allowed"]:\n                scope_rejected_rows.append({"query_year":y,"search_term":hit,**row,"detail_scope_decision":decision["decision"],"detail_scope_reason":decision["reason"]})\n                continue\n            fc=str(row.get("FACT_CODE","") or ""); wn=str(row.get("WAST_NO","") or ""); key=(str(row.get("YEAR",y)),fc,wn)\n''',
)
replace(
    "collectors/soosiro_collect.py",
    '''            exclusion=matching_exclusion(source_name,exclude_terms)\n            if not fc or exclusion: continue\n            candidates[fc]={"FACT_CODE":fc,"FACT_NAME":fact.get("FACT_NAME"),"FACT_FNAME":fact.get("FACT_FNAME"),"FACT_ADDR":fact.get("FACT_ADDR"),"discovery_basis":"OFFICIAL_ADDRESS"}\n''',
    '''            exclusion=matching_exclusion(source_name,exclude_terms)\n            if not fc or exclusion: continue\n            decision=evaluate_candidate(source_name,fact.get("FACT_ADDR",""),cfg.get("identity_gate"))\n            if not decision["allowed"]:\n                scope_rejected_rows.append({"search_term":"OFFICIAL_ADDRESS",**fact,"detail_scope_decision":decision["decision"],"detail_scope_reason":decision["reason"]})\n                continue\n            candidates[fc]={"FACT_CODE":fc,"FACT_NAME":fact.get("FACT_NAME"),"FACT_FNAME":fact.get("FACT_FNAME"),"FACT_ADDR":fact.get("FACT_ADDR"),"discovery_basis":"OFFICIAL_ADDRESS"}\n''',
)
replace(
    "collectors/soosiro_collect.py",
    '''        with (out/"excluded_rows.jsonl").open("w",encoding="utf-8") as f:\n            for row in excluded_rows: f.write(json.dumps(row,ensure_ascii=False)+"\\n")\n        (out/"fact_candidates.json").write_text(json.dumps(list(candidates.values()),ensure_ascii=False,indent=2),encoding="utf-8")\n''',
    '''        with (out/"excluded_rows.jsonl").open("w",encoding="utf-8") as f:\n            for row in excluded_rows: f.write(json.dumps(row,ensure_ascii=False)+"\\n")\n        with (out/"scope_rejected_rows.jsonl").open("w",encoding="utf-8") as f:\n            for row in scope_rejected_rows: f.write(json.dumps(row,ensure_ascii=False)+"\\n")\n        (out/"fact_candidates.json").write_text(json.dumps(list(candidates.values()),ensure_ascii=False,indent=2),encoding="utf-8")\n''',
)
replace(
    "collectors/soosiro_collect.py",
    '''        status.update({"status":"DATA_FOUND" if annual_rows else "NO_MATCH","annual_rows":len(annual_rows),"excluded_rows":len(excluded_rows),"fact_codes":len(candidates),"fact_code_list":sorted(candidates),"address_seeded_fact_codes":sorted(set(seeded_codes)),"daily_requests_success":daily_success,"daily_rows":len(daily_rows)})\n''',
    '''        status.update({"status":"DATA_FOUND" if annual_rows else "NO_MATCH","annual_rows":len(annual_rows),"scope_rejected_rows":len(scope_rejected_rows),"excluded_rows":len(excluded_rows),"fact_codes":len(candidates),"fact_code_list":sorted(candidates),"address_seeded_fact_codes":sorted(set(seeded_codes)),"daily_requests_success":daily_success,"daily_rows":len(daily_rows)})\n''',
)

print("identity-before-heavy-download patch complete")
