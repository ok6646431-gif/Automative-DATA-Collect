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
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


class CompanyScopeEntityFilterTests(unittest.TestCase):
    def test_company_scope_excludes_related_legal_entities_from_delivery_scope(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        try:
            profile = {
                "company_display_name": "테스트산업 주식회사",
                "requested_company_name": "테스트산업",
                "requested_scope": {"mode": "COMPANY", "label": "COMPANY"},
                "aliases": [
                    {"term": "테스트산업 주식회사", "alias_type": "current_legal_name"},
                    {"term": "테스트산업", "alias_type": "current_brand_name"},
                ],
                "site_candidates": [
                    {
                        "candidate_id": "P",
                        "site_name_raw": "포항제철소",
                        "address_raw": "경상북도 포항시 남구 동해안로 6261",
                        "identity_status": "CONFIRMED",
                        "verification_state": "VERIFIED",
                    },
                    {
                        "candidate_id": "G",
                        "site_name_raw": "광양제철소",
                        "address_raw": "전라남도 광양시 폭포사랑길 20-26",
                        "identity_status": "CONFIRMED",
                        "verification_state": "VERIFIED",
                    },
                ],
            }
            (root / "Company_Profile.json").write_text(
                json.dumps(profile, ensure_ascii=False), encoding="utf-8"
            )
            write_csv(
                root / "Site_Master.csv",
                [
                    {
                        "canonical_site_id": "SITE_P",
                        "canonical_site_name": "테스트산업 포항제철소",
                        "canonical_address_key": "경북포항시남구동해안로6261",
                        "identity_status": "CONFIRMED",
                    },
                    {
                        "canonical_site_id": "SITE_G",
                        "canonical_site_name": "테스트산업 광양제철소",
                        "canonical_address_key": "전남광양시폭포사랑길20-26",
                        "identity_status": "CONFIRMED",
                    },
                    {
                        "canonical_site_id": "SITE_REL",
                        "canonical_site_name": "테스트산업퓨처엠 포항화학사업부",
                        "canonical_address_key": "경북포항시남구신항로110",
                        "identity_status": "CONFIRMED",
                    },
                ],
                [
                    "canonical_site_id",
                    "canonical_site_name",
                    "canonical_address_key",
                    "identity_status",
                ],
            )
            write_csv(
                root / "Source_Identity.csv",
                [
                    {
                        "source_key": "PRTR",
                        "source_site_id": "CUR_P",
                        "canonical_site_id": "SITE_P",
                        "source_site_name_raw": "주식회사 테스트산업",
                        "source_address_raw": "경상북도 포항시 남구 동해안로 6261",
                        "match_status": "CONFIRMED",
                    },
                    {
                        "source_key": "PRTR",
                        "source_site_id": "CUR_G",
                        "canonical_site_id": "SITE_G",
                        "source_site_name_raw": "주식회사 테스트산업 광양제철소",
                        "source_address_raw": "전라남도 광양시 폭포사랑길 20-26",
                        "match_status": "CONFIRMED",
                    },
                    {
                        "source_key": "PRTR",
                        "source_site_id": "REL_F",
                        "canonical_site_id": "SITE_REL",
                        "source_site_name_raw": "(주)테스트산업퓨처엠 포항화학사업부",
                        "source_address_raw": "경상북도 포항시 남구 신항로 110",
                        "match_status": "CONFIRMED",
                    },
                    {
                        "source_key": "CHEM_STATS",
                        "source_site_id": "REL_I",
                        "canonical_site_id": "",
                        "source_site_name_raw": "주식회사 테스트산업인터내셔널",
                        "source_address_raw": "인천광역시 연수구 컨벤시아대로 165",
                        "match_status": "REVIEW_REQUIRED",
                    },
                ],
                [
                    "source_key",
                    "source_site_id",
                    "canonical_site_id",
                    "source_site_name_raw",
                    "source_address_raw",
                    "match_status",
                ],
            )

            scope = resolve_requested_scope(root)

            self.assertEqual(scope["mode"], "COMPANY")
            self.assertEqual(scope["target_canonical_site_ids"], {"SITE_P", "SITE_G"})
            self.assertEqual(scope["target_source_ids"]["PRTR"], {"CUR_P", "CUR_G"})
            self.assertEqual(scope["target_source_ids"]["CHEM_STATS"], set())
            excluded = {
                (x["source_key"], x["source_site_id"]): x["reason"]
                for x in scope["excluded_source_ids"]
            }
            self.assertEqual(
                excluded[("PRTR", "REL_F")],
                "SOURCE_ENTITY_NAME_EXTENDS_CURRENT_COMPANY",
            )
            self.assertEqual(
                excluded[("CHEM_STATS", "REL_I")],
                "SOURCE_ENTITY_NAME_EXTENDS_CURRENT_COMPANY",
            )
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
