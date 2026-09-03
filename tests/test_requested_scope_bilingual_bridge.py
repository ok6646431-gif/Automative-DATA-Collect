import csv
import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.requested_scope import resolve_requested_scope


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


class RequestedScopeBilingualBridgeTests(unittest.TestCase):
    def make_package(self, ambiguous=False):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        profile = {
            "company_display_name": "테스트오션(주)",
            "requested_company_name": "테스트오션",
            "legal_entity_active_period": {"start_year": 2000},
            "requested_scope": {"mode": "SITE_SET", "label": "주요 사업장", "candidate_ids": ["OFFICIAL"]},
            "aliases": [
                {"term": "테스트오션(주)", "scope": "current", "alias_type": "current_legal_name", "verification_state": "VERIFIED"},
                {"term": "과거조선(주)", "scope": "historical", "alias_type": "former_legal_name", "verification_state": "VERIFIED", "year_start": 2020, "year_end": 2023},
            ],
            "site_candidates": [{
                "candidate_id": "OFFICIAL",
                "site_name_raw": "테스트오션 주요 사업장",
                "address_raw": "3370, Geoje-daero, Geoje-si, Gyeongsangnam-do, 53302, Republic of Korea",
                "identity_status": "CONFIRMED",
                "verification_state": "VERIFIED",
            }],
            "related_entity_exclusions": [{"name": "테스트오션에코텍(주)", "verification_state": "VERIFIED"}],
        }
        (root / "Company_Profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")

        sites = [
            {"canonical_site_id": "SITE_OFFICIAL", "canonical_site_name": "테스트오션 주요 사업장", "canonical_address_key": "3370geojedaerogeojesigyeongsangnamdo53302republicofkorea", "identity_status": "CONFIRMED"},
            {"canonical_site_id": "SITE_MAIN", "canonical_site_name": "테스트오션(주)", "canonical_address_key": "경남거제시거제대로3370", "identity_status": "CONFIRMED"},
            {"canonical_site_id": "SITE_RELATED", "canonical_site_name": "테스트오션에코텍(주)", "canonical_address_key": "전남광양시산단로20", "identity_status": "CONFIRMED"},
        ]
        if ambiguous:
            sites.append({"canonical_site_id": "SITE_OTHER", "canonical_site_name": "테스트오션(주)", "canonical_address_key": "경남통영시해안로3370", "identity_status": "CONFIRMED"})
        write_csv(root / "Site_Master.csv", sites, ["canonical_site_id", "canonical_site_name", "canonical_address_key", "identity_status"])

        identities = [
            {"source_key": "PRTR", "source_site_id": "414", "canonical_site_id": "SITE_MAIN", "source_site_name_raw": "테스트오션(주)", "source_address_raw": "경상남도 거제시 거제대로 3370", "match_status": "CONFIRMED"},
            {"source_key": "CHEM_STATS", "source_site_id": "ACW978N", "canonical_site_id": "SITE_MAIN", "source_site_name_raw": "과거조선(주)", "source_address_raw": "경상남도 거제시 거제대로 3370", "match_status": "CONFIRMED"},
            {"source_key": "ENVINFO", "source_site_id": "ENV_MAIN", "canonical_site_id": "CAND_ENV", "source_site_name_raw": "테스트오션(주) 거제사업장", "source_address_raw": "경남 거제시 거제대로 3370 테스트오션", "match_status": "REVIEW_REQUIRED"},
            {"source_key": "ENVINFO", "source_site_id": "ENV_CENTER", "canonical_site_id": "CAND_CENTER", "source_site_name_raw": "테스트오션(주) 통합관리센터", "source_address_raw": "경남 거제시 거제대로 3370 테스트오션", "match_status": "REVIEW_REQUIRED"},
            {"source_key": "CHEM_STATS", "source_site_id": "RELATED", "canonical_site_id": "SITE_RELATED", "source_site_name_raw": "테스트오션에코텍(주)", "source_address_raw": "전남 광양시 산단로 20", "match_status": "CONFIRMED"},
        ]
        if ambiguous:
            identities.extend([
                {"source_key": "PRTR", "source_site_id": "OTHER_P", "canonical_site_id": "SITE_OTHER", "source_site_name_raw": "테스트오션(주)", "source_address_raw": "경남 통영시 해안로 3370", "match_status": "CONFIRMED"},
                {"source_key": "CHEM_STATS", "source_site_id": "OTHER_C", "canonical_site_id": "SITE_OTHER", "source_site_name_raw": "과거조선(주)", "source_address_raw": "경남 통영시 해안로 3370", "match_status": "CONFIRMED"},
            ])
        write_csv(root / "Source_Identity.csv", identities, ["source_key", "source_site_id", "canonical_site_id", "source_site_name_raw", "source_address_raw", "match_status"])
        return td, root

    def test_unique_cross_source_road_number_bridges_bilingual_address(self):
        td, root = self.make_package()
        try:
            scope = resolve_requested_scope(root)
            self.assertIn("SITE_MAIN", scope["target_canonical_site_ids"])
            self.assertEqual(scope["target_source_ids"]["PRTR"], {"414"})
            self.assertEqual(scope["target_source_ids"]["CHEM_STATS"], {"ACW978N"})
            self.assertEqual(scope["target_source_ids"]["ENVINFO"], {"ENV_MAIN"})
            self.assertNotIn("ENV_CENTER", scope["target_source_ids"]["ENVINFO"])
            self.assertNotIn("RELATED", scope["target_source_ids"]["CHEM_STATS"])
        finally:
            td.cleanup()

    def test_road_number_bridge_fails_closed_when_not_unique(self):
        td, root = self.make_package(ambiguous=True)
        try:
            scope = resolve_requested_scope(root)
            self.assertNotIn("SITE_MAIN", scope["target_canonical_site_ids"])
            self.assertNotIn("SITE_OTHER", scope["target_canonical_site_ids"])
            self.assertTrue(scope["unresolved_candidates"])
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
