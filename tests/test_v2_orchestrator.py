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
    ConfigurationBinding,
    ContainmentBlocked,
    ContainmentCapabilities,
    ContainmentPolicy,
    DriverBinding,
    EvidenceConsumption,
    EvidenceStore,
    EvidenceStoreError,
    EvaluationCheck,
    EvaluationDraft,
    EvaluatorDefinition,
    EvaluatorRegistry,
    ModelTurnResponse,
    NativeSubprocessBackend,
    OrchestrationBlocked,
    ToolCall,
    WorkspaceBinding,
    host_profile,
    model_identity,
    resolve_effective_configuration,
    run_v2_pack,
    runtime_profile,
)
from localbench.v2.orchestrator import PORTABLE_BOUNDED_FILES_CAPABILITY


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DRIVER_DIGEST = "d" * 64
EVALUATOR_DIGEST = "e" * 64


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pack_bytes(*, level: str, asset: dict | None = None, response_mode: str = "text") -> bytes:
    tool_surface = {"id": "none", "required_tools": []}
    if level == "L2":
        tool_surface = {
            "id": PORTABLE_BOUNDED_FILES_CAPABILITY,
            "required_tools": ["read_file", "write_file"],
        }
    value = {
        "schema_version": "benchmark-lab-pack:v2",
        "pack_id": f"synthetic-{level.lower()}",
        "pack_version": "1.0.0",
        "name": "BL-8A engineering fixture",
        "description": "Synthetic fixture only; not a scored model benchmark.",
        "level": level,
        "cases": [
            {
                "case_id": "case-a",
                "objective": "Exercise deterministic orchestration.",
                "input": {
                    "messages": [{"role": "user", "content": "synthetic input"}],
                    "context_assets": [] if asset is None else [asset],
                },
                "requirements": {
                    "configuration_profile": "profile-a",
                    "response_contract": {"mode": response_mode, "schema": None},
                    "tool_surface": tool_surface,
                    "minimum_context_tokens": 1024,
                },
                "evaluators": [
                    {"evaluator_id": "synthetic-evaluator", "contract_version": "1.0.0"}
                ],
                "hard_failure_rules": [
                    {"evaluator_id": "synthetic-evaluator", "rule_id": "bad-execution"}
                ],
                "repetitions": {"screen_trials": 1, "qualification_trials": 3},
                "tags": ["engineering"],
            }
        ],
    }
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


