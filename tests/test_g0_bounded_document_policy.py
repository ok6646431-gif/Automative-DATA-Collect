import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.g0_bounded_document_policy import normalize
from collectors.corporate_docs_collect import collect


def evidence():
    return {
        "schema_version": "1.0",
        "request_id": "scope-1",
        "discovery_status": "PARTIAL",
        "documents": [],
        "gaps": [
            {
                "document_type": "SUSTAINABILITY_REPORT",
                "year": 2024,
                "status": "DISCOVERY_GAP",
                "blocking": True,
                "reason": "No verified annual report file was discovered within the bounded official-site crawl.",
            }
        ],
    }


def audit():
    pages = [
        "https://official.example/",
        "https://official.example/environment",
        "https://official.example/esg",
    ]
    return {"stages": {
        "official_site": {
            "dart_website": "https://official.example/",
            "pages_crawled": len(pages), "page_urls": pages,
        },
        "corporate_documents": {"report_candidates": []},
        "fresh_process_document_recovery": {"status": "NO_POSITIVE_RECOVERY"},
    }, "http_attempts": []}


class BoundedDiscoveryTests(unittest.TestCase):
    def test_ordinary_missing_year_is_uncertain_not_unpublished(self):
        docs = evidence()
        out = normalize({"company_verification_state": "VERIFIED"}, docs, audit())
        self.assertEqual(out["discovery_status"], "COMPLETE_FOR_BOUNDED_OFFICIAL_DISCOVERY")
        self.assertEqual(out["gaps"][0]["status"], "NOT_FOUND_IN_BOUNDED_SCOPE")
        self.assertEqual(out["gaps"][0]["verification_status"], "UNVERIFIED")
        self.assertFalse(out["gaps"][0]["blocking"])
        self.assertEqual(out["discovery_scope"]["official_pages_checked"], 3)

    def test_no_verified_first_party_crawl_is_not_accepted(self):
        a = audit()
        a["stages"]["official_site"]["page_urls"] = []
        docs = evidence()
        out = normalize({"company_verification_state": "VERIFIED"}, docs, a)
        self.assertEqual(out["discovery_status"], "PARTIAL")
        self.assertTrue(out["gaps"][0]["blocking"])

    def test_positive_report_candidate_stays_blocking(self):
        a = audit()
        a["stages"]["corporate_documents"]["report_candidates"] = [{"year": 2024}]
        docs = evidence()
        out = normalize({"company_verification_state": "VERIFIED"}, docs, a)
        self.assertEqual(out["discovery_status"], "PARTIAL")

    def test_known_published_report_without_download_stays_blocking(self):
        docs = evidence()
        docs["gaps"][0]["status"] = "PUBLISHED_DOCUMENT_TARGET_UNRESOLVED"
        out = normalize({"company_verification_state": "VERIFIED"}, docs, audit())
        self.assertEqual(out["discovery_status"], "PARTIAL")

    def test_external_pages_do_not_count_as_first_party(self):
        a = audit()
        a["stages"]["official_site"]["page_urls"][1] = "https://unrelated.example/environment"
        docs = evidence()
        out = normalize({"company_verification_state": "VERIFIED"}, docs, a)
        self.assertEqual(out["discovery_status"], "PARTIAL")

    def test_collector_preserves_evidence_for_zero_document_case(self):
        docs = normalize({"company_verification_state": "VERIFIED"}, evidence(), audit())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d = root / "docs.json"
            p = root / "profile.json"
            d.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
            p.write_text(json.dumps({
                "request_id": "scope-1", "company_id": "TEST_ENTITY"
            }), encoding="utf-8")
            out_dir = root / "CORP_DOCS"
            result = collect(d, p, out_dir=str(out_dir))
            self.assertEqual(result["status"], "NO_DOCUMENTS_FOUND_IN_SCOPE")
            self.assertTrue((out_dir / "document_index.csv").is_file())
            self.assertTrue((out_dir / "discovery_scope.json").is_file())

    def test_request_mismatch_is_not_reinterpreted_as_nonpublication(self):
        docs = normalize({"company_verification_state": "VERIFIED"}, evidence(), audit())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d = root / "docs.json"; p = root / "profile.json"
            d.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
            p.write_text(json.dumps({
                "request_id": "another-request", "company_id": "TEST_ENTITY"
            }), encoding="utf-8")
            result = collect(d, p, out_dir=str(root / "CORP_DOCS"))
            self.assertEqual(result["status"], "INVALID_SCOPE")


if __name__ == "__main__":
    unittest.main()
