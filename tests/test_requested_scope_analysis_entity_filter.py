import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
from requested_scope import apply_requested_scope


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class AnalysisScopeSourceIdentityTests(unittest.TestCase):
    def test_related_entity_on_target_canonical_site_cannot_reenter_analysis(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            profile = {
                "company_display_name": "테스트산업 주식회사",
                "requested_company_name": "테스트산업",
                "legal_entity_active_period": {"start_year": 2022},
                "requested_scope": {
                    "mode": "SITE_SET",
                    "label": "테스트산업 포항",
                    "candidate_ids": ["P"],
                },
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
                    }
                ],
            }
            (root / "Company_Profile.json").write_text(
                json.dumps(profile, ensure_ascii=False), encoding="utf-8"
            )

            write_csv(
                root / "Site_Master.csv",
                [{
                    "canonical_site_id": "SITE_P",
                    "canonical_site_name": "테스트산업 포항제철소",
                    "canonical_address_key": "경상북도 포항시 남구 동해안로 6261",
                    "identity_status": "CONFIRMED",
                }],
                ["canonical_site_id", "canonical_site_name", "canonical_address_key", "identity_status"],
            )
            write_csv(
                root / "Source_Identity.csv",
                [
                    {
                        "source_key": "CHEM_STATS",
                        "source_site_id": "CUR",
                        "canonical_site_id": "SITE_P",
                        "source_site_name_raw": "주식회사 테스트산업 포항제철소",
                        "source_address_raw": "경상북도 포항시 남구 동해안로 6261",
                        "match_status": "CONFIRMED",
                    },
                    {
                        "source_key": "CHEM_STATS",
                        "source_site_id": "REL",
                        "canonical_site_id": "SITE_P",
                        "source_site_name_raw": "(주)테스트산업퓨처엠 포항화학사업부",
                        "source_address_raw": "경상북도 포항시 남구 동해안로 6261",
                        "match_status": "CONFIRMED",
                    },
                    {
                        "source_key": "PRTR",
                        "source_site_id": "CUR_FREE",
                        "canonical_site_id": "",
                        "source_site_name_raw": "주식회사 테스트산업 포항제철소",
                        "source_address_raw": "경상북도 포항시 남구 동해안로 6261",
                        "match_status": "REVIEW_REQUIRED",
                    },
                ],
                [
                    "source_key", "source_site_id", "canonical_site_id",
                    "source_site_name_raw", "source_address_raw", "match_status",
                ],
            )
            write_csv(
                root / "Analysis_Ready_Index.csv",
                [
                    {
                        "source_key": "CHEM_STATS", "source_site_id": "CUR",
                        "canonical_site_id": "SITE_P", "time_key": "2024",
                        "analysis_readiness": "READY", "analysis_eligible": "True",
                        "event_link_ids": "", "notes": "",
                    },
                    {
                        "source_key": "CHEM_STATS", "source_site_id": "REL",
                        "canonical_site_id": "SITE_P", "time_key": "2024",
                        "analysis_readiness": "READY", "analysis_eligible": "True",
                        "event_link_ids": "", "notes": "",
                    },
                    {
                        "source_key": "PRTR", "source_site_id": "CUR_FREE",
                        "canonical_site_id": "", "time_key": "2024",
                        "analysis_readiness": "READY", "analysis_eligible": "True",
                        "event_link_ids": "", "notes": "",
                    },
                    {
                        "source_key": "CHEM_STATS", "source_site_id": "CUR",
                        "canonical_site_id": "SITE_P", "time_key": "2021",
                        "analysis_readiness": "READY", "analysis_eligible": "True",
                        "event_link_ids": "", "notes": "",
                    },
                ],
                [
                    "source_key", "source_site_id", "canonical_site_id", "time_key",
                    "analysis_readiness", "analysis_eligible", "event_link_ids", "notes",
                ],
            )
            write_csv(
                root / "Coverage_Event_Links.csv",
                [],
                ["source_key", "canonical_site_id", "link_id"],
            )

            result = apply_requested_scope(root)
            rows = read_csv(root / "Analysis_Ready_Index.csv")
            keys = {(r["source_key"], r["source_site_id"], r["time_key"]): r for r in rows}

            self.assertNotIn(("CHEM_STATS", "REL", "2024"), keys)
            self.assertIn(("CHEM_STATS", "CUR", "2024"), keys)
            self.assertIn(("PRTR", "CUR_FREE", "2024"), keys)
            self.assertIn(("CHEM_STATS", "CUR", "2021"), keys)
            self.assertEqual(
                keys[("CHEM_STATS", "CUR", "2021")]["analysis_readiness"],
                "TEMPORAL_ENTITY_REVIEW",
            )
            self.assertEqual(
                keys[("CHEM_STATS", "CUR", "2021")]["analysis_eligible"],
                "False",
            )
            self.assertEqual(result["analysis_rows_before"], 4)
            self.assertEqual(result["analysis_rows_after"], 3)
            self.assertEqual(result["temporal_rows_held"], 1)

            scope = json.loads((root / "Requested_Scope.json").read_text(encoding="utf-8"))
            self.assertIn("CUR", scope["target_source_ids"]["CHEM_STATS"])
            self.assertNotIn("REL", scope["target_source_ids"]["CHEM_STATS"])
            self.assertIn("CUR_FREE", scope["target_source_ids"]["PRTR"])


if __name__ == "__main__":
    unittest.main()
