from __future__ import annotations

import unittest

from localbench.v2.contracts import EvidenceRef, seal_evidence
from localbench.v2.evaluators import (
    EVALUATOR_SPEC_VERSION,
    EvidenceConsumption,
    EvaluationCheck,
    EvaluationDraft,
    EvaluatorDefinition,
    EvaluatorRegistry,
    canonical_definition_bytes,
)
from localbench.v2.records import case_result


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


class V2EvaluatorFrameworkTests(unittest.TestCase):
    def _definition(
        self,
        *,
        requires_human_review: bool = False,
        scoring_mode: str = "weighted",
        extra_consumption: tuple[EvidenceConsumption, ...] = (),
    ) -> EvaluatorDefinition:
        return EvaluatorDefinition(
            evaluator_id="synthetic-status",
            contract_version="1",
            implementation_sha256=DIGEST_C,
            input_contract="benchmark-case+case-result:v2",
            result_contract="evaluation-result:v2",
            consumed_evidence=(
                EvidenceConsumption("case_result", required=True, multiple=False),
                *extra_consumption,
            ),
            requires_human_review=requires_human_review,
            scoring_mode=scoring_mode,
        )

    def _case_result(self, *, case_id: str = "case-1", status: str = "success"):
        return case_result(
            f"result-{case_id}",
            manifest=EvidenceRef("run_manifest", "run-a", DIGEST_A),
            benchmark=EvidenceRef("benchmark_input", "pack-a", DIGEST_B),
            trial=EvidenceRef("trial_identity", "trial-a", DIGEST_C),
            case_id=case_id,
            status=status,
            started_at="2026-09-11T00:00:00Z",
            finished_at="2026-09-11T00:00:01Z",
            metrics={"wall_seconds": 1.0},
            execution_evidence={"synthetic": True},
            terminal_output={"kind": "synthetic"},
        )

    def _case_definition(self, *, case_id: str = "case-1") -> dict:
        return {
            "case_id": case_id,
            "objective": "synthetic evaluator framework fixture",
            "evaluators": [
                {"evaluator_id": "synthetic-status", "contract_version": "1"}
            ],
            "hard_failure_rules": [
                {"evaluator_id": "synthetic-status", "rule_id": "execution-failure"}
            ],
        }

    @staticmethod
    def _status_evaluator(context):
        ok = context.case_result.payload["status"] == "success"
        return EvaluationDraft(
            verdict="pass" if ok else "fail",
            checks=(
                EvaluationCheck(
                    check_id="case-status",
                    passed=ok,
                    weight=10,
                    earned=10 if ok else 0,
                    detail="synthetic CaseResult status is success" if ok else "synthetic CaseResult status is not success",
                    evidence=(context.case_result.reference,),
                ),
            ),
            hard_failures=() if ok else ("execution-failure",),
        )

    def test_definition_is_content_addressed_and_identity_binds_implementation(self):
        definition = self._definition()
        changed = self._definition(
            extra_consumption=(
                EvidenceConsumption("benchmark_input", required=False, multiple=False),
            )
        )

        self.assertEqual(definition.schema_version, EVALUATOR_SPEC_VERSION)
        self.assertNotEqual(definition.definition_sha256, changed.definition_sha256)
        self.assertEqual(
            definition.identity.logical_id,
            f"eval-{definition.definition_sha256}",
        )
        self.assertEqual(
            definition.identity.payload["implementation_sha256"],
            DIGEST_C,
        )
        self.assertEqual(definition.identity.payload["version"], "1")

    def test_definition_round_trip_and_canonical_bytes_are_stable(self):
        definition = self._definition()
        restored = EvaluatorDefinition.from_mapping(definition.to_dict())

        self.assertEqual(restored, definition)
        self.assertEqual(restored.definition_sha256, definition.definition_sha256)
        self.assertEqual(canonical_definition_bytes(definition.to_dict()), canonical_definition_bytes(restored.to_dict()))

    def test_definition_rejects_unknown_fields_and_ambiguous_case_result_consumption(self):
        raw = self._definition().to_dict()
        raw["surprise"] = True
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            EvaluatorDefinition.from_mapping(raw)

        with self.assertRaisesRegex(ValueError, "exactly one required case_result"):
            EvaluatorDefinition(
                evaluator_id="bad",
                contract_version="1",
                implementation_sha256=DIGEST_A,
                input_contract="case-result:v2",
                result_contract="evaluation-result:v2",
                consumed_evidence=(
                    EvidenceConsumption("case_result", required=False, multiple=False),
                ),
                requires_human_review=False,
            )

    def test_registry_produces_normalized_sealed_evaluation_result(self):
        registry = EvaluatorRegistry()
        definition = self._definition()
        registry.register(definition, self._status_evaluator)

        result = registry.evaluate(
            "evaluation-1",
            evaluator_id="synthetic-status",
            contract_version="1",
            case_definition=self._case_definition(),
            case_result_record=self._case_result(),
            hard_failure_rules=["execution-failure"],
        )

        self.assertEqual(result.record_type, "evaluation_result")
        self.assertEqual(result.payload["verdict"], "pass")
        self.assertEqual(result.payload["score"], 10.0)
        self.assertEqual(result.payload["maximum_score"], 10.0)
        self.assertEqual(result.payload["hard_failures"], ())
        self.assertEqual(result.payload["checks"][0]["id"], "case-status")
        self.assertEqual(
            result.payload["evaluator"]["sha256"],
            definition.identity.sha256,
        )

    def test_hard_failure_is_structurally_separate_from_score(self):
        registry = EvaluatorRegistry()
        registry.register(self._definition(), self._status_evaluator)

        result = registry.evaluate(
            "evaluation-fail",
            evaluator_id="synthetic-status",
            contract_version="1",
            case_definition=self._case_definition(),
            case_result_record=self._case_result(status="error"),
            hard_failure_rules=["execution-failure"],
        )

        self.assertEqual(result.payload["verdict"], "fail")
        self.assertEqual(result.payload["score"], 0.0)
        self.assertEqual(result.payload["maximum_score"], 10.0)
        self.assertEqual(result.payload["hard_failures"], ("execution-failure",))

    def test_resolution_and_registration_fail_closed(self):
        registry = EvaluatorRegistry()
        definition = self._definition()
        registry.register(definition, self._status_evaluator)

        with self.assertRaisesRegex(KeyError, "unregistered evaluator"):
            registry.resolve("synthetic-status", "2")
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(definition, self._status_evaluator)

        mismatched_case = self._case_definition()
        mismatched_case["evaluators"] = [
            {"evaluator_id": "synthetic-status", "contract_version": "2"}
        ]
        with self.assertRaisesRegex(ValueError, "does not bind evaluator"):
            registry.evaluate(
                "bad-binding",
                evaluator_id="synthetic-status",
                contract_version="1",
                case_definition=mismatched_case,
                case_result_record=self._case_result(),
                hard_failure_rules=["execution-failure"],
            )

    def test_case_identity_and_evidence_surface_fail_closed(self):
        registry = EvaluatorRegistry()
        registry.register(self._definition(), self._status_evaluator)

        with self.assertRaisesRegex(ValueError, "case_id do not match"):
            registry.evaluate(
                "case-mismatch",
                evaluator_id="synthetic-status",
                contract_version="1",
                case_definition=self._case_definition(case_id="case-2"),
                case_result_record=self._case_result(case_id="case-1"),
                hard_failure_rules=["execution-failure"],
            )

        extra = seal_evidence("benchmark_input", "extra", {"synthetic": True})
        with self.assertRaisesRegex(ValueError, "did not declare consumption"):
            registry.evaluate(
                "extra-evidence",
                evaluator_id="synthetic-status",
                contract_version="1",
                case_definition=self._case_definition(),
                case_result_record=self._case_result(),
                supplemental_evidence=[extra],
                hard_failure_rules=["execution-failure"],
            )

    def test_declared_supplemental_evidence_can_be_consumed(self):
        definition = self._definition(
            extra_consumption=(
                EvidenceConsumption("benchmark_input", required=True, multiple=False),
            )
        )
        seen = []

        def evaluator(context):
            seen.append(context.evidence_by_type["benchmark_input"][0].logical_id)
            return EvaluationDraft(
                verdict="pass",
                checks=(
                    EvaluationCheck(
                        "supplemental-present",
                        True,
                        1,
                        1,
                        "declared synthetic supplemental evidence is present",
                    ),
                ),
            )

        registry = EvaluatorRegistry()
        registry.register(definition, evaluator)
        extra = seal_evidence("benchmark_input", "extra", {"synthetic": True})
        result = registry.evaluate(
            "with-extra",
            evaluator_id="synthetic-status",
            contract_version="1",
            case_definition=self._case_definition(),
            case_result_record=self._case_result(),
            supplemental_evidence=[extra],
            hard_failure_rules=["execution-failure"],
        )

        self.assertEqual(result.payload["verdict"], "pass")
        self.assertEqual(seen, ["extra"])

    def test_missing_required_supplemental_evidence_fails_closed(self):
        definition = self._definition(
            extra_consumption=(
                EvidenceConsumption("benchmark_input", required=True, multiple=False),
            )
        )
        registry = EvaluatorRegistry()
        registry.register(definition, self._status_evaluator)

        with self.assertRaisesRegex(ValueError, "required evaluator evidence is missing"):
            registry.evaluate(
                "missing-extra",
                evaluator_id="synthetic-status",
                contract_version="1",
                case_definition=self._case_definition(),
                case_result_record=self._case_result(),
                hard_failure_rules=["execution-failure"],
            )

    def test_undeclared_hard_failure_from_implementation_is_rejected(self):
        def evaluator(_context):
            return EvaluationDraft(
                verdict="fail",
                checks=(EvaluationCheck("x", False, 1, 0, "synthetic failure"),),
                hard_failures=("different-rule",),
            )

        registry = EvaluatorRegistry()
        registry.register(self._definition(), evaluator)
        with self.assertRaisesRegex(ValueError, "undeclared hard-failure"):
            registry.evaluate(
                "bad-hard-failure",
                evaluator_id="synthetic-status",
                contract_version="1",
                case_definition=self._case_definition(),
                case_result_record=self._case_result(),
                hard_failure_rules=["execution-failure"],
            )

    def test_hard_failure_cannot_be_hidden_behind_pass_verdict(self):
        def evaluator(_context):
            return EvaluationDraft(
                verdict="pass",
                checks=(EvaluationCheck("x", True, 1, 1, "synthetic"),),
                hard_failures=("execution-failure",),
            )

        registry = EvaluatorRegistry()
        registry.register(self._definition(), evaluator)
        with self.assertRaisesRegex(ValueError, "hard failures require"):
            registry.evaluate(
                "hidden-hard-failure",
                evaluator_id="synthetic-status",
                contract_version="1",
                case_definition=self._case_definition(),
                case_result_record=self._case_result(),
                hard_failure_rules=["execution-failure"],
            )

    def test_human_review_evaluator_cannot_emit_final_pass(self):
        registry = EvaluatorRegistry()
        registry.register(
            self._definition(requires_human_review=True),
            self._status_evaluator,
        )
        with self.assertRaisesRegex(ValueError, "requiring human review"):
            registry.evaluate(
                "human-review-pass",
                evaluator_id="synthetic-status",
                contract_version="1",
                case_definition=self._case_definition(),
                case_result_record=self._case_result(),
                hard_failure_rules=["execution-failure"],
            )

    def test_unscored_evaluator_produces_null_score(self):
        definition = self._definition(scoring_mode="unscored")

        def evaluator(_context):
            return EvaluationDraft(
                verdict="not_scored",
                checks=(
                    EvaluationCheck(
                        "diagnostic-only",
                        True,
                        0,
                        0,
                        "synthetic diagnostic",
                    ),
                ),
            )

        registry = EvaluatorRegistry()
        registry.register(definition, evaluator)
        result = registry.evaluate(
            "unscored",
            evaluator_id="synthetic-status",
            contract_version="1",
            case_definition=self._case_definition(),
            case_result_record=self._case_result(),
            hard_failure_rules=["execution-failure"],
        )

        self.assertEqual(result.payload["verdict"], "not_scored")
        self.assertIsNone(result.payload["score"])
        self.assertIsNone(result.payload["maximum_score"])


if __name__ == "__main__":
    unittest.main()
