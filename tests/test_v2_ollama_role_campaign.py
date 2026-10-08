from __future__ import annotations

import unittest

from localbench.v2.ollama_role_campaign import (
    _parameter_count,
    generation_spec,
)


class OllamaRoleCampaignTests(unittest.TestCase):
    def test_parameter_count_parsing(self):
        self.assertEqual(_parameter_count("12.2B"), 12_200_000_000)
        self.assertEqual(_parameter_count("270M"), 270_000_000)
        self.assertIsNone(_parameter_count("unknown"))

    def test_non_thinking_models_use_explicit_unsupported_reasoning(self):
        spec = generation_spec(
            context_tokens=32768,
            max_output_tokens=8192,
            timeout_seconds=600,
            reasoning_transport="unsupported",
            keep_alive_seconds=3600,
        )
        self.assertEqual(
            spec["generation"]["reasoning"],
            {"mode": "unsupported", "effort": None},
        )
        self.assertEqual(spec["execution"]["model_residency"]["mode"], "keep_loaded")
        self.assertEqual(spec["execution"]["timeout_seconds"], 600)

    def test_thinking_models_use_boolean_reasoning_contract(self):
        spec = generation_spec(
            context_tokens=32768,
            max_output_tokens=8192,
            timeout_seconds=600,
            reasoning_transport="boolean",
            keep_alive_seconds=3600,
        )
        self.assertEqual(
            spec["generation"]["reasoning"],
            {"mode": "enabled", "effort": None},
        )


if __name__ == "__main__":
    unittest.main()
