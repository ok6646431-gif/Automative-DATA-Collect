import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.icis_replay import (
    FRESH_FRESHNESS,
    REPLAY_FRESHNESS,
    _candidate_source_complete,
    _pick_current_sources,
    source_fingerprint,
    stamp_artifact,
)


def request_fixture():
    return {
        "company_display_name": "금호석유화학주식회사",
        "sources": {
            "PRTR": {
                "start_year": 2020,
                "end_year": 2024,
                "search_terms": [
                    {"term": "금호석유화학", "year_start": 2020, "year_end": 2024},
                    {"term": "금호석유화학(주)", "year_start": 2020, "year_end": 2024},
                ],
                "exclude_terms": ["금호피앤비화학", "금호미쓰이화학"],
                "site_address_anchors": {
                    "site-b": ["전남 여수시 B", "전라남도 여수시 B"],
                    "site-a": ["울산 남구 A"],
                },
                "max_pages": 50,
                "collect_details": True,
                "request_delay_ms": 80,
            },
            "CHEM_STATS": {
                "years": [2024, 2020, 2022],
                "search_terms": ["KKPC", "금호석유화학"],
                "search_terms_by_year": {"2024": ["KKPC", "금호석유화학"]},
                "exclude_terms": ["금호피앤비화학"],
                "max_pages": 10,
                "collect_details": True,
                "request_delay_ms": 80,
            },
        },
    }


def write_source(root: Path, source: str, status: dict, with_discovery=True, with_detail=True):
    d = root / source
    d.mkdir(parents=True, exist_ok=True)
    (d / "status.json").write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    if with_discovery:
        (d / "discovery.csv").write_text("search_year,id\n2024,1\n", encoding="utf-8")
    if with_detail:
        raw = d / "raw_detail"
        raw.mkdir(exist_ok=True)
        (raw / "2024_1.html").write_text("x" * 100, encoding="utf-8")


class ICISReplayTests(unittest.TestCase):
    def test_prtr_fingerprint_ignores_order_and_delay(self):
        a = request_fixture()
        b = request_fixture()
        b["sources"]["PRTR"]["search_terms"].reverse()
        b["sources"]["PRTR"]["exclude_terms"].reverse()
        b["sources"]["PRTR"]["site_address_anchors"] = {
            "site-a": ["울산 남구 A"],
            "site-b": ["전라남도 여수시 B", "전남 여수시 B"],
        }
        b["sources"]["PRTR"]["request_delay_ms"] = 999
        self.assertEqual(source_fingerprint(a, "PRTR"), source_fingerprint(b, "PRTR"))

    def test_prtr_fingerprint_changes_when_query_scope_changes(self):
        a = request_fixture()
        b = request_fixture()
        b["sources"]["PRTR"]["end_year"] = 2025
        self.assertNotEqual(source_fingerprint(a, "PRTR"), source_fingerprint(b, "PRTR"))

    def test_chem_fingerprint_normalizes_order_but_not_years(self):
        a = request_fixture()
        b = request_fixture()
        b["sources"]["CHEM_STATS"]["years"] = [2022, 2024, 2020]
        b["sources"]["CHEM_STATS"]["search_terms"].reverse()
        b["sources"]["CHEM_STATS"]["request_delay_ms"] = 900
        self.assertEqual(source_fingerprint(a, "CHEM_STATS"), source_fingerprint(b, "CHEM_STATS"))
        b["sources"]["CHEM_STATS"]["years"].append(2026)
        self.assertNotEqual(source_fingerprint(a, "CHEM_STATS"), source_fingerprint(b, "CHEM_STATS"))

    def test_candidate_rejects_replayed_chain(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            st = {"source_key": "PRTR", "status": "DATA_FOUND", "detail_ok": 1, "freshness": REPLAY_FRESHNESS}
            write_source(root, "PRTR", st)
            ok, reason = _candidate_source_complete(root, "PRTR", st)
            self.assertFalse(ok)
            self.assertEqual(reason, "candidate_is_already_replayed")

    def test_data_found_requires_discovery_and_declared_details(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            st = {"source_key": "PRTR", "status": "DATA_FOUND", "detail_ok": 1}
            write_source(root, "PRTR", st, with_discovery=False, with_detail=False)
            ok, reason = _candidate_source_complete(root, "PRTR", st)
            self.assertFalse(ok)
            self.assertEqual(reason, "data_found_without_discovery")
            (root / "PRTR" / "discovery.csv").write_text("search_year,id\n2024,1\n", encoding="utf-8")
            ok, reason = _candidate_source_complete(root, "PRTR", st)
            self.assertFalse(ok)
            self.assertEqual(reason, "detail_ok_without_raw_detail")

    def test_pick_current_sources_is_source_by_source_and_latest(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            attempts = base / "attempts"
            out = base / "out"
            a1 = attempts / "icis-attempt-1" / "output"
            a2 = attempts / "icis-attempt-2" / "output"
            write_source(a1, "PRTR", {"source_key": "PRTR", "status": "DATA_FOUND", "detail_ok": 0})
            write_source(a1, "CHEM_STATS", {"source_key": "CHEM_STATS", "status": "REMOTE_HOST_UNREACHABLE"}, with_discovery=False, with_detail=False)
            write_source(a2, "PRTR", {"source_key": "PRTR", "status": "REMOTE_HOST_UNREACHABLE"}, with_discovery=False, with_detail=False)
            write_source(a2, "CHEM_STATS", {"source_key": "CHEM_STATS", "status": "DATA_FOUND", "detail_ok": 0})
            out.mkdir()
            good, _ = _pick_current_sources(attempts, out)
            self.assertEqual(good, {"PRTR": True, "CHEM_STATS": True})
            self.assertEqual(json.loads((out / "PRTR" / "status.json").read_text(encoding="utf-8"))["current_attempt"], "icis-attempt-1")
            self.assertEqual(json.loads((out / "CHEM_STATS" / "status.json").read_text(encoding="utf-8"))["current_attempt"], "icis-attempt-2")
            self.assertEqual(json.loads((out / "PRTR" / "status.json").read_text(encoding="utf-8"))["freshness"], FRESH_FRESHNESS)

    def test_stamp_artifact_preserves_exact_request_and_fingerprints(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            req = request_fixture()
            req_path = root / "request.json"
            req_path.write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")
            write_source(root / "output", "PRTR", {"source_key": "PRTR", "status": "DATA_FOUND", "detail_ok": 0})
            write_source(root / "output", "CHEM_STATS", {"source_key": "CHEM_STATS", "status": "DATA_FOUND", "detail_ok": 0})
            manifest = stamp_artifact(req_path, root / "output", "123", "abc", "icis-attempt-1")
            cached = json.loads((root / "output" / "_replay" / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(cached, req)
            self.assertEqual(manifest["origin_run_id"], "123")
            self.assertEqual(manifest["sources"]["PRTR"]["query_fingerprint"], source_fingerprint(req, "PRTR"))
            self.assertEqual(manifest["sources"]["CHEM_STATS"]["query_fingerprint"], source_fingerprint(req, "CHEM_STATS"))


if __name__ == "__main__":
    unittest.main()
