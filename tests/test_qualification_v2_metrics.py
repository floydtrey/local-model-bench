"""Deterministic metric projection tests. No model inference."""
from __future__ import annotations
import unittest

from localbench.v2.metric_projection import case_status, project_metrics, CATALOG_VERSION


class MetricProjectionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {"schema_version": CATALOG_VERSION, "metrics": [
            {"id": "coding", "kind": "capability", "suite": "shared-l2-core",
             "suite_version": "1.0.0", "rubric": "shared-v2-evaluator",
             "rubric_version": "1", "cases": ["minimal-code-repair", "multi-file-synthesis"],
             "scoring": "independent_deterministic_case_pass"},
            {"id": "vision", "kind": "capability", "suite": None,
             "suite_version": None, "rubric": None, "rubric_version": None,
             "cases": [], "scoring": "not_tested"}]}
        self.metadata = {}
        self.base = {"suite_id": "shared-l2-core", "suite_version": "1.0.0",
                     "rubric_id": "shared-v2-evaluator", "rubric_version": "1", "candidate_id": "m1",
                     "model_identity": "m1-q4", "runtime_identity": "ollama-1",
                     "track": "controlled_role_qualification",
                     "worker_mode": None, "comparison_protocol": "p1",
                     "evidence_directory": "/run/case1"}

    def case(self, name, result=True, **changes):
        return {**self.base, "case_id": name, "deterministic_passed": result, **changes}

    def test_missing_is_unknown_not_zero(self):
        self.assertEqual(case_status({"status": "success"}), "unknown")
        result = project_metrics([], self.metadata, self.catalog)["metrics"]
        self.assertIsNone(result[0]["percentage"])
        self.assertEqual(result[1]["status"], "not_tested")

    def test_scored_cases_are_distinct_and_evidence_linked(self):
        rows = [self.case("minimal-code-repair", True),
                self.case("multi-file-synthesis", False, evidence_directory="/run/case2")]
        result = project_metrics(rows, self.metadata, self.catalog)["metrics"][0]
        self.assertEqual((result["numerator"], result["denominator"]), (1, 2))
        self.assertEqual(result["percentage"], 50)
        self.assertEqual(len(result["case_refs"]), 2)
        self.assertEqual(result["case_refs"][1]["evidence_directory"], "/run/case2")

    def test_repeats_not_independent(self):
        rows = [self.case("minimal-code-repair", True), self.case("minimal-code-repair", False)]
        result = project_metrics(rows, self.metadata, self.catalog)["metrics"][0]
        self.assertIsNone(result["denominator"])
        self.assertEqual(result["excluded"][0]["reason"], "multiple_attempts_without_selection_policy")

    def test_incompatible_configuration_excluded(self):
        rows = [self.case("minimal-code-repair", True),
                self.case("multi-file-synthesis", True, model_identity="m2-q8")]
        result = project_metrics(rows, self.metadata, self.catalog)["metrics"][0]
        self.assertIsNone(result["percentage"])
        self.assertTrue(any(x["reason"] == "incompatible_configuration" for x in result["excluded"]))

    def test_blocked_pending_unsupported_not_zero(self):
        self.assertEqual(case_status({"execution_status": "prerequisite_blocked"}), "blocked")
        self.assertEqual(case_status({"human_review_required": True}), "pending_review")
        self.assertEqual(case_status({"execution_status": "unsupported"}), "unsupported")
        self.assertEqual(case_status({"execution_status": "not_attempted"}), "not_attempted")
        result = project_metrics([self.case("minimal-code-repair", False,
                execution_status="prerequisite_blocked")], self.metadata, self.catalog)["metrics"][0]
        self.assertIsNone(result["percentage"])

    def test_tester_correct_fail_is_successful_assessment(self):
        self.assertEqual(case_status({"role": "tester", "implementation_truth": "defective",
            "candidate_decision": "FAIL", "assessed_outcome": "PASS"}), "passed")

    def test_first_pass_and_repair_are_distinct(self):
        rows = [
            self.case("minimal-code-repair", True, first_pass_passed=False,
                      repair_attempted=True, repair_passed=True),
            self.case("multi-file-synthesis", True, first_pass_passed=True,
                      repair_attempted=False, repair_passed=False,
                      evidence_directory="/run/case2"),
        ]
        result = project_metrics(rows, self.metadata, self.catalog)["metrics"][0]
        self.assertEqual(result["first_pass"], {"numerator": 1, "denominator": 2})
        self.assertEqual(result["after_repair"], {"numerator": 1, "denominator": 1})
        self.assertEqual(result["numerator"], 2)

    def test_human_review_pending_is_not_implicitly_approved(self):
        row = self.case("minimal-code-repair", True, human_review_required=True,
                        human_review_status="recorded")
        self.assertEqual(case_status(row), "pending_review")
        result = project_metrics([row], self.metadata, self.catalog)["metrics"][0]
        self.assertIsNone(result["denominator"])
        self.assertEqual(result["pending_review_cases"], ["minimal-code-repair"])

    def test_execution_error_does_not_inherit_deterministic_pass(self):
        self.assertEqual(case_status({"execution_status": "protocol_failure",
                                      "deterministic_passed": True}), "unknown")

    def test_legacy_unknown_identity_is_not_comparable(self):
        result = project_metrics([{"case_id": "minimal-code-repair", "suite_id": "shared-l2-core",
            "suite_version": "1.0.0", "rubric_id": "shared-v2-evaluator", "rubric_version": "1", "deterministic_passed": True,
            "evidence_directory": "/old"}], {}, self.catalog)["metrics"][0]
        self.assertIsNone(result["denominator"])
        self.assertEqual(result["excluded"][0]["reason"], "unknown_model_or_runtime_identity")


if __name__ == "__main__":
    unittest.main()
