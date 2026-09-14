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


class RequestedScopeCenterLabelTests(unittest.TestCase):
    def test_verified_company_center_is_not_mistaken_for_related_entity(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        try:
            profile = {
                "company_display_name": "테스트 주식회사",
                "requested_company_name": "테스트",
                "requested_scope": {
                    "mode": "SITE_SET",
                    "label": "테스트 국내 거점",
                    "candidate_ids": ["CENTER"],
                },
                "aliases": [
                    {
                        "term": "테스트 주식회사",
                        "scope": "current",
                        "alias_type": "current_legal_name",
                        "verification_state": "VERIFIED",
                    },
                    {
                        "term": "테스트",
                        "scope": "current",
                        "alias_type": "requested_name",
                        "verification_state": "VERIFIED",
                    },
                ],
                "site_candidates": [
                    {
                        "candidate_id": "CENTER",
                        "site_name_raw": "테스트센터",
                        "address_raw": "서울특별시 강남구 테헤란로 440",
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
                [
                    {
                        "canonical_site_id": "SITE_CENTER",
                        "canonical_site_name": "테스트센터",
                        "canonical_address_key": "서울강남구테헤란로440",
                        "identity_status": "CONFIRMED",
                    }
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
                [],
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

            self.assertEqual(scope["target_canonical_site_ids"], {"SITE_CENTER"})
            self.assertEqual(scope["unresolved_candidates"], [])
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
