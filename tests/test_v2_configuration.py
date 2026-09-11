from __future__ import annotations

import unittest

from localbench.v2.configuration import (
    CONFIG_SPEC_VERSION,
    resolve_effective_configuration,
)
from localbench.v2.records import model_identity, runtime_profile


DIGEST = "a" * 64
TOOL_DIGEST = "b" * 64


class ConfigurationTests(unittest.TestCase):
    def _runtime(self):
        return runtime_profile(
            "ollama-local",
            runtime_kind="ollama",
            version="test",
            build=None,
            transport={"kind": "loopback_http", "endpoint": "http://127.0.0.1:11434"},
            executable=None,
            installation_digest=None,
            capabilities={"chat": True, "tools": True},
        )

    def _model(self, *, context: int | None = 32768):
        return model_identity(
            "candidate",
            family="test",
            name="candidate:tag",
            source={"kind": "provider_registry", "locator": "candidate:tag"},
            artifact_digest=None,
            provider_digest=DIGEST,
            parameter_count=None,
            quantization=None,
            precision=None,
            declared_context_tokens=context,
        )

    def _spec(self, *, mode: str = "strict", context: int = 8192, tools=False):
        return {
            "schema_version": CONFIG_SPEC_VERSION,
            "comparison_mode": mode,
            "generation": {
                "context_tokens": context,
                "max_output_tokens": 2048,
                "response_format": {"mode": "text", "schema": None},
            },
            "execution": {
                "timeout_seconds": 600,
                "model_residency": {
                    "mode": "unload_after_model",
                    "keep_alive_seconds": 0,
                },
                "network_policy": "provider_only",
            },
            "tool_surface": {
                "id": "bounded-files" if tools else "none",
                "tools": ["read_file", "write_file"] if tools else [],
                "max_tool_calls": 12 if tools else 0,
                "schema_sha256": TOOL_DIGEST if tools else None,
            },
        }

    def _adapter(self, *, status: str = "exact", deviations=None):
        return {
            "adapter_id": "fake-adapter:v1",
            "status": status,
            "effective_request": {
                "num_ctx": 8192,
                "num_predict": 2048,
                "temperature": 0.0,
                "seed": 42,
            },
            "deviations": list(deviations or []),
        }

    def test_defaults_are_materialized_before_sealing(self):
        config = resolve_effective_configuration(
            "config-a",
            runtime=self._runtime(),
            model=self._model(),
            spec=self._spec(),
            adapter_resolution=self._adapter(),
        )

        generation = config.payload["settings"]["generation"]
        limits = config.payload["limits"]
        defaults = config.payload["settings"]["applied_defaults"]
        self.assertEqual(generation["temperature"], 0.0)
        self.assertEqual(generation["seed"], 42)
        self.assertEqual(generation["top_p"], 1.0)
        self.assertEqual(generation["stop"], ())
        self.assertEqual(limits["retries"], 0)
        self.assertEqual(limits["concurrency"], 1)
        self.assertIn("generation.temperature", defaults)
        self.assertIn("execution.retries", defaults)

    def test_behavior_change_changes_config_digest(self):
        first = resolve_effective_configuration(
            "config-a",
            runtime=self._runtime(),
            model=self._model(),
            spec=self._spec(),
            adapter_resolution=self._adapter(),
        )
        changed_spec = self._spec()
        changed_spec["generation"]["temperature"] = 0.2
        changed_adapter = self._adapter()
        changed_adapter["effective_request"]["temperature"] = 0.2
        second = resolve_effective_configuration(
            "config-a",
            runtime=self._runtime(),
            model=self._model(),
            spec=changed_spec,
            adapter_resolution=changed_adapter,
        )

        self.assertNotEqual(first.sha256, second.sha256)

    def test_strict_mode_rejects_degraded_adapter_resolution(self):
        with self.assertRaisesRegex(ValueError, "strict comparison"):
            resolve_effective_configuration(
                "config",
                runtime=self._runtime(),
                model=self._model(),
                spec=self._spec(),
                adapter_resolution=self._adapter(
                    status="degraded", deviations=["seed unsupported"]
                ),
            )

    def test_strict_mode_rejects_context_above_declared_limit(self):
        with self.assertRaisesRegex(ValueError, "exceeds model-declared context"):
            resolve_effective_configuration(
                "config",
                runtime=self._runtime(),
                model=self._model(context=4096),
                spec=self._spec(context=8192),
                adapter_resolution=self._adapter(),
            )

    def test_exploratory_mode_records_context_deviation(self):
        config = resolve_effective_configuration(
            "config",
            runtime=self._runtime(),
            model=self._model(context=4096),
            spec=self._spec(mode="exploratory", context=8192),
            adapter_resolution=self._adapter(),
        )

        deviations = config.payload["settings"]["adapter_resolution"]["deviations"]
        self.assertTrue(any("exceeds model-declared context" in item for item in deviations))

    def test_required_behavior_settings_cannot_fall_back_to_provider_defaults(self):
        spec = self._spec()
        del spec["generation"]["context_tokens"]
        with self.assertRaisesRegex(ValueError, "context_tokens must be explicit"):
            resolve_effective_configuration(
                "config",
                runtime=self._runtime(),
                model=self._model(),
                spec=spec,
                adapter_resolution=self._adapter(),
            )

        spec = self._spec()
        del spec["execution"]["timeout_seconds"]
        with self.assertRaisesRegex(ValueError, "timeout_seconds must be explicit"):
            resolve_effective_configuration(
                "config",
                runtime=self._runtime(),
                model=self._model(),
                spec=spec,
                adapter_resolution=self._adapter(),
            )

    def test_strict_tool_surface_requires_exact_schema_digest(self):
        spec = self._spec(tools=True)
        spec["tool_surface"]["schema_sha256"] = None
        with self.assertRaisesRegex(ValueError, "schema_sha256"):
            resolve_effective_configuration(
                "config",
                runtime=self._runtime(),
                model=self._model(),
                spec=spec,
                adapter_resolution=self._adapter(),
            )

    def test_unknown_fields_fail_closed(self):
        spec = self._spec()
        spec["generation"]["mystery_knob"] = 99
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            resolve_effective_configuration(
                "config",
                runtime=self._runtime(),
                model=self._model(),
                spec=spec,
                adapter_resolution=self._adapter(),
            )


if __name__ == "__main__":
    unittest.main()
