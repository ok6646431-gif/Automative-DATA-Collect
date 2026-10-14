import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orchestrator import source_snapshot_recovery as m


class PRTRSnapshotRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.current = self.root / "current/PRTR"
        self.old = self.root / "archived/PRTR"
        self.current.mkdir(parents=True)
        self.old.mkdir(parents=True)
        (self.current / "status.json").write_text(
            json.dumps({"source_key":"PRTR","status":"REMOTE_HOST_UNREACHABLE","rows":0}),
            encoding="utf-8")
        (self.old / "status.json").write_text(
            json.dumps({
                "source_key":"PRTR","status":"DATA_FOUND","errors":0,"rows":5,
                "detail_ok":5,"detail_fail":0,"detail_table_rows":10
            }),encoding="utf-8")
        self.cur_req=self.root/"current.json"
        self.old_req=self.root/"archive_request.json"
        self.acceptance=self.root/"acceptance.json"
        self.now=datetime(2026,10,15,3,0,tzinfo=timezone.utc)
        self.snapshot_time=(self.now-timedelta(days=1)).isoformat()
        self._request(self.cur_req)
        self._request(self.old_req)
        self.acceptance.write_text(json.dumps({"status":"PASS","blocking_issues":[]}),encoding="utf-8")
        with (self.old/"discovery.csv").open("w",encoding="utf-8-sig",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=[
                "search_year","entrps_id","company_name_raw","address_raw","match_status"])
            writer.writeheader()
            for year in range(2020,2025):
                writer.writerow({
                    "search_year":year,"entrps_id":"1021","company_name_raw":"S-OIL 온산공장",
                    "address_raw":"울산 울주군 온산읍 온산로 68",
                    "match_status":"UNRESOLVED",
                })
        details=self.old/"raw_detail"
        details.mkdir()
        with (self.old/"detail_table_rows.jsonl").open("w",encoding="utf-8") as f:
            for year in range(2020,2025):
                for index in range(2):
                    f.write(json.dumps({
                        "search_year":year,"entrps_id":"1021","cells":["배출량","12"],
                        "row_index":index
                    })+"\n")
                (details/f"{year}_1021.html").write_text("<html>"+("data"*1600)+"</html>",
                                                              encoding="utf-8")

    def _request(self,path,*,company="S-OIL(주)",years=(2020,2024),
                 site="울산광역시 울주군 온산읍 온산로 68"):
        obj={
            "company_display_name":company,"sources":{"PRTR":{
                "start_year":years[0],"end_year":years[1],
                "identity_gate":{"enabled":True,
                                 "current_entity_names":[company],
                                 "verified_sites":[{"site_name":"온산공장","address":site}],
                                 "address_only_is_sufficient":False},
            }},
        }
        path.write_text(json.dumps(obj,ensure_ascii=False),encoding="utf-8")

    def check(self):
        return m.validate(self.current,self.old,self.cur_req,self.old_req,
                          self.acceptance,run_id="38417731063",
                          collected_at=self.snapshot_time,now=self.now)

    def test_recover_original_with_full_sha_and_provenance(self):
        report=self.check()
        self.assertEqual("VERIFIED_ORIGINAL_SNAPSHOT_REUSED",report["recovery_status"])
        self.assertEqual([2020,2021,2022,2023,2024],report["source_years"])
        self.assertEqual(["1021"],report["source_native_ids"])
        final=m.recover(self.current,self.old,self.cur_req,self.old_req,self.acceptance,
                        run_id="38417731063",collected_at=self.snapshot_time,now=self.now)
        saved=m.load(self.current/"source_snapshot_recovery.json")
        self.assertEqual(saved["original_files_sha256"],final["original_files_sha256"])
        self.assertEqual("UNRESOLVED",m._rows(self.current/"discovery.csv")[0]["match_status"])
        self.assertTrue((self.root/"current/PRTR.failed_fetch/status.json").exists())
        self.assertEqual("REMOTE_HOST_UNREACHABLE",
                         m.load(self.root/"current/PRTR.failed_fetch/status.json")["status"])

    def test_never_overwrites_non_outage_or_partial_current_data(self):
        p=self.current/"status.json"
        p.write_text('{"status":"DATA_FOUND","rows":5}',encoding="utf-8")
        with self.assertRaisesRegex(m.SnapshotRejected,"NOT_AN_EXPLICIT"):
            self.check()
        p.write_text('{"status":"REMOTE_HOST_UNREACHABLE","rows":1}',encoding="utf-8")
        with self.assertRaisesRegex(m.SnapshotRejected,"PARTIAL_CURRENT"):
            self.check()

    def test_reject_wrong_company_or_verified_site_or_years(self):
        for opt in [
            {"company":"다른법인"},
            {"site":"울산 울주군 산업로 999"},
            {"years":(2021,2024)},
        ]:
            with self.subTest(opt=opt):
                self._request(self.old_req,**opt)
                with self.assertRaisesRegex(m.SnapshotRejected,"MISMATCH"):
                    self.check()
                self._request(self.old_req)

    def test_reject_unaccepted_or_incomplete_original(self):
        self.acceptance.write_text('{"status":"REVIEW_REQUIRED"}',encoding="utf-8")
        with self.assertRaisesRegex(m.SnapshotRejected,"NOT_PASS"):
            self.check()
        self.acceptance.write_text('{"status":"PASS","blocking_issues":[]}',encoding="utf-8")
        (self.old/"detail_table_rows.jsonl").write_text("",encoding="utf-8")
        with self.assertRaisesRegex(m.SnapshotRejected,"DETAIL_ROW_NOT_FOUND"):
            self.check()

    def test_reject_expired_evidence_even_when_original_is_complete(self):
        with self.assertRaisesRegex(m.SnapshotRejected,"TOO_OLD"):
            m.validate(self.current,self.old,self.cur_req,self.old_req,self.acceptance,
                       run_id="38417731063",collected_at="2025-01-01T00:00:00Z",
                       now=self.now)

    def test_failed_snapshot_never_creates_user_delivery(self):
        (self.old/"status.json").write_text(
            '{"status":"DATA_FOUND","errors":1,"rows":5,"detail_ok":5,"detail_fail":0}',
            encoding="utf-8")
        with self.assertRaisesRegex(m.SnapshotRejected,"NOT_COMPLETE"):
            m.recover(self.current,self.old,self.cur_req,self.old_req,self.acceptance,
                      run_id="38417731063",collected_at=self.snapshot_time,now=self.now)
        self.assertFalse((self.current/"source_snapshot_recovery.json").exists())
        self.assertEqual("REMOTE_HOST_UNREACHABLE",m.load(self.current/"status.json")["status"])


if __name__=="__main__":
    unittest.main()
