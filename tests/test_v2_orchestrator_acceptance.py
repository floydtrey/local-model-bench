from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from localbench.v2 import (
    CONFIG_SPEC_VERSION,
    ConfigurationBinding,
    DriverBinding,
    EvidenceConsumption,
    EvidenceStore,
    EvaluatorDefinition,
    EvaluatorRegistry,
    ModelTurnResponse,
    OrchestrationBlocked,
    host_profile,
    model_identity,
    run_v2_pack,
    runtime_profile,
)


DRIVER_DIGEST = "d" * 64
EVALUATOR_DIGEST = "e" * 64
MODEL_DIGEST = "a" * 64
HARNESS_COMMIT = "b" * 64


def _pack(level: str) -> bytes:
    value = {
        "schema_version": "benchmark-lab-pack:v2",
        "pack_id": f"acceptance-{level.lower()}",
        "pack_version": "1.0.0",
        "name": "BL-8A acceptance fixture",
        "description": "Synthetic engineering fixture only.",
        "level": level,
        "cases": [
            {
                "case_id": "case-a",
                "objective": "Exercise an orchestration acceptance invariant.",
                "input": {
                    "messages": [{"role": "user", "content": "synthetic input"}],
                    "context_assets": [],
                },
                "requirements": {
                    "configuration_profile": "profile-a",
                    "response_contract": {"mode": "text", "schema": None},
                    "tool_surface": {"id": "none", "required_tools": []},
                    "minimum_context_tokens": 1024,
                },
                "evaluators": [
                    {"evaluator_id": "failing-evaluator", "contract_version": "1.0.0"}
                ],
                "hard_failure_rules": [],
                "repetitions": {"screen_trials": 1, "qualification_trials": 1},
                "tags": ["engineering"],
            }
        ],
    }
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _foundation():
    host = host_profile(
        "host-acceptance",
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
        "runtime-acceptance",
        runtime_kind="fake",
        version="1",
        build=None,
        transport={"kind": "injected"},
        executable=None,
        installation_digest=None,
        capabilities={"chat": True, "tools": False},
    )
    model = model_identity(
        "model-acceptance",
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


def _configuration() -> ConfigurationBinding:
    return ConfigurationBinding(
        "profile-a",
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
                "id": "none",
                "tools": [],
                "max_tool_calls": 0,
                "schema_sha256": None,
            },
        },
        adapter_resolution={
            "adapter_id": "fake-adapter:v1",
            "status": "exact",
            "effective_request": {"synthetic": True},
            "deviations": [],
        },
    )


def _failing_registry() -> EvaluatorRegistry:
    registry = EvaluatorRegistry()
    definition = EvaluatorDefinition(
        evaluator_id="failing-evaluator",
        contract_version="1.0.0",
        implementation_sha256=EVALUATOR_DIGEST,
        input_contract="synthetic-input:v1",
        result_contract="synthetic-result:v1",
        consumed_evidence=(
            EvidenceConsumption("case_result"),
            EvidenceConsumption("intrinsic_execution_trace"),
        ),
        requires_human_review=False,
        scoring_mode="weighted",
    )

    def implementation(context):
        raise RuntimeError("synthetic evaluator failure")

    registry.register(definition, implementation)
    return registry


def _clock():
    values = iter(("2026-09-11T00:00:01Z", "2026-09-11T00:00:02Z"))
    return lambda: next(values)


class BL8AAcceptanceInvariantTests(unittest.TestCase):
    def test_evaluator_failure_preserves_raw_execution_and_case_evidence(self):
        host, runtime, model = _foundation()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = EvidenceStore(Path(temp_dir) / "evidence")
            with self.assertRaisesRegex(RuntimeError, "synthetic evaluator failure"):
                run_v2_pack(
                    run_id="run-evaluator-failure",
                    pack_source=_pack("L0"),
                    pack_source_locator=None,
                    host=host,
                    runtime=runtime,
                    model=model,
                    configuration_bindings={"profile-a": _configuration()},
                    evaluator_registry=_failing_registry(),
                    driver_binding=DriverBinding(
                        "fake-driver",
                        DRIVER_DIGEST,
                        lambda request: ModelTurnResponse(content="raw evidence survives"),
                    ),
                    evidence_store=store,
                    harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                    clock=_clock(),
                )

            self.assertEqual(
                len(list((store.root / "records" / "intrinsic_execution_trace").glob("*.json"))),
                1,
            )
            self.assertEqual(
                len(list((store.root / "records" / "case_result").glob("*.json"))),
                1,
            )
            evaluation_dir = store.root / "records" / "evaluation_result"
            self.assertFalse(evaluation_dir.exists())

    def test_l3_and_l4_fail_closed_before_driver_execution(self):
        host, runtime, model = _foundation()
        for level in ("L3", "L4"):
            called = False

            def driver(request):
                nonlocal called
                called = True
                return ModelTurnResponse(content="must not run")

            with self.subTest(level=level), tempfile.TemporaryDirectory() as temp_dir:
                store = EvidenceStore(Path(temp_dir) / "evidence")
                with self.assertRaisesRegex(OrchestrationBlocked, "supports only"):
                    run_v2_pack(
                        run_id=f"run-{level.lower()}-blocked",
                        pack_source=_pack(level),
                        pack_source_locator=None,
                        host=host,
                        runtime=runtime,
                        model=model,
                        configuration_bindings={"profile-a": _configuration()},
                        evaluator_registry=_failing_registry(),
                        driver_binding=DriverBinding(
                            "fake-driver", DRIVER_DIGEST, driver
                        ),
                        evidence_store=store,
                        harness_source={"kind": "git", "commit": HARNESS_COMMIT},
                    )
                self.assertFalse(called)
                self.assertFalse((store.root / "records" / "run_manifest").exists())


if __name__ == "__main__":
    unittest.main()
