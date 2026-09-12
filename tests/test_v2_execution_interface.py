from __future__ import annotations

import unittest

from localbench.v2.execution_interface import (
    BACKEND_TOOL_EXECUTION_POLICIES,
    EXECUTION_INTERFACE_VERSION,
    MALFORMED_CALL_POLICIES,
    NORMALIZED_TOOL_CALL_CONTRACT,
    PARSER_MODES,
    TOOL_TRANSPORT_MODES,
    execution_interface_identity,
)
from localbench.v2.records import model_identity, runtime_profile


DIGEST_A = "a" * 64


class ExecutionInterfaceIdentityTests(unittest.TestCase):
    def _runtime(self):
        return runtime_profile(
            "ollama-local",
            runtime_kind="ollama",
            version="0.34.0",
            build=None,
            transport={"kind": "loopback_http", "base_uri": "http://127.0.0.1:11434"},
            executable=None,
            installation_digest=None,
            capabilities={"chat": True, "tools": True},
        )

    def _model(self):
        return model_identity(
            "qwen25-coder-7b",
            family="qwen2.5-coder",
            name="qwen2.5-coder:7b",
            source={"kind": "provider_registry", "locator": "qwen2.5-coder:7b"},
            artifact_digest=None,
            provider_digest=DIGEST_A,
            parameter_count=None,
            quantization=None,
            precision=None,
            declared_context_tokens=None,
        )

    def test_native_execution_interface_is_sealed_separately_from_model(self):
        runtime = self._runtime()
        model = self._model()
        interface = execution_interface_identity(
            "qwen25-ollama-native",
            runtime=runtime.reference,
            model=model.reference,
            backend_kind="ollama",
            adapter_id="benchmark-lab-ollama-chat:v1",
            tool_transport_mode="native_structured",
            parser_mode="provider_native",
            parser_id="ollama-native-tools:v1",
            raw_interaction_contract="ollama-api-chat-response:v1",
            capabilities={"multi_turn_tools": True, "parallel_tool_calls": None},
        )

        self.assertEqual(interface.record_type, "execution_interface_identity")
        self.assertEqual(interface.payload["interface_version"], EXECUTION_INTERFACE_VERSION)
        self.assertEqual(interface.payload["runtime"]["sha256"], runtime.sha256)
        self.assertEqual(interface.payload["model"]["sha256"], model.sha256)
        self.assertEqual(
            interface.payload["normalized_tool_call_contract"], NORMALIZED_TOOL_CALL_CONTRACT
        )
        self.assertEqual(interface.payload["malformed_call_policy"], "fail_closed")
        self.assertEqual(interface.payload["backend_tool_execution"], "forbidden")

    def test_model_aware_parser_is_a_distinct_interface(self):
        runtime = self._runtime()
        model = self._model()
        native = execution_interface_identity(
            "qwen25-native",
            runtime=runtime.reference,
            model=model.reference,
            backend_kind="ollama",
            adapter_id="adapter-a",
            tool_transport_mode="native_structured",
            parser_mode="provider_native",
            parser_id="native-parser",
            raw_interaction_contract="raw:v1",
            capabilities={},
        )
        aware = execution_interface_identity(
            "qwen25-aware",
            runtime=runtime.reference,
            model=model.reference,
            backend_kind="ollama",
            adapter_id="adapter-a",
            tool_transport_mode="model_aware_structured",
            parser_mode="model_aware",
            parser_id="qwen25-parser",
            raw_interaction_contract="raw:v1",
            capabilities={},
        )

        self.assertNotEqual(native.sha256, aware.sha256)
        self.assertEqual(native.payload["model"]["sha256"], aware.payload["model"]["sha256"])

    def test_prompt_based_mode_must_be_explicit(self):
        runtime = self._runtime()
        model = self._model()
        interface = execution_interface_identity(
            "qwen25-prompt-parser",
            runtime=runtime.reference,
            model=model.reference,
            backend_kind="compatibility-adapter",
            adapter_id="prompt-tools:v1",
            tool_transport_mode="prompt_parsed",
            parser_mode="prompt_based",
            parser_id="qwen-agent-style-parser:v1",
            raw_interaction_contract="assistant-content:v1",
            capabilities={"prompt_injected_tools": True},
        )
        self.assertEqual(interface.payload["parser_mode"], "prompt_based")

        with self.assertRaisesRegex(ValueError, "prompt_based"):
            execution_interface_identity(
                "bad-prompt-parser",
                runtime=runtime.reference,
                model=model.reference,
                backend_kind="compatibility-adapter",
                adapter_id="prompt-tools:v1",
                tool_transport_mode="native_structured",
                parser_mode="prompt_based",
                parser_id="parser",
                raw_interaction_contract="assistant-content:v1",
                capabilities={},
            )

    def test_unavailable_transport_requires_no_parser(self):
        runtime = self._runtime()
        model = self._model()
        interface = execution_interface_identity(
            "qwen25-no-tools",
            runtime=runtime.reference,
            model=model.reference,
            backend_kind="runtime-without-tools",
            adapter_id="text-only:v1",
            tool_transport_mode="unavailable",
            parser_mode="none",
            parser_id=None,
            raw_interaction_contract="assistant-content:v1",
            capabilities={"tools": False},
        )
        self.assertIsNone(interface.payload["parser_id"])

        with self.assertRaisesRegex(ValueError, "parser_id must be null"):
            execution_interface_identity(
                "bad-none-parser",
                runtime=runtime.reference,
                model=model.reference,
                backend_kind="runtime-without-tools",
                adapter_id="text-only:v1",
                tool_transport_mode="unavailable",
                parser_mode="none",
                parser_id="should-not-exist",
                raw_interaction_contract="assistant-content:v1",
                capabilities={},
            )

    def test_authority_policies_fail_closed(self):
        runtime = self._runtime()
        model = self._model()

        with self.assertRaisesRegex(ValueError, "fail_closed"):
            execution_interface_identity(
                "bad-malformed-policy",
                runtime=runtime.reference,
                model=model.reference,
                backend_kind="ollama",
                adapter_id="adapter",
                tool_transport_mode="native_structured",
                parser_mode="provider_native",
                parser_id="native",
                raw_interaction_contract="raw:v1",
                capabilities={},
                malformed_call_policy="best_effort",
            )

        with self.assertRaisesRegex(ValueError, "forbidden"):
            execution_interface_identity(
                "bad-execution-policy",
                runtime=runtime.reference,
                model=model.reference,
                backend_kind="ollama",
                adapter_id="adapter",
                tool_transport_mode="native_structured",
                parser_mode="provider_native",
                parser_id="native",
                raw_interaction_contract="raw:v1",
                capabilities={},
                backend_tool_execution="allowed",
            )

    def test_public_mode_sets_are_intentionally_narrow(self):
        self.assertEqual(MALFORMED_CALL_POLICIES, frozenset({"fail_closed"}))
        self.assertEqual(BACKEND_TOOL_EXECUTION_POLICIES, frozenset({"forbidden"}))
        self.assertIn("model_aware_structured", TOOL_TRANSPORT_MODES)
        self.assertIn("model_aware", PARSER_MODES)


if __name__ == "__main__":
    unittest.main()
