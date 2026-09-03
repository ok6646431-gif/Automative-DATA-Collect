import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.collection_completeness import requested_scope_binding_rows


class RequestedScopeCompletenessGuardTests(unittest.TestCase):
    def test_site_set_raw_data_without_target_binding_is_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Requested_Scope.json").write_text(json.dumps({
                "mode": "SITE_SET",
                "label": "주요 사업장",
                "target_source_ids": {
                    "ENVINFO": [], "PRTR": [], "CHEM_STATS": [],
                    "CLEANSYS_AIR": [], "SOOSIRO_WATER": [],
                },
            }, ensure_ascii=False), encoding="utf-8")
            public = [
                {"source": "ENVINFO", "completeness_state": "DATA_PRESENT"},
                {"source": "PRTR", "completeness_state": "DATA_PRESENT"},
                {"source": "CHEM_STATS", "completeness_state": "NO_DATA_CONFIRMED"},
            ]
            rows = requested_scope_binding_rows(root, public)
            self.assertEqual({r["source"] for r in rows}, {"ENVINFO", "PRTR"})
            self.assertTrue(all(r["completeness_state"] == "REQUESTED_SCOPE_SOURCE_BINDING_UNRESOLVED" for r in rows))

    def test_bound_source_does_not_raise_guard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Requested_Scope.json").write_text(json.dumps({
                "mode": "SITE_SET",
                "label": "주요 사업장",
                "target_source_ids": {"PRTR": ["414"]},
            }, ensure_ascii=False), encoding="utf-8")
            public = [{"source": "PRTR", "completeness_state": "DATA_PRESENT"}]
            self.assertEqual(requested_scope_binding_rows(root, public), [])

    def test_company_scope_is_not_subject_to_site_binding_guard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Requested_Scope.json").write_text(json.dumps({"mode": "COMPANY"}), encoding="utf-8")
            public = [{"source": "PRTR", "completeness_state": "DATA_PRESENT"}]
            self.assertEqual(requested_scope_binding_rows(root, public), [])


if __name__ == "__main__":
    unittest.main()
