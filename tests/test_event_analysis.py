import csv, json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"orchestrator"))
from event_analysis import integrate_events, build_analysis_index


def write_csv(path,rows,fields):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def event_doc(events=None,gaps=None,request_id="REQ_TEST",status="COMPLETE"):
    return {"schema_version":"1.0","request_id":request_id,"discovery_status":status,"events":events or [],"gaps":gaps or []}


class TestEventAnalysis(unittest.TestCase):
    def make_package(self):
        td=tempfile.TemporaryDirectory(); root=Path(td.name)
        (root/"Integration_Summary.json").write_text(json.dumps({"company_id":"COMP_TEST"}),encoding="utf-8")
        (root/"Company_Profile.json").write_text(json.dumps({"request_id":"REQ_TEST","company_display_name":"테스트"}),encoding="utf-8")
        (root/"REVIEW_REQUIRED.json").write_text("[]",encoding="utf-8")
        write_csv(root/"Validation_Queue.csv",[],["validation_id","company_id","object_type","object_key","issue_type","severity","detected_by","evidence","recommended_action","status","resolved_by","resolved_at","notes"])
        write_csv(root/"Site_Master.csv",[{"canonical_site_id":"SITE_A","identity_status":"CONFIRMED"}],["canonical_site_id","identity_status"])
        write_csv(root/"Source_Identity.csv",[
            {"source_key":"PRTR","source_site_id":"100","canonical_site_id":"SITE_A","match_status":"CONFIRMED"},
            {"source_key":"ENVINFO","source_site_id":"200","canonical_site_id":"SITE_A","match_status":"CONFIRMED"}
        ],["source_key","source_site_id","canonical_site_id","match_status"])
        cov=[]
        for source in ["ENVINFO","PRTR","CHEM_STATS","CLEANSYS_AIR","SOOSIRO_WATER"]:
            cov.append({"company_id":"COMP_TEST","source_key":source,"coverage_scope":"test","available_start":"UNKNOWN","available_end":"UNKNOWN","collected_start":"2020","collected_end":"2024","rounds_or_detail":"","meets_minimum":"True","event_baseline_status":"PENDING_EVENT_LINK","comparability_status":"PENDING","coverage_status":"MEETS_MINIMUM","next_action":""})
        write_csv(root/"Coverage_Status.csv",cov,list(cov[0].keys()))
        return td,root

    def test_missing_locator_and_date_are_review_not_inferred(self):
        td,root=self.make_package()
        try:
            ev=root/"events.json"
            ev.write_text(json.dumps(event_doc([{"event_type":"INTEGRATED_PERMIT","event_scope":"SITE","canonical_site_id":"SITE_A","event_title":"permit"}],status="PARTIAL")),encoding="utf-8")
            summary=integrate_events(root,ev)
            with (root/"Event_Registry.csv").open(encoding="utf-8-sig") as f: events=list(csv.DictReader(f))
            with (root/"Validation_Queue.csv").open(encoding="utf-8-sig") as f: issues={r["issue_type"] for r in csv.DictReader(f)}
            self.assertEqual(summary["events"],1); self.assertEqual(events[0]["event_date_start"],"")
            self.assertIn("TRACEABILITY_GAP",issues); self.assertIn("EVENT_DATE_UNVERIFIED",issues)
        finally: td.cleanup()

    def test_definition_change_segments_and_checks_baseline(self):
        td,root=self.make_package()
        try:
            ev=root/"events.json"
            ev.write_text(json.dumps(event_doc([{"event_type":"DISCLOSURE_DEFINITION_CHANGE","event_scope":"COMPANY","event_date_start":"2020-01-01","event_title":"definition","source_key":"OFFICIAL_REPORT","source_locator":"official://report#p10","verification_status":"VERIFIED"}])),encoding="utf-8")
            integrate_events(root,ev)
            with (root/"Coverage_Event_Links.csv").open(encoding="utf-8-sig") as f: links=list(csv.DictReader(f))
            self.assertTrue(all(x["comparability_action"]=="SEGMENT_AT_EVENT" for x in links)); self.assertTrue(all(x["baseline_status"]=="BASELINE_MISSING" for x in links))
            with (root/"Validation_Queue.csv").open(encoding="utf-8-sig") as f: issues={r["issue_type"] for r in csv.DictReader(f)}
            self.assertIn("EVENT_BASELINE_MISSING",issues)
        finally: td.cleanup()

    def test_identity_event_does_not_modify_source_identity_and_blocks_analysis(self):
        td,root=self.make_package()
        try:
            with (root/"Coverage_Status.csv").open(encoding="utf-8-sig") as f: coverage=list(csv.DictReader(f))
            for row in coverage:
                if row["source_key"]=="PRTR": row["comparability_status"]="SURVEY_ROUND"
            write_csv(root/"Coverage_Status.csv",coverage,list(coverage[0]))
            out=root/"output"/"PRTR"; out.mkdir(parents=True)
            write_csv(out/"discovery.csv",[{"entrps_id":"100","search_year":"2024"}],["entrps_id","search_year"])

            before=(root/"Source_Identity.csv").read_bytes(); ev=root/"events.json"
            ev.write_text(json.dumps(event_doc([{"event_type":"SITE_IDENTITY_CHANGE","event_scope":"SITE","source_site_ref":{"source_key":"PRTR","source_site_id":"100"},"event_date_start":"2023-01-01","event_title":"rename","source_key":"OFFICIAL","source_locator":"official://rename","verification_status":"VERIFIED"}])),encoding="utf-8")
            integrate_events(root,ev)
            self.assertEqual(before,(root/"Source_Identity.csv").read_bytes())
            with (root/"Coverage_Event_Links.csv").open(encoding="utf-8-sig") as f: links=list(csv.DictReader(f))
            self.assertEqual({x["comparability_action"] for x in links},{"REVIEW_IDENTITY_MAPPING"})
            with (root/"Coverage_Status.csv").open(encoding="utf-8-sig") as f: coverage_after={r["source_key"]:r for r in csv.DictReader(f)}
            self.assertIn("IDENTITY_EVENT_REVIEW",coverage_after["PRTR"]["comparability_status"])

            build_analysis_index(root)
            with (root/"Analysis_Ready_Index.csv").open(encoding="utf-8-sig") as f: idx=list(csv.DictReader(f))
            self.assertEqual(idx[0]["analysis_readiness"],"COMPARABILITY_REVIEW")
            self.assertEqual(idx[0]["analysis_eligible"],"False")
        finally: td.cleanup()

    def test_stale_event_evidence_is_blocked_by_request_id(self):
        td,root=self.make_package()
        try:
            ev=root/"events.json"
            ev.write_text(json.dumps(event_doc([
                {"event_id":"EVT_STALE","event_type":"CORPORATE_RESTRUCTURE","event_scope":"COMPANY","event_date_start":"2024-01-01","event_title":"belongs to another company","source_key":"OFFICIAL","source_locator":"official://stale","verification_status":"VERIFIED"}
            ],request_id="REQ_OTHER")),encoding="utf-8")
            summary=integrate_events(root,ev)
            self.assertEqual(summary["event_discovery_status"],"INVALID_SCOPE")
            self.assertEqual(summary["events"],0); self.assertEqual(summary["event_links"],0)
            with (root/"Event_Registry.csv").open(encoding="utf-8-sig") as f: self.assertEqual(list(csv.DictReader(f)),[])
            with (root/"Coverage_Event_Links.csv").open(encoding="utf-8-sig") as f: self.assertEqual(list(csv.DictReader(f)),[])
            with (root/"Validation_Queue.csv").open(encoding="utf-8-sig") as f: rows=list(csv.DictReader(f))
            scope=[r for r in rows if r["issue_type"]=="EVENT_EVIDENCE_SCOPE_MISMATCH"]
            self.assertEqual(len(scope),1)
            self.assertIn("expected_request_id=REQ_TEST",scope[0]["evidence"])
            self.assertIn("supplied_request_id=REQ_OTHER",scope[0]["evidence"])
        finally: td.cleanup()

    def test_unscoped_event_evidence_is_blocked(self):
        td,root=self.make_package()
        try:
            ev=root/"events.json"
            raw=event_doc([{"event_type":"FACILITY_EXPANSION","event_scope":"COMPANY","event_date_start":"2024-01-01","source_locator":"official://x","verification_status":"VERIFIED"}])
            raw.pop("request_id")
            ev.write_text(json.dumps(raw),encoding="utf-8")
            summary=integrate_events(root,ev)
            self.assertEqual(summary["event_discovery_status"],"INVALID_SCOPE")
            self.assertEqual(summary["events"],0)
            with (root/"Validation_Queue.csv").open(encoding="utf-8-sig") as f: issues={r["issue_type"] for r in csv.DictReader(f)}
            self.assertIn("EVENT_EVIDENCE_SCOPE_MISMATCH",issues)
        finally: td.cleanup()

    def test_duplicate_event_id_only_fills_blank_fields(self):
        td,root=self.make_package()
        try:
            ev=root/"events.json"
            ev.write_text(json.dumps(event_doc([
                {"event_id":"EVT_X","event_type":"FACILITY_EXPANSION","event_scope":"COMPANY","event_date_start":"2022-01-01","event_title":"A","source_key":"OFFICIAL","source_locator":"official://a","verification_status":"VERIFIED"},
                {"event_id":"EVT_X","event_type":"FACILITY_EXPANSION","event_scope":"COMPANY","event_date_start":"2022-01-01","event_title":"B","event_description":"filled later","source_key":"OFFICIAL","source_locator":"official://a","verification_status":"VERIFIED"}
            ])),encoding="utf-8")
            integrate_events(root,ev)
            with (root/"Event_Registry.csv").open(encoding="utf-8-sig") as f: events=list(csv.DictReader(f))
            self.assertEqual(len(events),1); self.assertEqual(events[0]["event_title"],"A"); self.assertEqual(events[0]["event_description"],"filled later")
        finally: td.cleanup()

    def test_analysis_index_is_reference_only(self):
        td,root=self.make_package()
        try:
            out=root/"output"/"PRTR"; out.mkdir(parents=True)
            write_csv(out/"discovery.csv",[{"entrps_id":"100","search_year":"2024","official_total":"999"}],["entrps_id","search_year","official_total"])
            (root/"Coverage_Event_Links.csv").write_text("",encoding="utf-8")
            build_analysis_index(root)
            with (root/"Analysis_Ready_Index.csv").open(encoding="utf-8-sig") as f: idx=list(csv.DictReader(f))
            self.assertEqual(len(idx),1); self.assertEqual(idx[0]["raw_semantics"],"SOURCE_NATIVE_OFFICIAL_VALUES_NO_RECALC"); self.assertNotIn("official_total",idx[0])
            with (out/"discovery.csv").open(encoding="utf-8-sig") as f: raw=list(csv.DictReader(f))
            self.assertEqual(raw[0]["official_total"],"999")
        finally: td.cleanup()


if __name__=="__main__": unittest.main()
