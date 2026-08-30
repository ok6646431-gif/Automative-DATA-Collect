import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

# archive_stage is intentionally executable both as a package module and as a script;
# add the orchestrator directory so its script-style sibling imports resolve here too.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))

from orchestrator.collection_completeness import audit_envinfo, audit_prtr, document_rows
from orchestrator.archive_stage import append_artifact_rows


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields=[]
    for row in rows:
        for key in row:
            if key not in fields: fields.append(key)
    if not fields: fields=["value"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)


class CollectionCompletenessTests(unittest.TestCase):
    def test_successful_empty_query_is_no_data_confirmed(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td); root=output/"ENVINFO"; (root/"raw_search").mkdir(parents=True)
            (root/"raw_search"/"2020_2020_기업_p1.json").write_text("{}", encoding="utf-8")
            write_json(root/"status.json", {"status":"NO_MATCH","rows":0})
            rows=audit_envinfo(output, {
                "start_year":2020,"end_year":2020,"search_terms":["기업"],
                "search_terms_by_year":{"2020":["기업"]},"collect_details":True,
            })
            self.assertEqual(rows[0]["completeness_state"], "NO_DATA_CONFIRMED")

    def test_selected_year_without_query_evidence_is_not_no_data(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td); root=output/"ENVINFO"; (root/"raw_search").mkdir(parents=True)
            write_json(root/"status.json", {"status":"NO_MATCH","rows":0})
            rows=audit_envinfo(output, {
                "start_year":2020,"end_year":2020,"search_terms":["기업"],
                "search_terms_by_year":{"2020":["기업"]},
            })
            self.assertEqual(rows[0]["completeness_state"], "UNQUERIED_PERIOD")

    def test_per_year_search_error_is_query_failed(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td); root=output/"PRTR"; (root/"raw_search").mkdir(parents=True)
            (root/"errors.log").write_text("SEARCH\t2021\t기업\t1\tTimeout\tfail\n", encoding="utf-8")
            write_json(root/"status.json", {"status":"DATA_FOUND","rows":0,"detail_ok":0})
            rows=audit_prtr(output, {
                "start_year":2021,"end_year":2021,"search_terms":[{"term":"기업","year_start":2021,"year_end":2021}],
            })
            self.assertEqual(rows[0]["completeness_state"], "QUERY_FAILED")

    def test_annual_documents_latest_three_do_not_satisfy_2020_2026_window(self):
        with tempfile.TemporaryDirectory() as td:
            package=Path(td); docs=package/"output"/"CORP_DOCS"; docs.mkdir(parents=True)
            evidence={"discovery_status":"COMPLETE","documents":[]}
            index=[]
            for year in [2024,2025,2026]:
                did=f"R{year}"; stored=f"output/CORP_DOCS/raw_documents/{year}.pdf"
                p=package/stored; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"%PDF-test")
                evidence["documents"].append({"document_id":did,"document_type":"SUSTAINABILITY_REPORT","report_year":year,"verification_status":"VERIFIED"})
                index.append({"document_id":did,"collection_status":"DOWNLOADED","stored_path":stored})
            write_csv(docs/"document_index.csv", index)
            rows=document_rows(package, {"requested_history_window":{"start_year":2020,"end_year":2026}}, evidence)
            missing=[r["period"] for r in rows if r["completeness_state"]=="DOCUMENT_DISCOVERY_MISSING"]
            self.assertEqual(missing, ["2020","2021","2022","2023"])

    def test_verified_not_published_gap_resolves_annual_year(self):
        with tempfile.TemporaryDirectory() as td:
            package=Path(td); docs=package/"output"/"CORP_DOCS"; docs.mkdir(parents=True)
            stored="output/CORP_DOCS/raw_documents/2022.pdf"; p=package/stored; p.parent.mkdir(parents=True); p.write_bytes(b"%PDF-test")
            write_csv(docs/"document_index.csv", [{"document_id":"R2022","collection_status":"DOWNLOADED","stored_path":stored}])
            evidence={
                "discovery_status":"COMPLETE",
                "documents":[{"document_id":"R2022","document_type":"SUSTAINABILITY_REPORT","report_year":2022,"verification_status":"VERIFIED"}],
                "gaps":[{"document_type":"SUSTAINABILITY_REPORT","year":2021,"verification_status":"VERIFIED","status":"NOT_PUBLISHED"}],
            }
            rows=document_rows(package, {"requested_history_window":{"start_year":2021,"end_year":2022}}, evidence)
            resolved=[r for r in rows if r["period"]=="2021"]
            self.assertEqual(resolved[0]["completeness_state"], "NO_DATA_CONFIRMED")

    def test_verified_declared_policy_download_failure_is_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            package=Path(td); docs=package/"output"/"CORP_DOCS"; docs.mkdir(parents=True)
            write_csv(docs/"document_index.csv", [{"document_id":"POLICY","collection_status":"DOWNLOAD_FAILED","stored_path":""}])
            evidence={"discovery_status":"COMPLETE","documents":[{
                "document_id":"POLICY","document_type":"ENVIRONMENTAL_POLICY",
                "verification_status":"VERIFIED","report_year":2025,
            }]}
            rows=document_rows(package, {}, evidence)
            self.assertEqual(rows[0]["completeness_state"], "DOCUMENT_DOWNLOAD_FAILED")

    def test_completeness_outputs_are_added_to_artifact_index(self):
        with tempfile.TemporaryDirectory() as td:
            package=Path(td)
            with (package/"Artifact_Index.csv").open("w", encoding="utf-8-sig", newline="") as f:
                w=csv.DictWriter(f, fieldnames=["source","path","bytes","sha256"]); w.writeheader()
            for name in ["Collection_Completeness.json","Collection_Completeness.csv","Collection_No_Data.csv"]:
                (package/name).write_text("test", encoding="utf-8")
            append_artifact_rows(package)
            with (package/"Artifact_Index.csv").open(encoding="utf-8-sig", newline="") as f:
                paths={r["path"] for r in csv.DictReader(f)}
            self.assertTrue({"Collection_Completeness.json","Collection_Completeness.csv","Collection_No_Data.csv"}.issubset(paths))

    def test_prtr_uses_collector_filename_normalization(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td); root=output/"PRTR"; (root/"raw_search").mkdir(parents=True)
            (root/"raw_search"/"2024_Samsung_Electronics_Co_Ltd_p1.html").write_text("ok", encoding="utf-8")
            write_json(root/"status.json", {"status":"NO_MATCH","rows":0,"detail_ok":0})
            rows=audit_prtr(output, {
                "start_year":2024,"end_year":2024,
                "search_terms":[{"term":"Samsung Electronics Co., Ltd.","year_start":2024,"year_end":2024}],
            })
            self.assertEqual(rows[0]["completeness_state"], "NO_DATA_CONFIRMED")

    def test_soosiro_uses_collector_filename_normalization(self):
        from orchestrator.collection_completeness import audit_soosiro
        with tempfile.TemporaryDirectory() as td:
            output=Path(td); root=output/"SOOSIRO_WATER"; (root/"raw_annual").mkdir(parents=True)
            (root/"raw_annual"/"2024_Samsung_Electronics_Co_Ltd.json").write_text("{}", encoding="utf-8")
            write_json(root/"status.json", {"status":"NO_MATCH","annual_rows":0,"errors":0})
            write_json(root/"fact_candidates.json", [])
            rows=audit_soosiro(output, {
                "annual_years":[2024],"daily_years":[],
                "search_terms":["Samsung Electronics Co., Ltd."],
            })
            self.assertEqual(rows[0]["completeness_state"], "NO_DATA_CONFIRMED")

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
            },ensure_ascii=False)+"\n",encoding="utf-8")
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
            },ensure_ascii=False)+"\n",encoding="utf-8")
            rows=audit_chem(output,{"years":[2020],"search_terms":["기업"],"collect_details":True})
            found=[r for r in rows if r["source"]=="CHEM_STATS_SOURCE_ID"]
            self.assertEqual(found[0]["completeness_state"],"NO_DATA_CONFIRMED")


if __name__ == "__main__":
    unittest.main()
