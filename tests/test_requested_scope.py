import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
from requested_scope import apply_requested_scope, resolve_requested_scope


def write_csv(path, rows, fields):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)


class RequestedScopeTests(unittest.TestCase):
    def make_package(self):
        td = tempfile.TemporaryDirectory(); root = Path(td.name)
        profile = {
            "company_display_name": "테스트전자 주식회사",
            "requested_company_name": "테스트전자(반도체)",
            "requested_scope": {"mode": "SITE_SET", "label": "반도체", "candidate_ids": ["A", "B"]},
            "aliases": [{"term": "테스트전자"}, {"term": "테스트전자(주)"}],
            "site_candidates": [
                {"candidate_id": "A", "site_name_raw": "기흥", "address_raw": "경기도 용인시 기흥구 삼성로 1", "identity_status": "CONFIRMED", "verification_state": "VERIFIED"},
                {"candidate_id": "B", "site_name_raw": "온양", "address_raw": "충청남도 아산시 배방읍 배방로 158", "identity_status": "CONFIRMED", "verification_state": "VERIFIED"},
            ],
        }
        (root / "Company_Profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
        write_csv(root / "Site_Master.csv", [
            {"canonical_site_id": "SITE_A", "canonical_site_name": "테스트전자(주) 기흥사업장", "canonical_address_key": "경기용인시기흥구삼성로1", "identity_status": "CONFIRMED"},
            {"canonical_site_id": "SITE_B", "canonical_site_name": "테스트전자(주) 온양사업장", "canonical_address_key": "충남아산시배방읍배방로158", "identity_status": "CONFIRMED"},
            {"canonical_site_id": "SITE_X", "canonical_site_name": "테스트전자(주) 수원사업장", "canonical_address_key": "경기수원시영통구테스트로1", "identity_status": "CONFIRMED"},
        ], ["canonical_site_id", "canonical_site_name", "canonical_address_key", "identity_status"])
        write_csv(root / "Source_Identity.csv", [
            {"source_key": "CHEM_STATS", "source_site_id": "CHEM_A", "canonical_site_id": "SITE_A", "source_site_name_raw": "테스트전자 주식회사 기흥사업장", "source_address_raw": "경기도 용인시 기흥구 삼성로 1", "match_status": "CONFIRMED"},
            {"source_key": "CHEM_STATS", "source_site_id": "CHEM_B", "canonical_site_id": "CAND_B", "source_site_name_raw": "테스트전자(주)", "source_address_raw": "충청남도 아산시 배방읍 배방로 158", "match_status": "REVIEW_REQUIRED"},
            {"source_key": "CHEM_STATS", "source_site_id": "CHEM_X", "canonical_site_id": "CAND_X", "source_site_name_raw": "테스트전자(주)", "source_address_raw": "경기도 수원시 영통구 테스트로 1", "match_status": "REVIEW_REQUIRED"},
            {"source_key": "PRTR", "source_site_id": "PRTR_A", "canonical_site_id": "SITE_A", "source_site_name_raw": "테스트전자 기흥", "source_address_raw": "경기도 용인시 기흥구 삼성로 1", "match_status": "CONFIRMED"},
        ], ["source_key", "source_site_id", "canonical_site_id", "source_site_name_raw", "source_address_raw", "match_status"])
        write_csv(root / "Analysis_Ready_Index.csv", [
            {"analysis_id": "1", "canonical_site_id": "SITE_A", "source_key": "PRTR", "source_site_id": "PRTR_A", "event_link_ids": "", "analysis_readiness": "READY"},
            {"analysis_id": "2", "canonical_site_id": "", "source_key": "CHEM_STATS", "source_site_id": "CHEM_B", "event_link_ids": "", "analysis_readiness": "IDENTITY_REVIEW"},
            {"analysis_id": "3", "canonical_site_id": "", "source_key": "CHEM_STATS", "source_site_id": "CHEM_X", "event_link_ids": "", "analysis_readiness": "IDENTITY_REVIEW"},
        ], ["analysis_id", "canonical_site_id", "source_key", "source_site_id", "event_link_ids", "analysis_readiness"])
        write_csv(root / "Coverage_Event_Links.csv", [
            {"link_id": "L_COMPANY", "source_key": "PRTR", "canonical_site_id": ""},
            {"link_id": "L_SITE", "source_key": "PRTR", "canonical_site_id": "SITE_A"},
        ], ["link_id", "source_key", "canonical_site_id"])
        return td, root

    def test_company_only_name_never_matches_every_site(self):
        td, root = self.make_package()
        try:
            scope = resolve_requested_scope(root)
            self.assertIn("CHEM_A", scope["target_source_ids"]["CHEM_STATS"])
            self.assertIn("CHEM_B", scope["target_source_ids"]["CHEM_STATS"])
            self.assertNotIn("CHEM_X", scope["target_source_ids"]["CHEM_STATS"])
            self.assertEqual(scope["target_canonical_site_ids"], {"SITE_A", "SITE_B"})
        finally:
            td.cleanup()

    def test_analysis_view_filters_non_target_and_inherits_company_events(self):
        td, root = self.make_package()
        try:
            summary = apply_requested_scope(root)
            self.assertEqual(summary["analysis_rows_before"], 3)
            self.assertEqual(summary["analysis_rows_after"], 2)
            with (root / "Analysis_Ready_Index.csv").open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            by_id = {r["analysis_id"]: r for r in rows}
            self.assertEqual(set(by_id), {"1", "2"})
            self.assertEqual(by_id["1"]["event_link_ids"], "L_COMPANY|L_SITE")
            self.assertTrue((root / "Requested_Scope.json").exists())
            self.assertTrue((root / "Analysis_Scope.csv").exists())
        finally:
            td.cleanup()

    def test_colocated_official_units_require_name_evidence(self):
        td = tempfile.TemporaryDirectory(); root = Path(td.name)
        try:
            profile = {
                "company_display_name": "테스트화학 주식회사",
                "requested_scope": {"mode": "SITE_SET", "label": "생산공장", "candidate_ids": ["R", "L"]},
                "aliases": [{"term": "테스트화학"}],
                "site_candidates": [
                    {"candidate_id": "R", "site_name_raw": "울산고무공장", "address_raw": "울산광역시 남구 상개로 64", "identity_status": "CONFIRMED", "verification_state": "VERIFIED"},
                    {"candidate_id": "L", "site_name_raw": "울산 LATEX공장", "address_raw": "울산광역시 남구 상개로 64", "identity_status": "CONFIRMED", "verification_state": "VERIFIED"},
                ],
            }
            (root / "Company_Profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            write_csv(root / "Site_Master.csv", [
                {"canonical_site_id": "SITE_R", "canonical_site_name": "테스트화학 울산고무", "canonical_address_key": "울산남구상개로64", "identity_status": "CONFIRMED"},
            ], ["canonical_site_id", "canonical_site_name", "canonical_address_key", "identity_status"])
            write_csv(root / "Source_Identity.csv", [
                {"source_key": "PRTR", "source_site_id": "R1", "canonical_site_id": "SITE_R", "source_site_name_raw": "테스트화학 울산고무공장", "source_address_raw": "울산광역시 남구 상개로 64", "match_status": "CONFIRMED"},
            ], ["source_key", "source_site_id", "canonical_site_id", "source_site_name_raw", "source_address_raw", "match_status"])
            scope = resolve_requested_scope(root)
            self.assertEqual(scope["target_canonical_site_ids"], {"SITE_R"})
            unresolved = {x["candidate_id"]: x for x in scope["unresolved_candidates"]}
            self.assertNotIn("R", unresolved)
            self.assertEqual(unresolved["L"]["reason"], "COLOCATED_OFFICIAL_UNIT_NOT_DISTINCTLY_CONFIRMED")
            self.assertIn("R1", scope["target_source_ids"]["PRTR"])
        finally:
            td.cleanup()

    def test_same_address_related_entity_is_not_requested_scope(self):
        td = tempfile.TemporaryDirectory(); root = Path(td.name)
        try:
            profile = {
                "company_display_name": "테스트산업 주식회사",
                "requested_company_name": "테스트산업",
                "requested_scope": {"mode": "SITE_SET", "label": "제철소", "candidate_ids": ["P"]},
                "aliases": [
                    {"term": "테스트산업 주식회사", "alias_type": "current_legal_name", "year_start": 2022, "year_end": "auto"},
                    {"term": "테스트산업", "alias_type": "current_brand_name"},
                ],
                "site_candidates": [
                    {"candidate_id": "P", "site_name_raw": "포항제철소", "address_raw": "경상북도 포항시 남구 동해안로 6262", "identity_status": "CONFIRMED", "verification_state": "VERIFIED"},
                ],
            }
            (root / "Company_Profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            write_csv(root / "Site_Master.csv", [
                {"canonical_site_id": "SITE_P", "canonical_site_name": "테스트산업 포항제철소", "canonical_address_key": "경북포항시남구동해안로6262", "identity_status": "CONFIRMED"},
                {"canonical_site_id": "CAND_REL", "canonical_site_name": "테스트산업퓨처엠 라임공장(포항)", "canonical_address_key": "경북포항시남구동해안로6262", "identity_status": "NEW_SITE_CANDIDATE"},
            ], ["canonical_site_id", "canonical_site_name", "canonical_address_key", "identity_status"])
            write_csv(root / "Source_Identity.csv", [
                {"source_key": "ENVINFO", "source_site_id": "CUR", "canonical_site_id": "SITE_P", "source_site_name_raw": "테스트산업 포항제철소", "source_address_raw": "경상북도 포항시 남구 동해안로 6262", "match_status": "CONFIRMED"},
                {"source_key": "ENVINFO", "source_site_id": "REL", "canonical_site_id": "CAND_REL", "source_site_name_raw": "(주)테스트산업퓨처엠 라임공장(포항)", "source_address_raw": "경상북도 포항시 남구 동해안로 6262", "match_status": "REVIEW_REQUIRED"},
            ], ["source_key", "source_site_id", "canonical_site_id", "source_site_name_raw", "source_address_raw", "match_status"])
            scope = resolve_requested_scope(root)
            self.assertEqual(scope["target_canonical_site_ids"], {"SITE_P"})
            self.assertIn("CUR", scope["target_source_ids"]["ENVINFO"])
            self.assertNotIn("REL", scope["target_source_ids"]["ENVINFO"])
            excluded = {(x["source_key"], x["source_site_id"]): x["reason"] for x in scope["excluded_source_ids"]}
            self.assertEqual(excluded[("ENVINFO", "REL")], "SOURCE_ENTITY_NAME_EXTENDS_CURRENT_COMPANY")
        finally:
            td.cleanup()

    def test_pre_entity_rows_are_retained_but_held_from_current_analysis(self):
        td = tempfile.TemporaryDirectory(); root = Path(td.name)
        try:
            profile = {
                "company_display_name": "테스트산업 주식회사",
                "requested_company_name": "테스트산업",
                "requested_scope": {"mode": "SITE_SET", "label": "제철소", "candidate_ids": ["P"]},
                "aliases": [
                    {"term": "테스트산업 주식회사", "alias_type": "current_legal_name", "year_start": 2022, "year_end": "auto"},
                    {"term": "테스트산업", "alias_type": "current_brand_name"},
                ],
                "site_candidates": [
                    {"candidate_id": "P", "site_name_raw": "포항제철소", "address_raw": "경상북도 포항시 남구 동해안로 6262", "identity_status": "CONFIRMED", "verification_state": "VERIFIED"},
                ],
            }
            (root / "Company_Profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            write_csv(root / "Site_Master.csv", [
                {"canonical_site_id": "SITE_P", "canonical_site_name": "테스트산업 포항제철소", "canonical_address_key": "경북포항시남구동해안로6262", "identity_status": "CONFIRMED"},
            ], ["canonical_site_id", "canonical_site_name", "canonical_address_key", "identity_status"])
            write_csv(root / "Source_Identity.csv", [
                {"source_key": "PRTR", "source_site_id": "P1", "canonical_site_id": "SITE_P", "source_site_name_raw": "테스트산업 포항제철소", "source_address_raw": "경상북도 포항시 남구 동해안로 6262", "match_status": "CONFIRMED"},
            ], ["source_key", "source_site_id", "canonical_site_id", "source_site_name_raw", "source_address_raw", "match_status"])
            write_csv(root / "Analysis_Ready_Index.csv", [
                {"analysis_id": "OLD", "canonical_site_id": "SITE_P", "source_key": "PRTR", "source_site_id": "P1", "time_key": "2020", "event_link_ids": "", "analysis_readiness": "READY", "analysis_eligible": True, "notes": ""},
                {"analysis_id": "CUR", "canonical_site_id": "SITE_P", "source_key": "PRTR", "source_site_id": "P1", "time_key": "2022", "event_link_ids": "", "analysis_readiness": "READY", "analysis_eligible": True, "notes": ""},
            ], ["analysis_id", "canonical_site_id", "source_key", "source_site_id", "time_key", "event_link_ids", "analysis_readiness", "analysis_eligible", "notes"])
            write_csv(root / "Coverage_Event_Links.csv", [], ["link_id", "source_key", "canonical_site_id"])

            summary = apply_requested_scope(root)
            self.assertEqual(summary["current_legal_entity_active_period"], {"start_year": 2022, "end_year": None})
            self.assertEqual(summary["temporal_rows_held"], 1)
            rows = {r["analysis_id"]: r for r in csv.DictReader((root / "Analysis_Ready_Index.csv").open(encoding="utf-8-sig"))}
            self.assertEqual(set(rows), {"OLD", "CUR"})
            self.assertEqual(rows["OLD"]["analysis_readiness"], "TEMPORAL_ENTITY_REVIEW")
            self.assertEqual(rows["OLD"]["analysis_eligible"], "False")
            self.assertEqual(rows["CUR"]["analysis_readiness"], "READY")
            self.assertEqual(rows["CUR"]["analysis_eligible"], "True")
        finally:
            td.cleanup()

    def test_optional_legal_dong_does_not_break_road_address_match(self):
        td, root = self.make_package()
        try:
            scope = resolve_requested_scope(root)
            self.assertTrue(scope["target_canonical_site_ids"])
            from requested_scope import normalize_address
            self.assertEqual(
                normalize_address("울산광역시 남구 성암동 처용로 260-257"),
                normalize_address("울산광역시 남구 처용로 260-257"),
            )
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
