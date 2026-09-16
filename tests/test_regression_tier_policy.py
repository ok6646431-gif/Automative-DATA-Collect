import unittest

from orchestrator.regression_tier_policy import classify_execution_failure, classify_paths
from tests.test_coverage_semantics import CoverageSemanticsTests  # noqa: F401


class RegressionTierPolicyTest(unittest.TestCase):
    def test_identity_gate_change_is_r2_all_public_sources_not_r3(self):
        plan = classify_paths(["collectors/entity_scope_gate.py"])
        self.assertEqual(plan["required_tier"], "R2")
        self.assertFalse(plan["r3_required"])
        self.assertEqual(
            plan["r2_sources"],
            ["ENVINFO", "PRTR", "CHEM_STATS", "CLEANSYS_AIR", "SOOSIRO_WATER"],
        )

    def test_one_collector_only_invalidates_one_source(self):
        plan = classify_paths(["collectors/envinfo_collect.py"])
        self.assertEqual(plan["required_tier"], "R2")
        self.assertEqual(plan["r2_sources"], ["ENVINFO"])
        self.assertFalse(plan["r3_required"])

    def test_shared_icis_change_invalidates_both_icis_sources(self):
        plan = classify_paths(["collectors/icis_gate.py"])
        self.assertEqual(plan["required_tier"], "R2")
        self.assertEqual(plan["r2_sources"], ["PRTR", "CHEM_STATS"])

    def test_request_builder_invalidates_all_public_sources(self):
        plan = classify_paths(["orchestrator/request_builder.py"])
        self.assertEqual(plan["required_tier"], "R2")
        self.assertEqual(len(plan["r2_sources"]), 5)

    def test_company_identity_discovery_invalidates_all_source_lanes(self):
        plan = classify_paths(["orchestrator/company_profile_builder.py"])
        self.assertEqual(plan["required_tier"], "R2")
        self.assertEqual(
            plan["r2_sources"],
            ["ENVINFO", "PRTR", "CHEM_STATS", "CLEANSYS_AIR", "SOOSIRO_WATER", "CORP_DOCS"],
        )

    def test_archive_change_requires_r3_without_live_source_redownload(self):
        plan = classify_paths(["orchestrator/archive_builder.py"])
        self.assertEqual(plan["required_tier"], "R3")
        self.assertTrue(plan["r3_required"])
        self.assertEqual(plan["r2_sources"], [])

    def test_postprocess_semantic_change_requires_r3(self):
        plan = classify_paths(["orchestrator/postprocess.py"])
        self.assertEqual(plan["required_tier"], "R3")
        self.assertTrue(plan["r3_required"])
        self.assertEqual(plan["r2_sources"], [])

    def test_master_workflow_change_requires_r3(self):
        plan = classify_paths([".github/workflows/collect.yml"])
        self.assertEqual(plan["required_tier"], "R3")
        self.assertTrue(plan["r3_required"])

    def test_mixed_archive_and_collector_preserves_r2_sources(self):
        plan = classify_paths(["orchestrator/archive_stage.py", "collectors/prtr_collect.py"])
        self.assertEqual(plan["required_tier"], "R3")
        self.assertEqual(plan["r2_sources"], ["PRTR"])

    def test_request_data_promotion_needs_no_regression(self):
        plan = classify_paths([
            "requests/company_discovery.json",
            "requests/document_evidence.json",
            "requests/run_token.txt",
        ])
        self.assertEqual(plan["required_tier"], "NONE")
        self.assertFalse(plan["r1_required"])

    def test_docs_only_needs_no_runtime_regression(self):
        plan = classify_paths(["docs/REGRESSION_POLICY.md", "PROJECT_STATE.md"])
        self.assertEqual(plan["required_tier"], "NONE")
        self.assertFalse(plan["r1_required"])

    def test_test_only_change_is_r1(self):
        plan = classify_paths(["tests/test_entity_scope_gate.py"])
        self.assertEqual(plan["required_tier"], "R1")
        self.assertTrue(plan["r1_required"])

    def test_remote_timeout_is_infra_not_regression_failure(self):
        self.assertEqual(
            classify_execution_failure(status="REMOTE_HOST_UNREACHABLE", text="ConnectTimeout"),
            "INFRA_RETRY_REQUIRED",
        )

    def test_http_503_is_infra_not_regression_failure(self):
        self.assertEqual(
            classify_execution_failure(status="FAILED", text="HTTP 503 upstream unavailable"),
            "INFRA_RETRY_REQUIRED",
        )

    def test_assertion_failure_is_regression_failure(self):
        self.assertEqual(
            classify_execution_failure(status="FAILED", text="AssertionError: expected target ids"),
            "REGRESSION_FAIL",
        )


if __name__ == "__main__":
    unittest.main()
