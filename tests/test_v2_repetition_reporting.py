from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from localbench.v2.configuration import (
    CONFIG_SPEC_VERSION,
    resolve_effective_configuration,
)
from localbench.v2.evaluators import (
    EvidenceConsumption,
    EvaluationCheck,
    EvaluationDraft,
    EvaluatorDefinition,
    EvaluatorRegistry,
)
from localbench.v2.orchestrator import (
    ConfigurationBinding,
    DriverBinding,
    EvidenceStore,
    OrchestrationBlocked,
    WorkspaceBinding,
)
from localbench.v2.records import host_profile, model_identity, runtime_profile
from localbench.v2.repetition import run_v2_repetitions
from localbench.v2.reporting import (
    aggregate_repeated_run,
    persist_aggregate_report,
    render_aggregate_csv,
    render_aggregate_markdown,
)
from localbench.v2.tool_harness import (
    BOUNDED_FILE_SURFACE_ID,
    BOUNDED_FILE_TOOL_SCHEMA_SHA256,
    ModelTurnResponse,
    ToolCall,
)


MODEL_DIGEST = "a" * 64
DRIVER_DIGEST = "d" * 64
EVALUATOR_DIGEST = "e" * 64
HARNESS_COMMIT = "b" * 64


def foundation():
    host = host_profile(
        "host-bl8b",
        captured_at="2026-09-11T00:00:00Z",
        os_info={"name": "test", "build": "1"},
        cpu={"model": "cpu", "physical_cores": 4, "logical_cores": 8},
        memory={"installed_bytes": 16_000_000_000, "available_bytes": None},
        gpus=[],
        storage=[{"volume": "test", "total_bytes": 1_000_000_000, "free_bytes": None}],
        python={"version": "3.12", "implementation": "CPython"},
        compute_runtimes=[],
        power_thermal=None,
    )
    runtime = runtime_profile(
        "runtime-bl8b",
        runtime_kind="fake",
        version="1",
        build=None,
        transport={"kind": "injected"},
        executable=None,
        installation_digest=None,
        capabilities={"chat": True, "tools": True},
    )
    model = model_identity(
        "model-bl8b",
        family="synthetic",
        name="synthetic-model",
        source={"kind": "engineering_fixture"},
        artifact_digest=None,
        provider_digest=MODEL_DIGEST,
        parameter_count=None,
        quantization=None,
        precision=None,
        declared_context_tokens=8192,
    )
    return host, runtime, model


def configuration(*, tools: bool) -> ConfigurationBinding:
    return ConfigurationBinding(
        "profile-a",
        spec={
            "schema_version": CONFIG_SPEC_VERSION,
            "comparison_mode": "strict",
            "generation": {
                "context_tokens": 4096,
                "max_output_tokens": 512,
                "response_format": {"mode": "text", "schema": None},
                "reasoning": {"mode": "disabled", "effort": None},
            },
            "execution": {
                "timeout_seconds": 30,
                "model_residency": {
                    "mode": "unload_after_model",
                    "keep_alive_seconds": 0,
                },
                "network_policy": "provider_only",
            },
            "tool_surface": {
                "id": BOUNDED_FILE_SURFACE_ID if tools else "none",
                "tools": ["read_file", "write_file"] if tools else [],
                "max_tool_calls": 4 if tools else 0,
                "schema_sha256": BOUNDED_FILE_TOOL_SCHEMA_SHA256 if tools else None,
            },
        },
        adapter_resolution={
            "adapter_id": "fake-adapter:v1",
            "status": "exact",
            "effective_request": {"synthetic": True},
            "deviations": [],
        },
    )


