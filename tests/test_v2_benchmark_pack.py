from __future__ import annotations

import json
import unittest

from localbench.v2.benchmark_pack import PACK_SCHEMA_VERSION, parse_benchmark_pack


ASSET_DIGEST = "a" * 64


def pack_value(*, level: str = "L0", locator: str = "fixtures/context.txt") -> dict:
    assets = []
    if level != "L0":
        assets = [
            {
                "asset_id": "context-a",
                "sha256": ASSET_DIGEST,
                "media_type": "text/plain",
                "delivery": "inline_context",
                "source_locator": locator,
            }
        ]
    tool_surface = {"id": "none", "required_tools": []}
    if level in {"L2", "L3", "L4"}:
        tool_surface = {
            "id": "bounded-files-v1",
            "required_tools": ["read_file", "write_file"],
        }
    return {
        "schema_version": PACK_SCHEMA_VERSION,
        "pack_id": "synthetic-core",
        "pack_version": "1.0.0",
        "name": "Synthetic Contract Fixture",
        "description": "Engineering-only fixture for Benchmark Pack validation.",
        "level": level,
        "cases": [
            {
                "case_id": "case-a",
                "objective": "Exercise the portable case contract.",
                "input": {
                    "messages": [{"role": "user", "content": "synthetic input"}],
                    "context_assets": assets,
                },
                "requirements": {
                    "configuration_profile": "shared-default-v1",
                    "response_contract": {"mode": "text", "schema": None},
                    "tool_surface": tool_surface,
                    "minimum_context_tokens": None,
                },
                "evaluators": [
                    {
                        "evaluator_id": "synthetic-evaluator",
                        "contract_version": "1.0.0",
                    }
                ],
                "hard_failure_rules": [
                    {
                        "evaluator_id": "synthetic-evaluator",
                        "rule_id": "protocol-violation",
                    }
                ],
                "repetitions": {"screen_trials": 1, "qualification_trials": 3},
                "tags": ["synthetic"],
            }
        ],
    }


def encode(value: dict, *, pretty: bool = False) -> bytes:
    if pretty:
        return (json.dumps(value, indent=2) + "\n").encode("utf-8")
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


class BenchmarkPackContractTests(unittest.TestCase):
    def test_valid_pack_is_frozen_and_content_addressed(self):
        pack = parse_benchmark_pack(encode(pack_value()))

        self.assertEqual(pack.pack_id, "synthetic-core")
        self.assertEqual(pack.pack_version, "1.0.0")
        self.assertEqual(pack.level, "L0")
        self.assertEqual(pack.case_ids, ("case-a",))
        self.assertEqual(len(pack.source_sha256), 64)
        self.assertEqual(len(pack.semantic_sha256), 64)
        with self.assertRaises(TypeError):
            pack.case("case-a")["objective"] = "mutated"

    def test_source_bytes_and_semantic_identity_are_distinct(self):
        first_value = pack_value(level="L1", locator="fixtures/context.txt")
        second_value = pack_value(level="L1", locator="D:/private/context.txt")
        second_value["name"] = "Renamed reporting label"
        second_value["description"] = "Different non-behavioral description."
        second_value["cases"][0]["tags"] = ["different-report-tag"]

        first = parse_benchmark_pack(encode(first_value, pretty=False))
        second = parse_benchmark_pack(encode(second_value, pretty=True))

        self.assertNotEqual(first.source_sha256, second.source_sha256)
        self.assertEqual(first.semantic_sha256, second.semantic_sha256)

    def test_behavior_change_changes_semantic_identity(self):
        first_value = pack_value()
        second_value = pack_value()
        second_value["cases"][0]["input"]["messages"][0]["content"] = "changed input"

        first = parse_benchmark_pack(encode(first_value))
        second = parse_benchmark_pack(encode(second_value))

        self.assertNotEqual(first.semantic_sha256, second.semantic_sha256)

    def test_l0_rejects_external_context_assets(self):
        value = pack_value()
        value["cases"][0]["input"]["context_assets"] = [
            {
                "asset_id": "context-a",
                "sha256": ASSET_DIGEST,
                "media_type": "text/plain",
                "delivery": "inline_context",
                "source_locator": "fixtures/context.txt",
            }
        ]
        with self.assertRaisesRegex(ValueError, "L0 cases cannot declare context assets"):
            parse_benchmark_pack(encode(value))

    def test_l0_and_l1_reject_tool_surface(self):
        for level in ("L0", "L1"):
            with self.subTest(level=level):
                value = pack_value(level=level)
                value["cases"][0]["requirements"]["tool_surface"] = {
                    "id": "bounded-files-v1",
                    "required_tools": ["read_file"],
                }
                with self.assertRaisesRegex(ValueError, "cannot require a tool surface"):
                    parse_benchmark_pack(encode(value))

    def test_l2_allows_declared_bounded_tool_requirement(self):
        pack = parse_benchmark_pack(encode(pack_value(level="L2")))
        tool_surface = pack.case("case-a")["requirements"]["tool_surface"]
        self.assertEqual(tool_surface["id"], "bounded-files-v1")
        self.assertEqual(tool_surface["required_tools"], ("read_file", "write_file"))

    def test_hard_failure_rule_must_reference_declared_evaluator(self):
        value = pack_value()
        value["cases"][0]["hard_failure_rules"][0]["evaluator_id"] = "missing-evaluator"
        with self.assertRaisesRegex(ValueError, "undeclared evaluators"):
            parse_benchmark_pack(encode(value))

    def test_repetition_policy_is_explicit_and_monotonic(self):
        value = pack_value()
        value["cases"][0]["repetitions"] = {
            "screen_trials": 3,
            "qualification_trials": 2,
        }
        with self.assertRaisesRegex(ValueError, "qualification_trials must be >="):
            parse_benchmark_pack(encode(value))

    def test_unknown_case_fields_fail_closed(self):
        value = pack_value()
        value["cases"][0]["provider_options"] = {"temperature": 0}
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            parse_benchmark_pack(encode(value))

    def test_pack_can_become_existing_benchmark_input_evidence_without_leaking_path(self):
        pack = parse_benchmark_pack(encode(pack_value()))
        evidence = pack.to_benchmark_input()

        self.assertEqual(evidence.record_type, "benchmark_input")
        self.assertEqual(evidence.logical_id, "synthetic-core")
        self.assertEqual(evidence.payload["suite_id"], "synthetic-core@1.0.0")
        self.assertEqual(evidence.payload["source_sha256"], pack.source_sha256)
        self.assertEqual(evidence.payload["case_ids"], ("case-a",))
        self.assertIsNone(evidence.payload["source_locator"])

    def test_asset_locator_is_not_fixture_identity_but_digest_is_required(self):
        value = pack_value(level="L1")
        value["cases"][0]["input"]["context_assets"][0]["sha256"] = "not-a-digest"
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            parse_benchmark_pack(encode(value))


if __name__ == "__main__":
    unittest.main()
