from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from localbench.v2 import (
    BOUNDED_FILE_SURFACE_ID,
    BOUNDED_FILE_TOOL_SCHEMA_SHA256,
    CONFIG_SPEC_VERSION,
    BackendExecution,
    CommandSpec,
    ConfigurationBinding,
    ContainmentBlocked,
    ContainmentCapabilities,
    ContainmentExecutor,
    ContainmentPolicy,
    DriverBinding,
    EvidenceConsumption,
    EvidenceStore,
    EvaluationCheck,
    EvaluationDraft,
    EvaluatorDefinition,
    EvaluatorRegistry,
    ModelTurnResponse,
    NativeSubprocessBackend,
    ToolCall,
    WorkspaceBinding,
    aggregate_repeated_run,
    host_profile,
    model_identity,
    persist_aggregate_report,
    run_v2_repetitions,
    runtime_profile,
)


MODEL_DIGEST = "a" * 64
DRIVER_DIGEST = "d" * 64
EVALUATOR_DIGEST = "e" * 64
HARNESS_COMMIT = "b" * 64
WRONG_DIGEST = hashlib.sha256(b"different").hexdigest()


def foundation():
    host = host_profile(
        "host-construction-gate",
        captured_at="2026-09-11T00:00:00Z",
        os_info={"name": "synthetic", "build": "1"},
        cpu={"model": "synthetic-cpu", "physical_cores": 4, "logical_cores": 8},
        memory={"installed_bytes": 16_000_000_000, "available_bytes": None},
        gpus=[],
        storage=[
            {"volume": "synthetic", "total_bytes": 1_000_000_000, "free_bytes": None}
        ],
        python={"version": "3.12", "implementation": "CPython"},
        compute_runtimes=[],
        power_thermal=None,
    )
    runtime = runtime_profile(
        "runtime-construction-gate",
        runtime_kind="fake",
        version="1",
        build=None,
        transport={"kind": "injected"},
        executable=None,
        installation_digest=None,
        capabilities={"chat": True, "tools": True},
    )
    model = model_identity(
        "model-construction-gate",
        family="synthetic",
        name="synthetic-model",
        source={"kind": "construction_acceptance_fixture"},
        artifact_digest=None,
        provider_digest=MODEL_DIGEST,
        parameter_count=None,
        quantization=None,
        precision=None,
        declared_context_tokens=8192,
    )
    return host, runtime, model


def configuration(profile_id: str, *, max_tool_calls: int) -> ConfigurationBinding:
    return ConfigurationBinding(
        profile_id,
        spec={
            "schema_version": CONFIG_SPEC_VERSION,
            "comparison_mode": "strict",
            "generation": {
                "context_tokens": 4096,
                "max_output_tokens": 512,
                "response_format": {"mode": "text", "schema": None},
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
                "id": BOUNDED_FILE_SURFACE_ID,
                "tools": ["read_file", "write_file"],
                "max_tool_calls": max_tool_calls,
                "schema_sha256": BOUNDED_FILE_TOOL_SCHEMA_SHA256,
            },
        },
        adapter_resolution={
            "adapter_id": "fake-adapter:v1",
            "status": "exact",
            "effective_request": {"synthetic": True, "profile": profile_id},
            "deviations": [],
        },
    )


