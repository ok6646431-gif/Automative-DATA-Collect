import copy
import tempfile
import json
import unittest
from pathlib import Path

from orchestrator import g0_public_source_fallback as mod
from orchestrator.collection_acceptance import _verified_tms_identity


def discovery_fixture():
    site = {
        "candidate_id": "weak-site", "site_name_raw": "고객과 공장",
        "address_raw": "서울특별시 서초구 산업로 53",
        "source_locator": "https://official.example/locations",
        "verification_state": "UNVERIFIED", "identity_status": "CANDIDATE",
        "discovery_evidence": {"extraction_contract": "FLATTENED_TEXT_FALLBACK"},
    }
    d = {
        "schema_version": "1.0", "request_id": "company-test-g0",
        "requested_company_name": "예시제조",
        "current_legal_name": "(주)예시제조",
        "company_verification_state": "VERIFIED",
        "confidence": "HIGH",
        "identity_evidence": [{
            "source_locator": "https://englishdart.fss.or.kr/dsbc001/selectPopup.ax?selectKey=00107613",
            "verification_state": "VERIFIED",
        }],
        "domestic_site_candidates": [site],
        "requested_scope": {"mode": "SITE_SET", "candidate_ids": ["weak-site"]},
        "unresolved_items": [{"code": "SITE_IDENTITY_UNRESOLVED", "subject": "weak-site"}],
        "collection_policy": {
            "minimum_history_years": 5,
            "sources": {
                "ENVINFO": {"requested_window": {"start_year": 2020, "end_year": 2024}},
                "PRTR": {"requested_window": {"start_year": 2020, "end_year": 2024}},
                "CHEM_STATS": {"available_survey_rounds": [2020, 2022, 2024]},
                "CLEANSYS_AIR": {"requested_window": {"start_year": 2020, "end_year": 2025}},
                "SOOSIRO_WATER": {"requested_window": {"start_year": 2020, "end_year": 2025},
                                  "daily_available_years": [2024]},
            },
        },
    }
    a = {
        "gate_status": "REVIEW_REQUIRED",
        "stages": {
            "legal_identity": {
                "resolved": {
                    "korean_name": "(주)예시제조",
                    "select_key": "00107613",
                    "source_url": "https://englishdart.fss.or.kr/dsbc001/selectPopup.ax?selectKey=00107613",
                    "corporation_registration_number": "110111-0186638",
                    "website": "www.official.example",
                }
            },
            "promotion_policy": {
                "blocking_unresolved_items": copy.deepcopy(d["unresolved_items"]),
                "deferred_review_items": [{"code": "CORPORATE_DOCUMENT_COVERAGE_INCOMPLETE"}],
            },
        },
    }
    return d, a


