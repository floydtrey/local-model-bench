from __future__ import annotations

import unittest

from localbench.v2.records import (
    benchmark_input,
    case_result,
    effective_runtime_config,
    evaluation_result,
    evaluator_identity,
    host_profile,
    model_identity,
    run_manifest,
    runtime_profile,
    trial_identity,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


class V2RecordContractTests(unittest.TestCase):
    def _host(self, captured_at: str = "2026-09-11T00:00:00Z"):
        return host_profile(
            "host-a",
            captured_at=captured_at,
            os_info={"name": "Windows 11", "build": None},
            cpu={"model": "test-cpu", "physical_cores": None, "logical_cores": 16},
            memory={"installed_bytes": None, "available_bytes": None},
            gpus=[{"name": "test-gpu", "vram_bytes": None, "driver": None}],
            storage=[{"volume": "C:", "available_bytes": None}],
            python={"version": "3.12", "implementation": "CPython"},
            compute_runtimes=[{"kind": "cuda", "version": None}],
            power_thermal=None,
        )

    def _chain(self):
        host = self._host()
        runtime = runtime_profile(
            "ollama-local",
            runtime_kind="ollama",
            version=None,
            build=None,
            transport={"kind": "loopback_http", "endpoint": "http://127.0.0.1:11434"},
            executable=None,
            installation_digest=None,
            capabilities={"chat": True, "tools": None},
        )
        model = model_identity(
            "candidate-a",
            family=None,
            name="candidate:tag",
            source={"kind": "provider_registry", "locator": "candidate:tag"},
            artifact_digest=None,
            provider_digest=DIGEST_A,
            parameter_count=None,
            quantization=None,
            precision=None,
            declared_context_tokens=None,
        )
        config = effective_runtime_config(
            "candidate-a-config",
            runtime=runtime.reference,
            model=model.reference,
            settings={"temperature": 0, "context_tokens": 32768},
            tool_surface={"id": "none", "tools": []},
            limits={"timeout_seconds": 600, "retries": 0},
        )
        benchmark = benchmark_input(
            "shared-core-v2",
            suite_id="shared-core-v2",
            source_sha256=DIGEST_B,
            level="L0",
            case_ids=["case-1"],
            source_format="json",
            source_locator="suites/v2/shared-core.json",
        )
        evaluator = evaluator_identity(
            "structured-v2",
            evaluator_id="structured-v2",
            version="1",
            implementation_sha256=DIGEST_C,
            result_contract="structured-response:v2",
            requires_human_review=False,
        )
        trial = trial_identity(
            "shared-core-v2-case-1-trial-1",
            layer="intrinsic",
            ordinal=1,
            repeat_group="case-1",
            benchmark=benchmark.reference,
        )
        manifest = run_manifest(
            "run-a",
            host=host.reference,
            runtime=runtime.reference,
            model=model.reference,
            effective_config=config.reference,
            benchmarks=[benchmark.reference],
            evaluators=[evaluator.reference],
            trials=[trial.reference],
            harness_source={"kind": "git", "commit": DIGEST_A},
        )
        return host, runtime, model, config, benchmark, evaluator, trial, manifest

    def test_complete_identity_chain_is_sealed(self):
        host, runtime, model, config, benchmark, evaluator, trial, manifest = self._chain()

        self.assertEqual(host.record_type, "host_profile")
        self.assertEqual(runtime.record_type, "runtime_profile")
        self.assertEqual(model.record_type, "model_identity")
        self.assertEqual(config.payload["runtime"]["sha256"], runtime.sha256)
        self.assertEqual(config.payload["model"]["sha256"], model.sha256)
        self.assertEqual(manifest.payload["host"]["sha256"], host.sha256)
        self.assertEqual(manifest.payload["benchmarks"][0]["sha256"], benchmark.sha256)
        self.assertEqual(manifest.payload["evaluators"][0]["sha256"], evaluator.sha256)
        self.assertEqual(manifest.payload["trials"][0]["sha256"], trial.sha256)
        self.assertNotIn("status", manifest.payload)

    def test_unknown_measurements_remain_explicit_null(self):
        host, runtime, model, *_ = self._chain()

        self.assertIsNone(host.payload["memory"]["installed_bytes"])
        self.assertIsNone(runtime.payload["version"])
        self.assertIsNone(model.payload["artifact_digest"])
        self.assertIsNone(model.payload["declared_context_tokens"])

    def test_host_facts_fingerprint_ignores_collection_time(self):
        first = self._host("2026-09-11T00:00:00Z")
        second = self._host("2026-09-11T01:00:00Z")

        self.assertEqual(first.payload["facts_sha256"], second.payload["facts_sha256"])
        self.assertNotEqual(first.sha256, second.sha256)

    def test_reference_types_fail_closed(self):
        host, runtime, model, _, benchmark, evaluator, trial, _ = self._chain()

        with self.assertRaisesRegex(ValueError, "runtime_profile"):
            effective_runtime_config(
                "bad-config",
                runtime=model.reference,
                model=model.reference,
                settings={},
                tool_surface={},
                limits={},
            )

        with self.assertRaisesRegex(ValueError, "host_profile"):
            run_manifest(
                "bad-run",
                host=runtime.reference,
                runtime=runtime.reference,
                model=model.reference,
                effective_config=effective_runtime_config(
                    "good-config",
                    runtime=runtime.reference,
                    model=model.reference,
                    settings={},
                    tool_surface={},
                    limits={},
                ).reference,
                benchmarks=[benchmark.reference],
                evaluators=[evaluator.reference],
                trials=[trial.reference],
                harness_source={},
            )

    def test_case_and_evaluation_results_bind_to_manifest_and_evaluator(self):
        _, _, _, _, benchmark, evaluator, trial, manifest = self._chain()
        case = case_result(
            "run-a-case-1-trial-1",
            manifest=manifest.reference,
            benchmark=benchmark.reference,
            trial=trial.reference,
            case_id="case-1",
            status="success",
            started_at="2026-09-11T00:01:00Z",
            finished_at="2026-09-11T00:01:03Z",
            metrics={"wall_seconds": 3.0, "output_tokens": 12},
            execution_evidence={"response_sha256": DIGEST_A},
            terminal_output={"kind": "assistant_text", "sha256": DIGEST_B},
        )
        evaluation = evaluation_result(
            "run-a-case-1-trial-1-eval",
            case=case.reference,
            evaluator=evaluator.reference,
            verdict="pass",
            score=95,
            maximum_score=100,
            hard_failures=[],
            checks=[{"id": "schema", "passed": True, "points": 20}],
        )

        self.assertEqual(case.payload["manifest"]["sha256"], manifest.sha256)
        self.assertEqual(evaluation.payload["case"]["sha256"], case.sha256)
        self.assertEqual(evaluation.payload["evaluator"]["sha256"], evaluator.sha256)
        self.assertEqual(evaluation.payload["hard_failures"], ())

    def test_scoring_contract_rejects_incoherent_scores(self):
        _, _, _, _, benchmark, evaluator, trial, manifest = self._chain()
        case = case_result(
            "case",
            manifest=manifest.reference,
            benchmark=benchmark.reference,
            trial=trial.reference,
            case_id="case-1",
            status="success",
            started_at="start",
            finished_at="finish",
            metrics={},
            execution_evidence={},
            terminal_output=None,
        )

        with self.assertRaisesRegex(ValueError, "both be present"):
            evaluation_result(
                "bad-eval",
                case=case.reference,
                evaluator=evaluator.reference,
                verdict="pass",
                score=10,
                maximum_score=None,
                hard_failures=[],
                checks=[],
            )
        with self.assertRaisesRegex(ValueError, "exceed"):
            evaluation_result(
                "bad-eval-2",
                case=case.reference,
                evaluator=evaluator.reference,
                verdict="pass",
                score=101,
                maximum_score=100,
                hard_failures=[],
                checks=[],
            )

    def test_benchmark_level_and_trial_layer_are_versioned_categories(self):
        with self.assertRaisesRegex(ValueError, "L0"):
            benchmark_input(
                "bad-level",
                suite_id="suite",
                source_sha256=DIGEST_A,
                level="prompt",
                case_ids=["case"],
                source_format="json",
                source_locator=None,
            )

        benchmark = benchmark_input(
            "suite",
            suite_id="suite",
            source_sha256=DIGEST_A,
            level="L0",
            case_ids=["case"],
            source_format="json",
            source_locator=None,
        )
        with self.assertRaisesRegex(ValueError, "layer"):
            trial_identity(
                "bad-layer",
                layer="mystery",
                ordinal=1,
                repeat_group=None,
                benchmark=benchmark.reference,
            )


if __name__ == "__main__":
    unittest.main()