def pack_bytes() -> bytes:
    portable_surface = {
        "id": "bounded-files-v1",
        "required_tools": ["read_file", "write_file"],
    }

    def case(case_id: str, *, profile_id: str = "profile-default", trials: int = 1):
        hard_failures = []
        if case_id == "hard-failure":
            hard_failures = [
                {
                    "evaluator_id": "construction-evaluator",
                    "rule_id": "synthetic-hard-failure",
                }
            ]
        return {
            "case_id": case_id,
            "objective": "Synthetic deterministic construction acceptance behavior.",
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": f"Execute synthetic fixture {case_id}.",
                    }
                ],
                "context_assets": [],
            },
            "requirements": {
                "configuration_profile": profile_id,
                "response_contract": {"mode": "text", "schema": None},
                "tool_surface": portable_surface,
                "minimum_context_tokens": 1024,
            },
            "evaluators": [
                {
                    "evaluator_id": "construction-evaluator",
                    "contract_version": "1.0.0",
                }
            ],
            "hard_failure_rules": hard_failures,
            "repetitions": {
                "screen_trials": trials,
                "qualification_trials": max(2, trials),
            },
            "tags": ["synthetic", "construction-acceptance"],
        }

    value = {
        "schema_version": "benchmark-lab-pack:v2",
        "pack_id": "v2-construction-acceptance",
        "pack_version": "1.0.0",
        "name": "V2 synthetic construction acceptance",
        "description": "No real model/provider execution.",
        "level": "L2",
        "cases": [
            case("authorized-rw", trials=2),
            case("unauthorized-path"),
            case("stale-write"),
            case("malformed-tool"),
            case("tool-limit", profile_id="profile-limit"),
            case("hard-failure"),
        ],
    }
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


class SyntheticDriver:
    def __call__(self, request):
        case_id = request.case_id
        turn = request.turn
        if case_id == "authorized-rw":
            if turn == 1:
                return ModelTurnResponse(
                    tool_calls=(ToolCall("read-input", "read_file", {"path": "input.txt"}),)
                )
            if turn == 2:
                result = request.messages[-1]["result"]
                return ModelTurnResponse(
                    tool_calls=(
                        ToolCall(
                            "write-output",
                            "write_file",
                            {
                                "path": "output.txt",
                                "content": str(result["content"]).upper(),
                                "expected_sha256": None,
                            },
                        ),
                    )
                )
            return ModelTurnResponse(content="authorized-complete")

        if case_id == "unauthorized-path":
            if turn == 1:
                return ModelTurnResponse(
                    tool_calls=(
                        ToolCall("escape-read", "read_file", {"path": "../secret.txt"}),
                    )
                )
            return ModelTurnResponse(content="unauthorized-observed")

        if case_id == "stale-write":
            if turn == 1:
                return ModelTurnResponse(
                    tool_calls=(
                        ToolCall(
                            "stale-write",
                            "write_file",
                            {
                                "path": "output.txt",
                                "content": "new\n",
                                "expected_sha256": WRONG_DIGEST,
                            },
                        ),
                    )
                )
            return ModelTurnResponse(content="stale-observed")

        if case_id == "malformed-tool":
            if turn == 1:
                return ModelTurnResponse(
                    tool_calls=(
                        ToolCall("malformed-write", "write_file", {"path": "output.txt"}),
                    )
                )
            return ModelTurnResponse(content="malformed-observed")

        if case_id == "tool-limit":
            return ModelTurnResponse(
                tool_calls=(
                    ToolCall(f"limit-read-{turn}", "read_file", {"path": "input.txt"}),
                )
            )

        if case_id == "hard-failure":
            return ModelTurnResponse(content="synthetic-hard-failure-output")

        raise AssertionError(f"unexpected synthetic case: {case_id}")


def _events(trace, event_type: str):
    return [
        event
        for event in trace.payload["events"]
        if event["event_type"] == event_type
    ]