def pack_bytes(
    *,
    level: str,
    screen_trials: int,
    qualification_trials: int,
    two_cases: bool = False,
) -> bytes:
    tool_surface = {"id": "none", "required_tools": []}
    if level == "L2":
        tool_surface = {
            "id": "bounded-files-v1",
            "required_tools": ["read_file", "write_file"],
        }

    def case(case_id: str, screen: int, qualification: int):
        return {
            "case_id": case_id,
            "objective": "Synthetic BL-8B engineering fixture.",
            "input": {
                "messages": [{"role": "user", "content": "synthetic"}],
                "context_assets": [],
            },
            "requirements": {
                "configuration_profile": "profile-a",
                "response_contract": {"mode": "text", "schema": None},
                "tool_surface": tool_surface,
                "minimum_context_tokens": 1024,
            },
            "evaluators": [
                {"evaluator_id": "synthetic-evaluator", "contract_version": "1.0.0"}
            ],
            "hard_failure_rules": [
                {"evaluator_id": "synthetic-evaluator", "rule_id": "synthetic-failure"}
            ],
            "repetitions": {
                "screen_trials": screen,
                "qualification_trials": qualification,
            },
            "tags": ["engineering"],
        }

    cases = [case("case-a", screen_trials, qualification_trials)]
    if two_cases:
        cases.append(case("case-b", screen_trials + 1, qualification_trials + 1))
    value = {
        "schema_version": "benchmark-lab-pack:v2",
        "pack_id": f"bl8b-{level.lower()}",
        "pack_version": "1.0.0",
        "name": "BL-8B synthetic fixture",
        "description": "Engineering fixture only.",
        "level": level,
        "cases": cases,
    }
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def registry() -> EvaluatorRegistry:
    values = EvaluatorRegistry()
    definition = EvaluatorDefinition(
        evaluator_id="synthetic-evaluator",
        contract_version="1.0.0",
        implementation_sha256=EVALUATOR_DIGEST,
        input_contract="synthetic-input:v1",
        result_contract="synthetic-result:v1",
        consumed_evidence=(EvidenceConsumption("case_result"),),
        requires_human_review=False,
        scoring_mode="weighted",
    )

    def implementation(context):
        terminal = context.case_result.payload.get("terminal_output")
        content = "" if terminal is None else str(terminal.get("content", ""))
        passed = content != "bad"
        return EvaluationDraft(
            verdict="pass" if passed else "fail",
            checks=(
                EvaluationCheck(
                    "synthetic-check",
                    passed,
                    1.0,
                    1.0 if passed else 0.0,
                    "deterministic synthetic outcome",
                ),
            ),
            hard_failures=() if passed else ("synthetic-failure",),
        )

    values.register(definition, implementation)
    return values


def fixed_clock(trials: int):
    values = []
    for index in range(trials):
        values.extend(
            [
                f"2026-09-11T00:00:{index * 2:02d}Z",
                f"2026-09-11T00:00:{index * 2 + 1:02d}Z",
            ]
        )
    iterator = iter(values)
    return lambda: next(iterator)