class VerifiedLegalOnlySourceFallbackTests(unittest.TestCase):
    def test_verified_company_recovers_all_five_sources_without_fake_site(self):
        discovery, audit = discovery_fixture()
        snapshot = copy.deepcopy(discovery)
        profile, request, receipt = mod.build_source_only(discovery, audit)
        self.assertEqual(discovery, snapshot)
        self.assertEqual("COMPANY", profile["requested_scope"]["mode"] if "requested_scope" in profile else "COMPANY")
        self.assertEqual("COMPANY_VERIFIED_PUBLIC_DISCOVERY_ONLY", receipt["status"])
        self.assertEqual(1, receipt["unverified_site_candidates_excluded"])
        self.assertEqual(0, receipt["verified_site_count"])
        self.assertEqual(list(mod.PUBLIC_SOURCES), list(request["sources"]))
        for source in mod.PUBLIC_SOURCES:
            identity = request["sources"][source]["identity_gate"]
            self.assertIn("(주)예시제조", identity["current_entity_names"])
            self.assertEqual([], identity["verified_sites"])
        self.assertFalse(_verified_tms_identity(request, "CLEANSYS_AIR"))
        self.assertFalse(_verified_tms_identity(request, "SOOSIRO_WATER"))
        self.assertEqual(2024, request["sources"]["ENVINFO"]["end_year"])
        self.assertEqual([2020, 2022, 2024], request["sources"]["CHEM_STATS"]["years"])

    def test_preserves_strongly_verified_site_without_relying_on_weak_site(self):
        discovery, audit = discovery_fixture()
        verified = {
            "candidate_id": "strong", "site_name_raw": "울산공장",
            "address_raw": "울산광역시 남구 산업로 10",
            "source_locator": "https://official.example/locations",
            "verification_state": "VERIFIED", "identity_status": "CONFIRMED",
            "discovery_evidence": {"extraction_contract": "STRUCTURED_DOM_NAME_ADDRESS_PAIR"},
        }
        discovery["domestic_site_candidates"].append(verified)
        _, request, receipt = mod.build_source_only(discovery, audit)
        self.assertEqual(1, receipt["verified_site_count"])
        self.assertEqual(1, receipt["unverified_site_candidates_excluded"])
        self.assertEqual([{"site_name": "울산공장", "address": "울산광역시 남구 산업로 10"}],
                         request["sources"]["PRTR"]["identity_gate"]["verified_sites"])

    def test_bogus_source_verified_weak_site_is_downgraded(self):
        d, a = discovery_fixture()
        d["domestic_site_candidates"][0]["verification_state"] = "VERIFIED"
        d["domestic_site_candidates"][0]["identity_status"] = "CONFIRMED"
        _, request, receipt = mod.build_source_only(d, a)
        self.assertEqual([], request["sources"]["CLEANSYS_AIR"]["site_addresses"])
        self.assertEqual(1, receipt["unverified_site_candidates_excluded"])

    def test_invalid_legal_identity_is_rejected(self):
        bad_mutations = [
            lambda d, a: d.update(company_verification_state="UNVERIFIED"),
            lambda d, a: d.update(current_legal_name="다른 법인"),
            lambda d, a: a["stages"]["legal_identity"]["resolved"].update(select_key=""),
            lambda d, a: a["stages"]["legal_identity"]["resolved"].update(source_url="https://example.org/?selectKey=00107613"),
            lambda d, a: d.update(identity_evidence=[]),
            lambda d, a: a["stages"]["legal_identity"]["resolved"].update(website=""),
        ]
        for change in bad_mutations:
            with self.subTest(change=change):
                d, a = discovery_fixture()
                change(d, a)
                with self.assertRaises(mod.SourceFallbackIneligible):
                    mod.build_source_only(d, a)

    def test_non_site_blocker_and_unclassified_deferred_issue_stop_fallback(self):
        for code in ("LEGAL_ENTITY_AMBIGUOUS", "RELATED_ENTITY_SCOPE_UNRESOLVED"):
            with self.subTest(code=code):
                d, a = discovery_fixture()
                issue = {"code": code, "subject": "another entity"}
                d["unresolved_items"].append(issue)
                a["stages"]["promotion_policy"]["blocking_unresolved_items"].append(issue)
                with self.assertRaises(mod.SourceFallbackIneligible):
                    mod.build_source_only(d, a)
        d, a = discovery_fixture()
        a["stages"]["promotion_policy"]["deferred_review_items"].append({"code": "UNKNOWN"})
        with self.assertRaises(mod.SourceFallbackIneligible):
            mod.build_source_only(d, a)

    def test_cli_emits_separate_outputs_without_overwriting_input(self):
        d, a = discovery_fixture()
        with tempfile.TemporaryDirectory() as temp:
            inp = Path(temp) / "g0"
            out = Path(temp) / "independent"
            inp.mkdir()
            for name, obj in (("company_discovery.json", d), ("Discovery_Audit.json", a)):
                (inp / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
            import sys
            from unittest.mock import patch
            with patch.object(sys, "argv", [
                "g0_public_source_fallback.py", "--discovery-dir", str(inp),
                "--out-dir", str(out),
            ]):
                self.assertEqual(0, mod.main())
            self.assertEqual(d, json.loads((inp / "company_discovery.json").read_text(encoding="utf-8")))
            self.assertTrue((out / "request.json").exists())
            self.assertEqual(
                "COMPANY_VERIFIED_PUBLIC_DISCOVERY_ONLY",
                json.loads((out / "identity_evidence.json").read_text(encoding="utf-8"))["status"],
            )


if __name__ == "__main__":
    unittest.main()
