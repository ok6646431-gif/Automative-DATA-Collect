import csv
import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.collection_completeness import audit_envinfo, audit_prtr, document_rows


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


if __name__ == "__main__":
    unittest.main()