class BL8BRepetitionReportingTests(unittest.TestCase):
    def test_presealed_effective_configuration_identity_is_reused_exactly(self):
        host, runtime, model = foundation()
        base = configuration(tools=False)
        expected = resolve_effective_configuration(
            "config-candidate-profile-a",
            runtime=runtime,
            model=model,
            spec=base.spec,
            adapter_resolution=base.adapter_resolution,
        )
        binding = ConfigurationBinding(
            profile_id="profile-a",
            spec=base.spec,
            adapter_resolution=base.adapter_resolution,
            effective_logical_id=expected.logical_id,
            expected_effective_config=expected.reference,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            run = run_v2_repetitions(
                run_id="run-presealed-config",
                repetition_phase="screen",
                pack_source=pack_bytes(
                    level="L0", screen_trials=1, qualification_trials=3
                ),
                pack_source_locator=None,
                host=host,
                runtime=runtime,
                model=model,
                configuration_bindings={"profile-a": binding},
                evaluator_registry=registry(),
                driver_binding=DriverBinding(
                    "fake-driver",
                    DRIVER_DIGEST,
                    lambda request: ModelTurnResponse(content="good"),
                ),
                evidence_store=EvidenceStore(Path(temp_dir) / "evidence"),
                harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                clock=fixed_clock(1),
            )

        self.assertEqual(run.effective_configs, (expected,))
        self.assertEqual(
            run.trials[0].payload["effective_config"],
            expected.reference.to_dict(),
        )

    def test_presealed_effective_configuration_mismatch_blocks_before_driver(self):
        host, runtime, model = foundation()
        base = configuration(tools=False)
        changed_spec = {
            **base.spec,
            "generation": {
                **base.spec["generation"],
                "temperature": 0.25,
            },
        }
        expected = resolve_effective_configuration(
            "config-candidate-profile-a",
            runtime=runtime,
            model=model,
            spec=changed_spec,
            adapter_resolution=base.adapter_resolution,
        )
        binding = ConfigurationBinding(
            profile_id="profile-a",
            spec=base.spec,
            adapter_resolution=base.adapter_resolution,
            effective_logical_id=expected.logical_id,
            expected_effective_config=expected.reference,
        )
        called = False

        def driver(request):
            nonlocal called
            called = True
            return ModelTurnResponse(content="good")

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                OrchestrationBlocked, "presealed identity"
            ):
                run_v2_repetitions(
                    run_id="run-mismatched-config",
                    repetition_phase="screen",
                    pack_source=pack_bytes(
                        level="L0", screen_trials=1, qualification_trials=3
                    ),
                    pack_source_locator=None,
                    host=host,
                    runtime=runtime,
                    model=model,
                    configuration_bindings={"profile-a": binding},
                    evaluator_registry=registry(),
                    driver_binding=DriverBinding(
                        "fake-driver", DRIVER_DIGEST, driver
                    ),
                    evidence_store=EvidenceStore(
                        Path(temp_dir) / "evidence"
                    ),
                    harness_source={
                        "kind": "git",
                        "commit": HARNESS_COMMIT,
                    },
                    clock=fixed_clock(1),
                )

        self.assertFalse(called)

    def test_screen_phase_uses_each_cases_predeclared_count_and_ordinals(self):
        host, runtime, model = foundation()
        calls = 0

        def driver(request):
            nonlocal calls
            calls += 1
            return ModelTurnResponse(content="good")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir) / "evidence")
            run = run_v2_repetitions(
                run_id="run-screen",
                repetition_phase="screen",
                pack_source=pack_bytes(
                    level="L0", screen_trials=2, qualification_trials=4, two_cases=True
                ),
                pack_source_locator=None,
                host=host,
                runtime=runtime,
                model=model,
                configuration_bindings={"profile-a": configuration(tools=False)},
                evaluator_registry=registry(),
                driver_binding=DriverBinding("fake-driver", DRIVER_DIGEST, driver),
                evidence_store=store,
                harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                clock=fixed_clock(5),
            )

            self.assertEqual(run.planned_counts, {"case-a": 2, "case-b": 3})
            self.assertEqual(calls, 5)
            ordinals = {}
            for trial in run.trials:
                ordinals.setdefault(trial.payload["case_id"], []).append(trial.payload["ordinal"])
                self.assertIsNotNone(trial.payload["repeat_group"])
            self.assertEqual(ordinals, {"case-a": [1, 2], "case-b": [1, 2, 3]})
            self.assertEqual(len(run.manifest.payload["trials"]), 5)
            self.assertEqual(
                run.manifest.payload["harness_source"]["repetition_phase"], "screen"
            )

    def test_qualification_phase_uses_qualification_trials(self):
        host, runtime, model = foundation()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir) / "evidence")
            run = run_v2_repetitions(
                run_id="run-qualification",
                repetition_phase="qualification",
                pack_source=pack_bytes(
                    level="L0", screen_trials=1, qualification_trials=3
                ),
                pack_source_locator=None,
                host=host,
                runtime=runtime,
                model=model,
                configuration_bindings={"profile-a": configuration(tools=False)},
                evaluator_registry=registry(),
                driver_binding=DriverBinding(
                    "fake-driver",
                    DRIVER_DIGEST,
                    lambda request: ModelTurnResponse(content="good"),
                ),
                evidence_store=store,
                harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                clock=fixed_clock(3),
            )
            self.assertEqual(run.planned_counts, {"case-a": 3})
            self.assertEqual([item.payload["ordinal"] for item in run.trials], [1, 2, 3])

    def test_repeated_l2_requires_distinct_equal_start_workspaces(self):
        host, runtime, model = foundation()
        driver_calls = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            roots = []
            for ordinal in (1, 2):
                root = Path(temp_dir) / f"workspace-{ordinal}"
                root.mkdir()
                (root / "input.txt").write_text("same", encoding="utf-8")
                roots.append(root)

            def factory(case_id, ordinal):
                return WorkspaceBinding(
                    root=roots[ordinal - 1],
                    readable_paths=("input.txt",),
                    writable_paths=("out.txt",),
                )

            state = {}

            def driver(request):
                nonlocal driver_calls
                driver_calls += 1
                key = (request.case_id, request.turn, driver_calls)
                if request.turn == 1:
                    return ModelTurnResponse(
                        tool_calls=(ToolCall(f"read-{driver_calls}", "read_file", {"path": "input.txt"}),)
                    )
                if request.turn == 2:
                    return ModelTurnResponse(
                        tool_calls=(
                            ToolCall(
                                f"write-{driver_calls}",
                                "write_file",
                                {"path": "out.txt", "content": "done", "expected_sha256": None},
                            ),
                        )
                    )
                state[key] = True
                return ModelTurnResponse(content="good")

            store = EvidenceStore(Path(temp_dir) / "evidence")
            run = run_v2_repetitions(
                run_id="run-l2-repeat",
                repetition_phase="screen",
                pack_source=pack_bytes(
                    level="L2", screen_trials=2, qualification_trials=2
                ),
                pack_source_locator=None,
                host=host,
                runtime=runtime,
                model=model,
                configuration_bindings={"profile-a": configuration(tools=True)},
                evaluator_registry=registry(),
                driver_binding=DriverBinding("fake-tool-driver", DRIVER_DIGEST, driver),
                evidence_store=store,
                harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                workspace_factory=factory,
                clock=fixed_clock(2),
            )

            initial_ids = {
                item.payload["workspace_scope"]["initial_state_sha256"]
                for item in run.execution_bindings
            }
            self.assertEqual(len(initial_ids), 1)
            self.assertEqual((roots[0] / "out.txt").read_text(encoding="utf-8"), "done")
            self.assertEqual((roots[1] / "out.txt").read_text(encoding="utf-8"), "done")

    def test_repeated_l2_mismatched_start_state_blocks_before_driver_or_manifest(self):
        host, runtime, model = foundation()
        called = False
        with tempfile.TemporaryDirectory() as temp_dir:
            roots = []
            for ordinal, content in ((1, "one"), (2, "two")):
                root = Path(temp_dir) / f"workspace-{ordinal}"
                root.mkdir()
                (root / "input.txt").write_text(content, encoding="utf-8")
                roots.append(root)

            def factory(case_id, ordinal):
                return WorkspaceBinding(
                    root=roots[ordinal - 1],
                    readable_paths=("input.txt",),
                    writable_paths=("out.txt",),
                )

            def driver(request):
                nonlocal called
                called = True
                return ModelTurnResponse(content="must not run")

            store = EvidenceStore(Path(temp_dir) / "evidence")
            with self.assertRaisesRegex(OrchestrationBlocked, "inconsistent initial workspace"):
                run_v2_repetitions(
                    run_id="run-l2-bad-baseline",
                    repetition_phase="screen",
                    pack_source=pack_bytes(
                        level="L2", screen_trials=2, qualification_trials=2
                    ),
                    pack_source_locator=None,
                    host=host,
                    runtime=runtime,
                    model=model,
                    configuration_bindings={"profile-a": configuration(tools=True)},
                    evaluator_registry=registry(),
                    driver_binding=DriverBinding("fake-tool-driver", DRIVER_DIGEST, driver),
                    evidence_store=store,
                    harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                    workspace_factory=factory,
                )
            self.assertFalse(called)
            self.assertFalse((store.root / "records" / "run_manifest").exists())

    def test_aggregate_is_derived_evidence_with_statistics_and_raw_references(self):
        host, runtime, model = foundation()
        outputs = iter(("good", "bad", "good"))
        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir) / "evidence")
            run = run_v2_repetitions(
                run_id="run-report",
                repetition_phase="screen",
                pack_source=pack_bytes(
                    level="L0", screen_trials=3, qualification_trials=3
                ),
                pack_source_locator=None,
                host=host,
                runtime=runtime,
                model=model,
                configuration_bindings={"profile-a": configuration(tools=False)},
                evaluator_registry=registry(),
                driver_binding=DriverBinding(
                    "fake-driver",
                    DRIVER_DIGEST,
                    lambda request: ModelTurnResponse(content=next(outputs)),
                ),
                evidence_store=store,
                harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                clock=fixed_clock(3),
            )
            report = aggregate_repeated_run("aggregate-report-a", run)
            persist_aggregate_report(report, store)

            case = report.payload["cases"][0]
            evaluation = case["evaluation"]
            execution = case["execution"]
            self.assertAlmostEqual(evaluation["pass_rate"], 2 / 3)
            self.assertAlmostEqual(evaluation["normalized_score"]["mean"], 2 / 3)
            self.assertEqual(evaluation["normalized_score"]["median"], 1.0)
            self.assertAlmostEqual(
                evaluation["normalized_score"]["population_variance"], 2 / 9
            )
            self.assertEqual(evaluation["hard_failures"]["total"], 1)
            self.assertEqual(
                evaluation["hard_failures"]["by_rule"], {"synthetic-failure": 1}
            )
            self.assertEqual(execution["duration_seconds"]["mean"], 1.0)
            self.assertEqual(execution["attempts"]["measured"], 0)
            self.assertIsNone(execution["attempts"]["mean"])
            self.assertEqual(execution["telemetry"], {})
            self.assertEqual(len(case["evidence"]["trials"]), 3)
            self.assertEqual(len(case["evidence"]["case_results"]), 3)
            self.assertEqual(len(case["evidence"]["evaluation_results"]), 3)
            self.assertTrue(store.contains(report))

            markdown = render_aggregate_markdown(report)
            csv_text = render_aggregate_csv(report)
            self.assertIn("Aggregates are derived evidence only", markdown)
            self.assertIn(report.sha256, markdown)
            self.assertIn("case_id,planned_trials,observed_trials", csv_text)
            self.assertIn("case-a,3,3,3", csv_text)

    def test_report_persistence_does_not_rewrite_raw_case_evidence(self):
        host, runtime, model = foundation()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir) / "evidence")
            run = run_v2_repetitions(
                run_id="run-raw-preservation",
                repetition_phase="screen",
                pack_source=pack_bytes(
                    level="L0", screen_trials=1, qualification_trials=1
                ),
                pack_source_locator=None,
                host=host,
                runtime=runtime,
                model=model,
                configuration_bindings={"profile-a": configuration(tools=False)},
                evaluator_registry=registry(),
                driver_binding=DriverBinding(
                    "fake-driver",
                    DRIVER_DIGEST,
                    lambda request: ModelTurnResponse(content="good"),
                ),
                evidence_store=store,
                harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                clock=fixed_clock(1),
            )
            raw_path = store.path_for(run.case_results[0])
            before = raw_path.read_bytes()
            report = aggregate_repeated_run("aggregate-raw-preservation", run)
            persist_aggregate_report(report, store)
            self.assertEqual(raw_path.read_bytes(), before)


    def test_model_driver_error_preserves_evidence_and_stops_before_scoring(self):
        host, runtime, model = foundation()

        def driver(request):
            raise RuntimeError("synthetic driver failure")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir) / "evidence")

            with self.assertRaisesRegex(
                OrchestrationBlocked,
                "qualification evidence was preserved and scoring was stopped",
            ):
                run_v2_repetitions(
                    run_id="run-driver-error",
                    repetition_phase="screen",
                    pack_source=pack_bytes(
                        level="L0",
                        screen_trials=1,
                        qualification_trials=1,
                    ),
                    pack_source_locator=None,
                    host=host,
                    runtime=runtime,
                    model=model,
                    configuration_bindings={
                        "profile-a": configuration(tools=False)
                    },
                    evaluator_registry=registry(),
                    driver_binding=DriverBinding(
                        "failing-driver",
                        DRIVER_DIGEST,
                        driver,
                    ),
                    evidence_store=store,
                    harness_source={
                        "kind": "git",
                        "commit": HARNESS_COMMIT,
                    },
                    clock=fixed_clock(1),
                )

            traces = list(
                (store.root / "records" / "intrinsic_execution_trace").glob("*.json")
            )
            cases = list(
                (store.root / "records" / "case_result").glob("*.json")
            )
            evaluations = list(
                (store.root / "records" / "evaluation_result").glob("*.json")
            )

            self.assertEqual(len(traces), 1)
            self.assertEqual(len(cases), 1)
            self.assertEqual(len(evaluations), 0)

            case_payload = json.loads(
                cases[0].read_text(encoding="utf-8")
            )["payload"]

            self.assertEqual(case_payload["status"], "error")
            self.assertEqual(
                case_payload["metrics"]["stop_reason"],
                "model_driver_error",
            )

if __name__ == "__main__":
    unittest.main()
