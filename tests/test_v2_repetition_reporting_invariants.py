from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from localbench.v2 import (
    BOUNDED_FILE_SURFACE_ID,
    BOUNDED_FILE_TOOL_SCHEMA_SHA256,
    CONFIG_SPEC_VERSION,
    REPETITION_PHASES,
    ConfigurationBinding,
    DriverBinding,
    EvidenceConsumption,
    EvidenceStore,
    EvaluationCheck,
    EvaluationDraft,
    EvaluatorDefinition,
    EvaluatorRegistry,
    ModelTurnResponse,
    OrchestrationBlocked,
    RepeatedRun,
    WorkspaceBinding,
    aggregate_repeated_run,
    case_result,
    evaluation_result,
    host_profile,
    model_identity,
    run_v2_repetitions,
    runtime_profile,
)


MODEL_DIGEST = "a" * 64
DRIVER_DIGEST = "d" * 64
EVALUATOR_DIGEST = "e" * 64
HARNESS_COMMIT = "b" * 64


def foundation():
    host = host_profile(
        "host-bl8b-invariants",
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
        "runtime-bl8b-invariants",
        runtime_kind="fake",
        version="1",
        build=None,
        transport={"kind": "injected"},
        executable=None,
        installation_digest=None,
        capabilities={"chat": True, "tools": True},
    )
    model = model_identity(
        "model-bl8b-invariants",
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


def pack_bytes(*, level: str, trials: int) -> bytes:
    tool_surface = {"id": "none", "required_tools": []}
    if level == "L2":
        tool_surface = {
            "id": "bounded-files-v1",
            "required_tools": ["read_file", "write_file"],
        }
    return json.dumps(
        {
            "schema_version": "benchmark-lab-pack:v2",
            "pack_id": f"bl8b-invariants-{level.lower()}",
            "pack_version": "1.0.0",
            "name": "BL-8B invariants fixture",
            "description": "Synthetic engineering fixture only.",
            "level": level,
            "cases": [
                {
                    "case_id": "case-a",
                    "objective": "Exercise BL-8B invariants.",
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
                        {
                            "evaluator_id": "synthetic-evaluator",
                            "contract_version": "1.0.0",
                        }
                    ],
                    "hard_failure_rules": [],
                    "repetitions": {
                        "screen_trials": trials,
                        "qualification_trials": trials,
                    },
                    "tags": ["engineering"],
                }
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")


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
        return EvaluationDraft(
            verdict="pass",
            checks=(
                EvaluationCheck(
                    "synthetic-check",
                    True,
                    1.0,
                    1.0,
                    "deterministic synthetic outcome",
                ),
            ),
        )

    values.register(definition, implementation)
    return values


def clock_for(trials: int):
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


class BL8BInvariantTests(unittest.TestCase):
    def test_repetition_phase_contract_and_planned_counts_are_immutable(self):
        with self.assertRaises(TypeError):
            REPETITION_PHASES["invented"] = "invented_trials"  # type: ignore[index]

        host, runtime, model = foundation()
        with tempfile.TemporaryDirectory() as temp_dir:
            run = run_v2_repetitions(
                run_id="run-immutable-plan",
                repetition_phase="screen",
                pack_source=pack_bytes(level="L0", trials=1),
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
                evidence_store=EvidenceStore(Path(temp_dir) / "evidence"),
                harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                clock=clock_for(1),
            )
            with self.assertRaises(TypeError):
                run.planned_counts["case-a"] = 99  # type: ignore[index]

    def test_repeated_l2_without_workspace_factory_fails_before_manifest_or_driver(self):
        host, runtime, model = foundation()
        called = False
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "workspace"
            root.mkdir()
            (root / "input.txt").write_text("same", encoding="utf-8")
            store = EvidenceStore(Path(temp_dir) / "evidence")

            def driver(request):
                nonlocal called
                called = True
                return ModelTurnResponse(content="must not run")

            with self.assertRaisesRegex(OrchestrationBlocked, "require workspace_factory"):
                run_v2_repetitions(
                    run_id="run-no-factory",
                    repetition_phase="screen",
                    pack_source=pack_bytes(level="L2", trials=2),
                    pack_source_locator=None,
                    host=host,
                    runtime=runtime,
                    model=model,
                    configuration_bindings={"profile-a": configuration(tools=True)},
                    evaluator_registry=registry(),
                    driver_binding=DriverBinding("fake-tool-driver", DRIVER_DIGEST, driver),
                    evidence_store=store,
                    harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                    workspaces={
                        "case-a": WorkspaceBinding(
                            root=root,
                            readable_paths=("input.txt",),
                            writable_paths=("out.txt",),
                        )
                    },
                )
            self.assertFalse(called)
            self.assertFalse((store.root / "records" / "run_manifest").exists())

    def test_repeated_l2_workspace_root_reuse_fails_before_driver(self):
        host, runtime, model = foundation()
        called = False
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "workspace"
            root.mkdir()
            (root / "input.txt").write_text("same", encoding="utf-8")
            binding = WorkspaceBinding(
                root=root,
                readable_paths=("input.txt",),
                writable_paths=("out.txt",),
            )
            store = EvidenceStore(Path(temp_dir) / "evidence")

            def driver(request):
                nonlocal called
                called = True
                return ModelTurnResponse(content="must not run")

            with self.assertRaisesRegex(OrchestrationBlocked, "distinct roots"):
                run_v2_repetitions(
                    run_id="run-root-reuse",
                    repetition_phase="screen",
                    pack_source=pack_bytes(level="L2", trials=2),
                    pack_source_locator=None,
                    host=host,
                    runtime=runtime,
                    model=model,
                    configuration_bindings={"profile-a": configuration(tools=True)},
                    evaluator_registry=registry(),
                    driver_binding=DriverBinding("fake-tool-driver", DRIVER_DIGEST, driver),
                    evidence_store=store,
                    harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                    workspace_factory=lambda case_id, ordinal: binding,
                )
            self.assertFalse(called)

    def test_explicit_attempt_retry_and_telemetry_measurements_are_aggregated(self):
        host, runtime, model = foundation()
        with tempfile.TemporaryDirectory() as temp_dir:
            run = run_v2_repetitions(
                run_id="run-measured-telemetry",
                repetition_phase="screen",
                pack_source=pack_bytes(level="L0", trials=1),
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
                evidence_store=EvidenceStore(Path(temp_dir) / "evidence"),
                harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                clock=clock_for(1),
            )

            old_case = run.case_results[0]
            metrics = dict(old_case.payload["metrics"])
            metrics.update(
                {
                    "attempts": 2,
                    "retries": 1,
                    "telemetry": {
                        "peak_ram_bytes": 200.0,
                        "peak_vram_bytes": 100.0,
                        "gpu_utilization_percent": None,
                    },
                }
            )
            measured_case = case_result(
                "case-measured-telemetry",
                manifest=run.manifest.reference,
                benchmark=run.benchmark.reference,
                trial=run.trials[0].reference,
                case_id="case-a",
                status=old_case.payload["status"],
                started_at=old_case.payload["started_at"],
                finished_at=old_case.payload["finished_at"],
                metrics=metrics,
                execution_evidence=dict(old_case.payload["execution_evidence"]),
                terminal_output=None
                if old_case.payload["terminal_output"] is None
                else dict(old_case.payload["terminal_output"]),
            )
            old_evaluation = run.evaluation_results[0]
            measured_evaluation = evaluation_result(
                "evaluation-measured-telemetry",
                case=measured_case.reference,
                evaluator=old_evaluation.payload["evaluator"],
                verdict=old_evaluation.payload["verdict"],
                score=old_evaluation.payload["score"],
                maximum_score=old_evaluation.payload["maximum_score"],
                hard_failures=tuple(old_evaluation.payload["hard_failures"]),
                checks=tuple(dict(item) for item in old_evaluation.payload["checks"]),
            )
            measured_run: RepeatedRun = replace(
                run,
                case_results=(measured_case,),
                evaluation_results=(measured_evaluation,),
            )
            report = aggregate_repeated_run("aggregate-measured-telemetry", measured_run)
            execution = report.payload["cases"][0]["execution"]
            self.assertEqual(execution["attempts"]["measured"], 1)
            self.assertEqual(execution["attempts"]["mean"], 2.0)
            self.assertEqual(execution["retries"]["mean"], 1.0)
            self.assertEqual(execution["telemetry"]["peak_ram_bytes"]["mean"], 200.0)
            self.assertEqual(execution["telemetry"]["peak_vram_bytes"]["mean"], 100.0)
            self.assertNotIn("gpu_utilization_percent", execution["telemetry"])


if __name__ == "__main__":
    unittest.main()