def evaluator_registry() -> EvaluatorRegistry:
    registry = EvaluatorRegistry()
    definition = EvaluatorDefinition(
        evaluator_id="construction-evaluator",
        contract_version="1.0.0",
        implementation_sha256=EVALUATOR_DIGEST,
        input_contract="construction-fixture:v1",
        result_contract="construction-evaluation:v1",
        consumed_evidence=(
            EvidenceConsumption("case_result"),
            EvidenceConsumption("tool_execution_trace"),
        ),
        requires_human_review=False,
        scoring_mode="weighted",
    )

    def implementation(context):
        case_id = str(context.case_result.payload["case_id"])
        trace = context.evidence_by_type["tool_execution_trace"][0]
        summary = trace.payload["summary"]
        passed = True
        detail = "synthetic harness behavior matched expectation"

        if case_id == "authorized-rw":
            passed = (
                context.case_result.payload["status"] == "success"
                and summary["successful_tool_calls"] == 2
                and summary["denied_tool_calls"] == 0
            )
        elif case_id == "unauthorized-path":
            auth = _events(trace, "tool_authorization")
            passed = (
                context.case_result.payload["status"] == "success"
                and summary["denied_tool_calls"] == 1
                and len(auth) == 1
                and auth[0]["payload"]["reason"] == "invalid_path"
            )
        elif case_id == "stale-write":
            results = _events(trace, "tool_result")
            passed = (
                context.case_result.payload["status"] == "success"
                and summary["failed_tool_calls"] == 1
                and len(results) == 1
                and results[0]["payload"]["result"]["error"] == "stale_write"
            )
        elif case_id == "malformed-tool":
            auth = _events(trace, "tool_authorization")
            passed = (
                context.case_result.payload["status"] == "success"
                and summary["denied_tool_calls"] == 1
                and len(auth) == 1
                and auth[0]["payload"]["reason"] == "invalid_arguments"
            )
        elif case_id == "tool-limit":
            passed = (
                context.case_result.payload["status"] == "resource_limit"
                and summary["stop_reason"] == "max_tool_calls"
                and summary["tool_calls"] == 1
            )
        elif case_id == "hard-failure":
            return EvaluationDraft(
                verdict="fail",
                checks=(
                    EvaluationCheck(
                        "synthetic-hard-failure-check",
                        False,
                        1.0,
                        0.0,
                        "deliberate evaluator hard failure for construction acceptance",
                    ),
                ),
                hard_failures=("synthetic-hard-failure",),
            )
        else:
            raise AssertionError(f"unexpected evaluator case: {case_id}")

        return EvaluationDraft(
            verdict="pass" if passed else "fail",
            checks=(
                EvaluationCheck(
                    "synthetic-boundary-check",
                    passed,
                    1.0,
                    1.0 if passed else 0.0,
                    detail,
                ),
            ),
            hard_failures=(),
        )

    registry.register(definition, implementation)
    return registry


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


def build_workspace_factory(base: Path):
    base.mkdir(parents=True, exist_ok=True)
    roots = {}

    def factory(case_id: str, ordinal: int) -> WorkspaceBinding:
        root = base / f"{case_id}-{ordinal}"
        root.mkdir()
        if case_id in {"authorized-rw", "tool-limit"}:
            content = "alpha\n" if case_id == "authorized-rw" else "x\n"
            (root / "input.txt").write_text(content, encoding="utf-8", newline="\n")
        if case_id == "stale-write":
            (root / "output.txt").write_text("old\n", encoding="utf-8", newline="\n")
        roots[(case_id, ordinal)] = root
        return WorkspaceBinding(
            root=root,
            readable_paths=("input.txt", "output.txt"),
            writable_paths=("output.txt",),
        )

    return factory, roots


def run_synthetic_campaign(base: Path, store: EvidenceStore):
    host, runtime, model = foundation()
    factory, roots = build_workspace_factory(base)
    run = run_v2_repetitions(
        run_id="construction-gate-run",
        repetition_phase="screen",
        pack_source=pack_bytes(),
        pack_source_locator=None,
        host=host,
        runtime=runtime,
        model=model,
        configuration_bindings={
            "profile-default": configuration("profile-default", max_tool_calls=4),
            "profile-limit": configuration("profile-limit", max_tool_calls=1),
        },
        evaluator_registry=evaluator_registry(),
        driver_binding=DriverBinding(
            "synthetic-construction-driver",
            DRIVER_DIGEST,
            SyntheticDriver(),
        ),
        evidence_store=store,
        harness_source={"kind": "git", "commit": HARNESS_COMMIT},
        workspace_factory=factory,
        clock=fixed_clock(7),
    )
    report = aggregate_repeated_run("construction-gate-report", run)
    persist_aggregate_report(report, store)
    return run, report, roots


