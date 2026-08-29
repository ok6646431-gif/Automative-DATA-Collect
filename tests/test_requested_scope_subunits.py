import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
from requested_scope import resolve_requested_scope


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class RequestedScopeSubunitTests(unittest.TestCase):
    def test_numbered_current_company_subunit_can_match_official_parent_site(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        try:
            profile = {
                "company_display_name": "테스트케미칼 주식회사",
                "requested_company_name": "테스트케미칼",
                "requested_scope": {"mode": "SITE_SET", "label": "생산거점", "candidate_ids": ["Y"]},
                "aliases": [{"term": "테스트케미칼"}],
                "site_candidates": [
                    {
                        "candidate_id": "Y",
                        "site_name_raw": "기초화학 여수공장",
                        "address_raw": "전라남도 여수시 여수산단4로 53",
                        "identity_status": "CONFIRMED",
                        "verification_state": "VERIFIED",
                    }
                ],
            }
            (root / "Company_Profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            write_csv(
                root / "Site_Master.csv",
                [
                    {
                        "canonical_site_id": "SITE_Y1",
                        "canonical_site_name": "테스트케미칼(주)여수1공장",
                        "canonical_address_key": "전남여수시여수산단4로53",
                        "identity_status": "CONFIRMED",
                    }
                ],
                ["canonical_site_id", "canonical_site_name", "canonical_address_key", "identity_status"],
            )
            write_csv(
                root / "Source_Identity.csv",
                [
                    {
                        "source_key": "PRTR",
                        "source_site_id": "Y1",
                        "canonical_site_id": "SITE_Y1",
                        "source_site_name_raw": "테스트케미칼(주)여수1공장",
                        "source_address_raw": "전라남도 여수시 여수산단4로 53",
                        "match_status": "CONFIRMED",
                    }
                ],
                ["source_key", "source_site_id", "canonical_site_id", "source_site_name_raw", "source_address_raw", "match_status"],
            )
            scope = resolve_requested_scope(root)
            self.assertEqual(scope["target_canonical_site_ids"], {"SITE_Y1"})
            self.assertIn("Y1", scope["target_source_ids"]["PRTR"])
            excluded = {(x["source_key"], x["source_site_id"]) for x in scope["excluded_source_ids"]}
            self.assertNotIn(("PRTR", "Y1"), excluded)
        finally:
            td.cleanup()

    def test_related_brand_extension_still_fails_closed(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        try:
            profile = {
                "company_display_name": "테스트산업 주식회사",
                "requested_company_name": "테스트산업",
                "requested_scope": {"mode": "SITE_SET", "label": "제철소", "candidate_ids": ["P"]},
                "aliases": [{"term": "테스트산업"}],
                "site_candidates": [
                    {
                        "candidate_id": "P",
                        "site_name_raw": "포항제철소",
                        "address_raw": "경상북도 포항시 남구 동해안로 6262",
                        "identity_status": "CONFIRMED",
                        "verification_state": "VERIFIED",
                    }
                ],
            }
            (root / "Company_Profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            write_csv(root / "Site_Master.csv", [], ["canonical_site_id", "canonical_site_name", "canonical_address_key", "identity_status"])
            write_csv(
                root / "Source_Identity.csv",
                [
                    {
                        "source_key": "ENVINFO",
                        "source_site_id": "REL",
                        "canonical_site_id": "CAND_REL",
                        "source_site_name_raw": "(주)테스트산업퓨처엠 라임공장(포항)",
                        "source_address_raw": "경상북도 포항시 남구 동해안로 6262",
                        "match_status": "REVIEW_REQUIRED",
                    }
                ],
                ["source_key", "source_site_id", "canonical_site_id", "source_site_name_raw", "source_address_raw", "match_status"],
            )
            scope = resolve_requested_scope(root)
            self.assertNotIn("REL", scope["target_source_ids"]["ENVINFO"])
            excluded = {(x["source_key"], x["source_site_id"]): x["reason"] for x in scope["excluded_source_ids"]}
            self.assertEqual(excluded[("ENVINFO", "REL")], "SOURCE_ENTITY_NAME_EXTENDS_CURRENT_COMPANY")
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
