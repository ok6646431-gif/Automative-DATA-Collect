import unittest

from orchestrator.archive_builder import doc_user_folder


class ArchiveReportCatalogRoutingTests(unittest.TestCase):
    def test_report_catalog_is_not_routed_as_annual_sustainability_report(self):
        folder = doc_user_folder(
            "OTHER_OFFICIAL_DOCUMENT",
            "Official sustainability report catalog",
        )
        self.assertEqual(folder, "06_회사환경정책/기타_공식자료")
        self.assertNotEqual(folder, "04_지속가능경영보고서")

    def test_actual_annual_report_remains_in_annual_report_folder(self):
        self.assertEqual(
            doc_user_folder("SUSTAINABILITY_REPORT", "2024 Sustainability Report"),
            "04_지속가능경영보고서",
        )


if __name__ == "__main__":
    unittest.main()
