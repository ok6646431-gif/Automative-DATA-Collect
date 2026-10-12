import csv
import json
import tempfile
import unittest
from pathlib import Path

from orchestrator import public_site_crosscheck as mod


class PublicSiteCrosscheckTests(unittest.TestCase):
    def _csv(self, p, rows):
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as f:
            out = csv.DictWriter(f, fieldnames=list(rows[0]))
            out.writeheader()
            out.writerows(rows)

    def _fixture(self, root):
        env = root / "ENVINFO"
        chem = root / "CHEM_STATS"
        self._csv(env / "discovery.csv", [
            {"year": str(y), "compId": "00000000000000199765", "compNm": "(주)이수페타시스"}
            for y in range(2020, 2025)
        ])
        (env / "raw_detail").mkdir(parents=True)
        html = """
          <html><table><tr><th>구분</th><th>사업장명</th><th>주소</th></tr>
          <tr><td>대표사업장</td><td>(주)이수페타시스</td>
          <td>대구 달성군 논공읍 논공로53길 36 이수페타시스</td></tr></table></html>
        """
        (env / "raw_detail" / "2024_00000000000000199765.html").write_text(
            html, encoding="utf-8")
        self._csv(chem / "discovery.csv", [
            {"reportYear": "2020", "bplcId": "ADH677N", "bplcNm": "(주)이수페타시스",
             "locplcAdres": "대구광역시 달성군 논공읍 논공로53길 36 (주)이수페타시스"},
            {"reportYear": "2022", "bplcId": "AAC001N", "bplcNm": "(주)이수페타시스",
             "locplcAdres": "대구광역시 논공읍 논공로53길 36 , 50"},
            {"reportYear": "2024", "bplcId": "AAC001N", "bplcNm": "(주)이수페타시스",
             "locplcAdres": "대구광역시 논공읍 논공로53길 36"},
        ])
        for source in mod.TMS:
            p = root / source / "status.json"
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({
                "source_key": source, "status": "NO_FACILITY_MATCH_CONFIRMED",
                "registry_scan_complete": True,
                "candidate_count": 0, "fact_codes": 0,
            }), encoding="utf-8")

    def test_related_legal_road_anchor_keeps_native_ids_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._fixture(root)
            result = mod.evaluate(root, "(주)이수페타시스")
            self.assertEqual("CORRELATED_WITH_LIMITATIONS", result["status"])
            self.assertEqual(
                ["AAC001N", "ADH677N"], result["chem_native_ids"])
            self.assertEqual(1, len(result["envinfo_native_ids"]))
            self.assertFalse(result["facility_id_crosswalk_verified"])
            self.assertEqual(
                "RELATED_LOCATION_CANDIDATES_NOT_VERIFIED_AS_IDENTICAL_FACILITY",
                result["crosswalk_state"])
            self.assertTrue(all(x["shared_primary_road_anchor"]
                                for x in result["location_correlation"]))
            self.assertIn(
                "MULTIPLE_SOURCE_NATIVE_CHEM_IDS_NO_AUTO_MERGE", result["review_issues"])
            self.assertIn(
                "MULTI_NUMBER_LOCATION_SCOPE_REQUIRES_REVIEW", result["review_issues"])
            self.assertEqual(["50"], next(x["chem_multiple_address_numbers"]
                                         for x in result["location_correlation"]
                                         if x["chem_year"] == "2022"))
            for source in mod.TMS:
                self.assertEqual(
                    "UNCONFIRMED", result["tms"][source]["disclosure_applicability"])
                self.assertTrue(result["tms"][source]["no_emissions_inference"])

    def test_different_road_number_does_not_confirm_location(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._fixture(root)
            p = root / "ENVINFO/raw_detail/2024_00000000000000199765.html"
            p.write_text(p.read_text(encoding="utf-8").replace(
                "논공로53길 36", "논공로53길 99"), encoding="utf-8")
            result = mod.evaluate(root, "(주)이수페타시스")
            self.assertEqual("REVIEW_REQUIRED", result["status"])
            self.assertIn("CROSS_SOURCE_LOCATION_CORRELATION_INCOMPLETE",
                          result["review_issues"])

    def test_name_matching_with_no_official_site_row_is_not_enough(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._fixture(root)
            (root / "ENVINFO/raw_detail/2024_00000000000000199765.html").unlink()
            result = mod.evaluate(root, "(주)이수페타시스")
            self.assertEqual("REVIEW_REQUIRED", result["status"])
            self.assertIn("ENVINFO_SITE_ADDRESS_NOT_EXPLICITLY_EXTRACTED",
                          result["review_issues"])

    def test_legal_name_collision_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._fixture(root)
            result = mod.evaluate(root, "(주)다른법인")
            self.assertEqual("REVIEW_REQUIRED", result["status"])
            self.assertEqual([], result["chem_native_ids"])
            self.assertEqual([], result["envinfo_native_ids"])

    def test_missing_sources_do_not_turn_into_no_data(self):
        with tempfile.TemporaryDirectory() as d:
            result = mod.evaluate(d, "(주)이수페타시스")
            self.assertEqual("REVIEW_REQUIRED", result["status"])
            self.assertFalse(result["facility_id_crosswalk_verified"])

    def test_address_variants_preserve_additional_factory_numbers(self):
        a = mod.road_address("대구광역시 달성군 논공읍 논공로 53길 36, 50, 60, 70")
        b = mod.road_address("대구시 논공읍 논공로53길 36")
        self.assertEqual(a["key"], b["key"])
        self.assertEqual(["50", "60", "70"], a["additional_numbers"])
        self.assertNotEqual(a["key"], mod.road_address("대구시 논공읍 논공로53길 50")["key"])
        self.assertNotEqual(a["key"], mod.road_address("부산시 논공읍 논공로53길 36")["key"])

    def test_source_native_ids_are_never_crosswalked_due_to_same_name(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._fixture(root)
            result = mod.evaluate(root, "이수페타시스")
            self.assertFalse(result["facility_id_crosswalk_verified"])
            self.assertEqual(2, len(result["chem_native_ids"]))


if __name__ == "__main__":
    unittest.main()
