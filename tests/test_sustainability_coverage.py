import tempfile
import unittest
from pathlib import Path

from orchestrator.sustainability_coverage import evaluate


class SustainabilityCoverageTests(unittest.TestCase):
    def test_verified_but_failed_reports_do_not_satisfy_file_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            delivered=[]
            for year in [2020,2021,2022]:
                p=root/f"기업_지속가능경영보고서_{year}.pdf"; p.write_bytes(b"%PDF-test")
                delivered.append(p)
            rows=[]
            for year,status in [(2022,"DOWNLOADED"),(2023,"DOWNLOAD_FAILED"),(2024,"DOWNLOAD_FAILED"),(2025,"DOWNLOAD_FAILED")]:
                rows.append({
                    "document_type":"SUSTAINABILITY_REPORT","title":f"report {year}","report_year":str(year),
                    "verification_status":"VERIFIED","collection_status":status,
                })
            profile={"minimum_history_years":5,"current_legal_name_active_period":{"start_year":1976}}
            result=evaluate(profile,rows,delivered)
            self.assertEqual(result["state"],"FILE_COVERAGE_PARTIAL")
            self.assertEqual(result["target_report_years"],[2020,2021,2022,2023,2024,2025])
            self.assertEqual(result["missing_target_years"],[2023,2024,2025])
            self.assertFalse(result["coverage_sufficient"])

    def test_older_verified_year_cannot_be_dropped_when_minimum_is_met(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); delivered=[]
            for year in [2021,2022,2023,2024,2025]:
                p=root/f"report_{year}.pdf"; p.write_bytes(b"%PDF-test"); delivered.append(p)
            rows=[{
                "document_type":"SUSTAINABILITY_REPORT","title":f"report {year}","report_year":str(year),
                "verification_status":"VERIFIED","collection_status":"DOWNLOADED",
            } for year in [2020,2021,2022,2023,2024,2025]]
            result=evaluate({"minimum_history_years":5},rows,delivered)
            self.assertEqual(result["state"],"FILE_COVERAGE_PARTIAL")
            self.assertEqual(result["target_report_years"],[2020,2021,2022,2023,2024,2025])
            self.assertEqual(result["missing_target_years"],[2020])
            self.assertFalse(result["coverage_sufficient"])

    def test_recent_spin_off_caps_required_history_to_company_age(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); delivered=[]
            for year in [2021,2022,2023]:
                p=root/f"report_{year}.pdf"; p.write_bytes(b"%PDF-test"); delivered.append(p)
            rows=[{
                "document_type":"SUSTAINABILITY_REPORT","title":f"report {year}","report_year":str(year),
                "verification_status":"VERIFIED","collection_status":"DOWNLOADED",
            } for year in [2021,2022,2023]]
            result=evaluate({"minimum_history_years":5,"current_legal_name_active_period":{"start_year":2021}},rows,delivered)
            self.assertEqual(result["required_report_count"],3)
            self.assertEqual(result["state"],"FILE_COVERAGE_COMPLETE")

    def test_index_range_expands_expected_years_only_when_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); p=root/"report_2025.pdf"; p.write_bytes(b"%PDF-test")
            rows=[{
                "document_type":"ENVIRONMENTAL_DISCLOSURE","title":"공식 지속가능경영 보고서 자료실",
                "coverage_start":"2021","coverage_end":"2025","verification_status":"VERIFIED",
                "collection_status":"DOWNLOADED",
            }]
            result=evaluate({"minimum_history_years":5},rows,[p])
            self.assertEqual(result["expected_report_years"],[2021,2022,2023,2024,2025])
            self.assertEqual(result["missing_target_years"],[2021,2022,2023,2024])
            self.assertFalse(result["coverage_sufficient"])

    def test_requested_window_expands_verified_annual_series(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); delivered=[]
            for year in [2024,2025,2026]:
                p=root/f"report_{year}.pdf"; p.write_bytes(b"%PDF-test"); delivered.append(p)
            rows=[{
                "document_type":"SUSTAINABILITY_REPORT","title":f"report {year}","report_year":year,
                "verification_status":"VERIFIED","collection_status":"DOWNLOADED",
            } for year in [2024,2025,2026]]
            result=evaluate({
                "minimum_history_years":5,
                "requested_history_window":{"start_year":2020,"end_year":2026},
            },rows,delivered)
            self.assertEqual(result["target_report_years"],[2020,2021,2022,2023,2024,2025,2026])
            self.assertEqual(result["missing_target_years"],[2020,2021,2022,2023])
            self.assertEqual(result["state"],"FILE_COVERAGE_PARTIAL")


if __name__ == "__main__":
    unittest.main()