def evidence_identity(run, report):
    return {
        "benchmark": run.benchmark.sha256,
        "configs": [item.sha256 for item in run.effective_configs],
        "trials": [item.sha256 for item in run.trials],
        "bindings": [item.sha256 for item in run.execution_bindings],
        "manifest": run.manifest.sha256,
        "execution": [item.sha256 for item in run.execution_evidence],
        "cases": [item.sha256 for item in run.case_results],
        "evaluations": [item.sha256 for item in run.evaluation_results],
        "report": report.sha256,
    }


class FakeStrictBackend:
    def __init__(self, *, status: str = "completed") -> None:
        self.calls = 0
        self.status = status

    @property
    def capabilities(self) -> ContainmentCapabilities:
        return ContainmentCapabilities(
            backend_id="synthetic-strict",
            backend_version="1",
            wall_clock_timeout=True,
            process_custody="strict",
            network_policies=("disabled", "provider_only", "task_allowed"),
            workspace_isolation=True,
            workspace_write_scope=True,
            assessor_isolation=True,
            output_limit=True,
            memory_limit=True,
        )

    def execute(self, command: CommandSpec, policy: ContainmentPolicy) -> BackendExecution:
        self.calls += 1
        if self.status == "timeout":
            return BackendExecution(
                status="timeout",
                stop_reason="wall_clock_limit",
                exit_code=-1,
                stdout=b"partial",
                stderr=b"",
                duration_seconds=policy.wall_seconds,
                cleanup_performed=True,
            )
        return BackendExecution(
            status="completed",
            stop_reason="process_exit",
            exit_code=0,
            stdout=b"ok\n",
            stderr=b"",
            duration_seconds=0.01,
            cleanup_performed=False,
        )


def strict_policy(*, max_attempts: int = 1) -> ContainmentPolicy:
    return ContainmentPolicy(
        wall_seconds=5,
        max_attempts=max_attempts,
        network_policy="disabled",
        process_custody="strict",
        require_workspace_isolation=True,
        require_assessor_isolation=True,
        writable_paths=("output.txt",),
        max_output_bytes=1024,
        max_memory_bytes=64_000_000,
    )


