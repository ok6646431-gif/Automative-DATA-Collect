import json
import unittest
from pathlib import Path

try:
    import jsonschema
except ModuleNotFoundError:
    jsonschema = None


@unittest.skipUnless(
    jsonschema is not None,
    "jsonschema is installed in the G0 schema-contract workflow; collector jobs may omit it",
)
class DocumentEvidenceSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(
            Path("requests/document_evidence.schema.json").read_text(encoding="utf-8")
        )
        cls.validator = jsonschema.Draft202012Validator(cls.schema)

    def test_summary_and_digital_report_representations_validate(self):
        payload = {
            "schema_version": "1.0",
            "request_id": "schema-contract-test",
            "discovery_status": "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE",
            "documents": [
                {
                    "document_id": "SUMMARY_2022",
                    "document_type": "SUSTAINABILITY_REPORT_SUMMARY",
                    "title": "2022 sustainability report highlight",
                    "report_year": 2022,
                    "source_url": "https://official.example/report-highlight.pdf",
                    "source_locator": "https://official.example/reports",
                    "expected_extension": "pdf",
                    "verification_status": "SOURCE_VERIFIED",
                    "importance": "SUPPORTING",
                    "coverage_role": "SUPPORTING_SUMMARY_ONLY",
                },
                {
                    "document_id": "DIGITAL_2025",
                    "document_type": "SUSTAINABILITY_REPORT",
                    "title": "2025 sustainability report",
                    "report_year": 2025,
                    "source_url": "https://official.example/digital-report",
                    "source_locator": "https://official.example/digital-report",
                    "expected_extension": "html",
                    "verification_status": "SOURCE_VERIFIED",
                    "importance": "CORE",
                    "representation": "DIGITAL_REPORT",
                    "entity_alignment": "ALIGNED",
                },
            ],
            "gaps": [],
        }
        self.validator.validate(payload)


if __name__ == "__main__":
    unittest.main()