class FakeStrictBackend:
    @property
    def capabilities(self):
        return ContainmentCapabilities(
            backend_id="fake-strict",
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

    def execute(self, command, policy):  # pragma: no cover - BL-8A must never call it
        raise AssertionError("BL-8A has no subprocess model-driver adapter")


class BL8AOrchestratorTests(unittest.TestCase):
    def foundation(self):
        host = host_profile(
            "host-test",
            captured_at="2026-09-11T00:00:00Z",
            os_info={"name": "test", "build": "1"},
            cpu={"model": "test-cpu", "physical_cores": 4, "logical_cores": 8},
            memory={"installed_bytes": 16_000_000_000, "available_bytes": None},
            gpus=[],
            storage=[{"volume": "test", "total_bytes": 1_000_000_000, "free_bytes": None}],
            python={"version": "3.12", "implementation": "CPython"},
            compute_runtimes=[],
            power_thermal=None,
        )
        runtime = runtime_profile(
            "runtime-test",
            runtime_kind="fake",
            version="1",
            build=None,
            transport={"kind": "injected"},
            executable=None,
            installation_digest=None,
            capabilities={"chat": True, "tools": True},
        )
        model = model_identity(
            "model-test",
            family="synthetic",
            name="synthetic-model",
            source={"kind": "engineering_fixture"},
            artifact_digest=None,
            provider_digest=DIGEST_A,
            parameter_count=None,
            quantization=None,
            precision=None,
            declared_context_tokens=8192,
        )
        return host, runtime, model

    def config(self, *, tools: bool):
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

    def registry(self, trace_type: str):
        registry = EvaluatorRegistry()
        definition = EvaluatorDefinition(
            evaluator_id="synthetic-evaluator",
            contract_version="1.0.0",
            implementation_sha256=EVALUATOR_DIGEST,
            input_contract="synthetic-input:v1",
            result_contract="synthetic-result:v1",
            consumed_evidence=(
                EvidenceConsumption("case_result"),
                EvidenceConsumption(trace_type),
                EvidenceConsumption("execution_binding"),
            ),
            requires_human_review=False,
            scoring_mode="weighted",
        )

        def implementation(context):
            trace = context.evidence_by_type[trace_type][0]
            binding = context.evidence_by_type["execution_binding"][0]
            passed = context.case_result.payload["status"] == "success"
            return EvaluationDraft(
                verdict="pass" if passed else "fail",
                checks=(
                    EvaluationCheck(
                        "execution-success",
                        passed,
                        1.0,
                        1.0 if passed else 0.0,
                        f"binding={binding.sha256}",
                        evidence=(trace.reference, binding.reference),
                    ),
                ),
                hard_failures=() if passed else ("bad-execution",),
            )

        registry.register(definition, implementation)
        return registry

    def fixed_clock(self):
        values = iter(("2026-09-11T00:00:01Z", "2026-09-11T00:00:02Z"))
        return lambda: next(values)

    def test_intrinsic_manifest_is_persisted_before_driver_and_evaluator_runs(self):
        host, runtime, model = self.foundation()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir) / "evidence")
            calls = []

            def driver(request):
                calls.append(request)
                manifest_dir = store.root / "records" / "run_manifest"
                binding_dir = store.root / "records" / "execution_binding"
                self.assertEqual(len(list(manifest_dir.glob("*.json"))), 1)
                self.assertEqual(len(list(binding_dir.glob("*.json"))), 1)
                self.assertEqual(tuple(request.tools), ())
                return ModelTurnResponse(content="synthetic answer")

            result = run_v2_pack(
                run_id="run-intrinsic",
                pack_source=pack_bytes(level="L0"),
                pack_source_locator=None,
                host=host,
                runtime=runtime,
                model=model,
                configuration_bindings={"profile-a": self.config(tools=False)},
                evaluator_registry=self.registry("intrinsic_execution_trace"),
                driver_binding=DriverBinding("fake-driver", DRIVER_DIGEST, driver),
                evidence_store=store,
                harness_source={"kind": "git", "commit": DIGEST_B},
                clock=self.fixed_clock(),
            )

            self.assertEqual(len(calls), 1)
            self.assertEqual(result.manifest.record_type, "run_manifest")
            self.assertEqual(len(result.execution_bindings), 1)
            self.assertEqual(result.execution_bindings[0].payload["execution_mode"], "intrinsic")
            self.assertEqual(result.case_results[0].payload["status"], "success")
            self.assertEqual(result.evaluation_results[0].payload["verdict"], "pass")
            self.assertEqual(store.load(result.manifest.reference), result.manifest)

    def test_pack_run_reuses_presealed_effective_configuration_identity(self):
        host, runtime, model = self.foundation()
        base = self.config(tools=False)
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
            result = run_v2_pack(
                run_id="run-presealed-config",
                pack_source=pack_bytes(level="L0"),
                pack_source_locator=None,
                host=host,
                runtime=runtime,
                model=model,
                configuration_bindings={"profile-a": binding},
                evaluator_registry=self.registry(
                    "intrinsic_execution_trace"
                ),
                driver_binding=DriverBinding(
                    "fake-driver",
                    DRIVER_DIGEST,
                    lambda request: ModelTurnResponse(content="answer"),
                ),
                evidence_store=EvidenceStore(Path(temp_dir) / "evidence"),
                harness_source={"kind": "git", "commit": DIGEST_B},
                clock=self.fixed_clock(),
            )

        self.assertEqual(result.effective_configs, (expected,))
        self.assertEqual(
            result.trials[0].payload["effective_config"],
            expected.reference.to_dict(),
        )

    def test_l1_asset_bytes_are_verified_and_locator_is_not_candidate_visible(self):
        host, runtime, model = self.foundation()
        data = b"private context bytes"
        asset = {
            "asset_id": "private-context",
            "sha256": sha(data),
            "media_type": "text/plain",
            "delivery": "inline_context",
            "source_locator": "D:/private/secret/context.txt",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir) / "evidence")

            def driver(request):
                candidate_asset = request.context_assets[0]
                self.assertNotIn("source_locator", candidate_asset)
                self.assertEqual(candidate_asset["content_utf8"], data.decode("utf-8"))
                return ModelTurnResponse(content="used context")

            result = run_v2_pack(
                run_id="run-l1",
                pack_source=pack_bytes(level="L1", asset=asset),
                pack_source_locator="private-pack.json",
                host=host,
                runtime=runtime,
                model=model,
                configuration_bindings={"profile-a": self.config(tools=False)},
                evaluator_registry=self.registry("intrinsic_execution_trace"),
                driver_binding=DriverBinding("fake-driver", DRIVER_DIGEST, driver),
                evidence_store=store,
                harness_source={"kind": "git", "commit": DIGEST_B},
                asset_loader=lambda descriptor: data,
                clock=self.fixed_clock(),
            )
            binding_asset = result.execution_bindings[0].payload["context_assets"][0]
            self.assertNotIn("source_locator", binding_asset)
            self.assertEqual(binding_asset["sha256"], sha(data))

    def test_asset_digest_mismatch_blocks_before_manifest_or_driver(self):
        host, runtime, model = self.foundation()
        asset = {
            "asset_id": "context",
            "sha256": "f" * 64,
            "media_type": "text/plain",
            "delivery": "inline_context",
            "source_locator": "fixture.txt",
        }
        called = False

        def driver(request):
            nonlocal called
            called = True
            return ModelTurnResponse(content="should not run")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir) / "evidence")
            with self.assertRaisesRegex(OrchestrationBlocked, "digest mismatch"):
                run_v2_pack(
                    run_id="run-bad-asset",
                    pack_source=pack_bytes(level="L1", asset=asset),
                    pack_source_locator=None,
                    host=host,
                    runtime=runtime,
                    model=model,
                    configuration_bindings={"profile-a": self.config(tools=False)},
                    evaluator_registry=self.registry("intrinsic_execution_trace"),
                    driver_binding=DriverBinding("fake-driver", DRIVER_DIGEST, driver),
                    evidence_store=store,
                    harness_source={"kind": "git", "commit": DIGEST_B},
                    asset_loader=lambda descriptor: b"different",
                )
            self.assertFalse(called)
            self.assertFalse((store.root / "records" / "run_manifest").exists())

    def test_l2_scope_and_portable_mapping_are_sealed_before_bounded_execution(self):
        host, runtime, model = self.foundation()
        input_bytes = b"hello"
        input_sha = sha(input_bytes)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "workspace"
            root.mkdir()
            (root / "input.txt").write_bytes(input_bytes)
            store = EvidenceStore(Path(temp_dir) / "evidence")

            def driver(request):
                manifest_dir = store.root / "records" / "run_manifest"
                self.assertEqual(len(list(manifest_dir.glob("*.json"))), 1)
                if request.turn == 1:
                    return ModelTurnResponse(
                        tool_calls=(ToolCall("read-1", "read_file", {"path": "input.txt"}),)
                    )
                if request.turn == 2:
                    return ModelTurnResponse(
                        tool_calls=(
                            ToolCall(
                                "write-1",
                                "write_file",
                                {"path": "out.txt", "content": "done", "expected_sha256": None},
                            ),
                        )
                    )
                return ModelTurnResponse(content="finished")

            result = run_v2_pack(
                run_id="run-l2",
                pack_source=pack_bytes(level="L2"),
                pack_source_locator=None,
                host=host,
                runtime=runtime,
                model=model,
                configuration_bindings={"profile-a": self.config(tools=True)},
                evaluator_registry=self.registry("tool_execution_trace"),
                driver_binding=DriverBinding("fake-tool-driver", DRIVER_DIGEST, driver),
                evidence_store=store,
                harness_source={"kind": "git", "commit": DIGEST_B},
                workspaces={
                    "case-a": WorkspaceBinding(
                        root=root,
                        readable_paths=("input.txt",),
                        writable_paths=("out.txt",),
                    )
                },
                clock=self.fixed_clock(),
            )

            self.assertEqual((root / "out.txt").read_text(encoding="utf-8"), "done")
            binding = result.execution_bindings[0]
            self.assertEqual(binding.payload["workspace_scope"]["readable_paths"], ("input.txt",))
            self.assertEqual(binding.payload["workspace_scope"]["writable_paths"], ("out.txt",))
            tool_binding = binding.payload["driver"]["tool_surface_binding"]
            self.assertEqual(
                tool_binding["required_capability"], PORTABLE_BOUNDED_FILES_CAPABILITY
            )
            self.assertEqual(tool_binding["concrete_surface"], BOUNDED_FILE_SURFACE_ID)
            self.assertEqual(
                tool_binding["concrete_schema_sha256"], BOUNDED_FILE_TOOL_SCHEMA_SHA256
            )
            trace = result.execution_evidence[0]
            self.assertEqual(trace.payload["initial_workspace"]["files"][0]["sha256"], input_sha)
            self.assertEqual(result.case_results[0].payload["status"], "success")
            self.assertEqual(result.evaluation_results[0].payload["verdict"], "pass")

    def test_subprocess_driver_preflight_blocks_before_manifest_and_driver(self):
        host, runtime, model = self.foundation()
        called = False

        def driver(request):
            nonlocal called
            called = True
            return ModelTurnResponse(content="should not run")

        policy = ContainmentPolicy(
            wall_seconds=10,
            max_attempts=1,
            network_policy="disabled",
            process_custody="best_effort",
            require_workspace_isolation=False,
            require_assessor_isolation=False,
            writable_paths=(),
            max_output_bytes=None,
            max_memory_bytes=None,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir) / "evidence")
            binding = DriverBinding(
                "subprocess-driver",
                DRIVER_DIGEST,
                driver,
                execution_kind="subprocess",
                containment_policy=policy,
                containment_backend=NativeSubprocessBackend(),
            )
            with self.assertRaises(ContainmentBlocked):
                run_v2_pack(
                    run_id="run-blocked",
                    pack_source=pack_bytes(level="L0"),
                    pack_source_locator=None,
                    host=host,
                    runtime=runtime,
                    model=model,
                    configuration_bindings={"profile-a": self.config(tools=False)},
                    evaluator_registry=self.registry("intrinsic_execution_trace"),
                    driver_binding=binding,
                    evidence_store=store,
                    harness_source={"kind": "git", "commit": DIGEST_B},
                )
            self.assertFalse(called)
            self.assertFalse((store.root / "records" / "run_manifest").exists())

    def test_successful_subprocess_preflight_seals_plan_but_direct_call_is_forbidden(self):
        host, runtime, model = self.foundation()
        called = False

        def driver(request):
            nonlocal called
            called = True
            return ModelTurnResponse(content="must not run")

        policy = ContainmentPolicy(
            wall_seconds=10,
            max_attempts=1,
            network_policy="provider_only",
            process_custody="strict",
            require_workspace_isolation=True,
            require_assessor_isolation=True,
            writable_paths=(),
            max_output_bytes=1024,
            max_memory_bytes=1024,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir) / "evidence")
            binding = DriverBinding(
                "subprocess-driver",
                DRIVER_DIGEST,
                driver,
                execution_kind="subprocess",
                containment_policy=policy,
                containment_backend=FakeStrictBackend(),
            )
            with self.assertRaisesRegex(OrchestrationBlocked, "direct-call fallback is forbidden"):
                run_v2_pack(
                    run_id="run-contained-plan",
                    pack_source=pack_bytes(level="L0"),
                    pack_source_locator=None,
                    host=host,
                    runtime=runtime,
                    model=model,
                    configuration_bindings={"profile-a": self.config(tools=False)},
                    evaluator_registry=self.registry("intrinsic_execution_trace"),
                    driver_binding=binding,
                    evidence_store=store,
                    harness_source={"kind": "git", "commit": DIGEST_B},
                )
            self.assertFalse(called)
            manifests = list((store.root / "records" / "run_manifest").glob("*.json"))
            bindings = list((store.root / "records" / "execution_binding").glob("*.json"))
            self.assertEqual(len(manifests), 1)
            self.assertEqual(len(bindings), 1)
            binding_payload = json.loads(bindings[0].read_text(encoding="utf-8"))["payload"]
            self.assertEqual(binding_payload["containment"]["policy_sha256"], policy.sha256)

    def test_configuration_contract_mismatch_fails_before_execution(self):
        host, runtime, model = self.foundation()
        called = False

        def driver(request):
            nonlocal called
            called = True
            return ModelTurnResponse(content="should not run")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir) / "evidence")
            with self.assertRaisesRegex(OrchestrationBlocked, "response contract"):
                run_v2_pack(
                    run_id="run-config-mismatch",
                    pack_source=pack_bytes(level="L0", response_mode="json_object"),
                    pack_source_locator=None,
                    host=host,
                    runtime=runtime,
                    model=model,
                    configuration_bindings={"profile-a": self.config(tools=False)},
                    evaluator_registry=self.registry("intrinsic_execution_trace"),
                    driver_binding=DriverBinding("fake-driver", DRIVER_DIGEST, driver),
                    evidence_store=store,
                    harness_source={"kind": "git", "commit": DIGEST_B},
                )
            self.assertFalse(called)

    def test_evidence_store_is_idempotent_but_never_rewrites_conflicting_bytes(self):
        host, _, _ = self.foundation()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir))
            path = store.persist(host)
            original = path.read_bytes()
            store.persist(host)
            self.assertEqual(path.read_bytes(), original)
            path.write_bytes(b"corrupt")
            with self.assertRaises(EvidenceStoreError):
                store.persist(host)


if __name__ == "__main__":
    unittest.main()
