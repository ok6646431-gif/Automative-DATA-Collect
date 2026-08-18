import csv, json, tempfile, unittest
from pathlib import Path

from orchestrator.event_analysis import integrate_events, build_analysis_index


def write_csv(path,rows,fields):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


class TestEventAnalysis(unittest.TestCase):
    def make_package(self):
        td=tempfile.TemporaryDirectory(); root=Path(td.name)
        (root/"Integration_Summary.json").write_text(json.dumps({"company_id":"COMP_TEST"}),encoding="utf-8")
        (root/"REVIEW_REQUIRED.json").write_text("[]",encoding="utf-8")
        write_csv(root/"Validation_Queue.csv",[],["validation_id","company_id","object_type","object_key","issue_type","severity","detected_by","evidence","recommended_action","status","resolved_by","resolved_at","notes"])
        write_csv(root/"Site_Master.csv",[
            {"canonical_site_id":"SITE_A","identity_status":"CONFIRMED"}
        ],["canonical_site_id","identity_status"])
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
            ev.write_text(json.dumps({"discovery_status":"PARTIAL","events":[{"event_type":"INTEGRATED_PERMIT","event_scope":"SITE","canonical_site_id":"SITE_A","event_title":"permit"}]}),encoding="utf-8")
            summary=integrate_events(root,ev)
            events=list(csv.DictReader((root/"Event_Registry.csv").open(encoding="utf-8-sig")))
            issues={r["issue_type"] for r in csv.DictReader((root/"Validation_Queue.csv").open(encoding="utf-8-sig"))}
            self.assertEqual(summary["events"],1)
            self.assertEqual(events[0]["event_date_start"],"")
            self.assertIn("TRACEABILITY_GAP",issues)
            self.assertIn("EVENT_DATE_UNVERIFIED",issues)
        finally: td.cleanup()

    def test_definition_change_segments_and_checks_baseline(self):
        td,root=self.make_package()
        try:
            ev=root/"events.json"
            ev.write_text(json.dumps({"discovery_status":"COMPLETE","events":[{
                "event_type":"DISCLOSURE_DEFINITION_CHANGE","event_scope":"COMPANY","event_date_start":"2020-01-01",
                "event_title":"definition","source_key":"OFFICIAL_REPORT","source_locator":"official://report#p10","verification_status":"VERIFIED"
            }]}),encoding="utf-8")
            integrate_events(root,ev)
            links=list(csv.DictReader((root/"Coverage_Event_Links.csv").open(encoding="utf-8-sig")))
            self.assertTrue(all(x["comparability_action"]=="SEGMENT_AT_EVENT" for x in links))
            self.assertTrue(all(x["baseline_status"]=="BASELINE_MISSING" for x in links))
            issues={r["issue_type"] for r in csv.DictReader((root/"Validation_Queue.csv").open(encoding="utf-8-sig"))}
            self.assertIn("EVENT_BASELINE_MISSING",issues)
        finally: td.cleanup()

    def test_identity_event_does_not_modify_source_identity(self):
        td,root=self.make_package()
        try:
            before=(root/"Source_Identity.csv").read_bytes()
            ev=root/"events.json"
            ev.write_text(json.dumps({"discovery_status":"COMPLETE","events":[{
                "event_type":"SITE_IDENTITY_CHANGE","event_scope":"SITE","source_site_ref":{"source_key":"PRTR","source_site_id":"100"},
                "event_date_start":"2023-01-01","event_title":"rename","source_key":"OFFICIAL","source_locator":"official://rename","verification_status":"VERIFIED"
            }]}),encoding="utf-8")
            integrate_events(root,ev)
            self.assertEqual(before,(root/"Source_Identity.csv").read_bytes())
            links=list(csv.DictReader((root/"Coverage_Event_Links.csv").open(encoding="utf-8-sig")))
            self.assertEqual({x["comparability_action"] for x in links},{"REVIEW_IDENTITY_MAPPING"})
        finally: td.cleanup()

    def test_duplicate_event_id_only_fills_blank_fields(self):
        td,root=self.make_package()
        try:
            ev=root/"events.json"
            ev.write_text(json.dumps({"discovery_status":"COMPLETE","events":[
                {"event_id":"EVT_X","event_type":"FACILITY_EXPANSION","event_scope":"COMPANY","event_date_start":"2022-01-01","event_title":"A","source_key":"OFFICIAL","source_locator":"official://a","verification_status":"VERIFIED"},
                {"event_id":"EVT_X","event_type":"FACILITY_EXPANSION","event_scope":"COMPANY","event_date_start":"2022-01-01","event_title":"B","event_description":"filled later","source_key":"OFFICIAL","source_locator":"official://a","verification_status":"VERIFIED"}
            ]}),encoding="utf-8")
            integrate_events(root,ev)
            events=list(csv.DictReader((root/"Event_Registry.csv").open(encoding="utf-8-sig")))
            self.assertEqual(len(events),1)
            self.assertEqual(events[0]["event_title"],"A")
            self.assertEqual(events[0]["event_description"],"filled later")
        finally: td.cleanup()

    def test_analysis_index_is_reference_only(self):
        td,root=self.make_package()
        try:
            out=root/"output"/"PRTR"; out.mkdir(parents=True)
            write_csv(out/"discovery.csv",[{"entrps_id":"100","search_year":"2024","official_total":"999"}], ["entrps_id","search_year","official_total"])
            (root/"Coverage_Event_Links.csv").write_text("",encoding="utf-8")
            build_analysis_index(root)
            idx=list(csv.DictReader((root/"Analysis_Ready_Index.csv").open(encoding="utf-8-sig")))
            self.assertEqual(len(idx),1)
            self.assertEqual(idx[0]["raw_semantics"],"SOURCE_NATIVE_OFFICIAL_VALUES_NO_RECALC")
            self.assertNotIn("official_total",idx[0])
            raw=list(csv.DictReader((out/"discovery.csv").open(encoding="utf-8-sig")))
            self.assertEqual(raw[0]["official_total"],"999")
        finally: td.cleanup()


if __name__=="__main__": unittest.main()