class V2ConstructionAcceptanceTests(unittest.TestCase):
    def test_complete_synthetic_l2_campaign_and_replay_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = EvidenceStore(root / "evidence")

            first_base = root / "first"
            first_base.mkdir()
            first_secret = first_base / "secret.txt"
            first_secret.write_text("must remain private", encoding="utf-8")
            first, first_report, first_roots = run_synthetic_campaign(first_base, store)

            self.assertEqual(first.planned_counts["authorized-rw"], 2)
            self.assertEqual(sum(first.planned_counts.values()), 7)
            self.assertEqual(len(first.case_results), 7)
            self.assertEqual(len(first.evaluation_results), 7)
            self.assertEqual(first_report.payload["planned_trials"], 7)
            self.assertEqual(first_report.payload["observed_trials"], 7)

            status_counts = first_report.payload["overall"]["execution"]["status_counts"]
            self.assertEqual(status_counts["resource_limit"], 1)
            self.assertEqual(status_counts["success"], 6)
            evaluation = first_report.payload["overall"]["evaluation"]
            self.assertAlmostEqual(evaluation["pass_rate"], 6 / 7)
            self.assertEqual(evaluation["hard_failures"]["total"], 1)
            self.assertEqual(
                evaluation["hard_failures"]["by_rule"],
                {"synthetic-hard-failure": 1},
            )

            self.assertEqual(
                (first_roots[("authorized-rw", 1)] / "output.txt").read_text(encoding="utf-8"),
                "ALPHA\n",
            )
            self.assertEqual(
                (first_roots[("authorized-rw", 2)] / "output.txt").read_text(encoding="utf-8"),
                "ALPHA\n",
            )
            self.assertEqual(
                (first_roots[("stale-write", 1)] / "output.txt").read_text(encoding="utf-8"),
                "old\n",
            )
            self.assertFalse((first_roots[("malformed-tool", 1)] / "output.txt").exists())
            self.assertEqual(first_secret.read_text(encoding="utf-8"), "must remain private")

            first_identity = evidence_identity(first, first_report)
            second_base = root / "second"
            second_base.mkdir()
            second_secret = second_base / "secret.txt"
            second_secret.write_text("different private bytes", encoding="utf-8")
            second, second_report, _ = run_synthetic_campaign(second_base, store)
            self.assertEqual(evidence_identity(second, second_report), first_identity)
            self.assertEqual(second_secret.read_text(encoding="utf-8"), "different private bytes")
            self.assertTrue(store.contains(second_report))

            case_refs = {
                item["sha256"]
                for item in first_report.payload["evidence"]["case_results"]
            }
            self.assertEqual(case_refs, {item.sha256 for item in first.case_results})

    def test_subprocess_containment_preflight_refuses_before_driver_or_manifest(self):
        host, runtime, model = foundation()
        called = False

        def driver(request):
            nonlocal called
            called = True
            return ModelTurnResponse(content="must-not-run")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir) / "evidence")
            binding = DriverBinding(
                "synthetic-subprocess-driver",
                DRIVER_DIGEST,
                driver,
                execution_kind="subprocess",
                containment_policy=strict_policy(),
                containment_backend=NativeSubprocessBackend(),
            )
            with self.assertRaises(ContainmentBlocked):
                run_v2_repetitions(
                    run_id="construction-containment-refusal",
                    repetition_phase="screen",
                    pack_source=pack_bytes(),
                    pack_source_locator=None,
                    host=host,
                    runtime=runtime,
                    model=model,
                    configuration_bindings={
                        "profile-default": configuration("profile-default", max_tool_calls=4),
                        "profile-limit": configuration("profile-limit", max_tool_calls=1),
                    },
                    evaluator_registry=evaluator_registry(),
                    driver_binding=binding,
                    evidence_store=store,
                    harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                )
            self.assertFalse(called)
            self.assertFalse((store.root / "records" / "run_manifest").exists())

    def test_bl7_attempt_limit_and_timeout_evidence_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path(temp_dir)
            policy = strict_policy(max_attempts=1)
            backend = FakeStrictBackend()
            executor = ContainmentExecutor(backend, policy)
            command = CommandSpec(
                "construction-attempt-limit",
                ("python", "-c", "print('synthetic')"),
                cwd,
                cwd_role="candidate_workspace",
            )
            first = executor.execute(command)
            self.assertEqual(first.attempt, 1)
            self.assertEqual(first.status, "completed")
            with self.assertRaisesRegex(ContainmentBlocked, "maximum attempt count"):
                executor.execute(command)
            self.assertEqual(backend.calls, 1)

            timeout_backend = FakeStrictBackend(status="timeout")
            timeout = ContainmentExecutor(timeout_backend, policy).execute(
                CommandSpec(
                    "construction-timeout",
                    ("python", "-c", "pass"),
                    cwd,
                    cwd_role="candidate_workspace",
                )
            )
            self.assertEqual(timeout.status, "timeout")
            self.assertEqual(timeout.stop_reason, "wall_clock_limit")
            self.assertEqual(timeout.evidence.record_type, "containment_execution")
            self.assertEqual(timeout.evidence.payload["status"], "timeout")
            self.assertEqual(timeout.evidence.payload["stop_reason"], "wall_clock_limit")
            self.assertTrue(timeout.evidence.payload["cleanup_performed"])


if __name__ == "__main__":
    unittest.main()
