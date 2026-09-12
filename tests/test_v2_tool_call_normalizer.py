from __future__ import annotations

import unittest

from localbench.v2.tool_call_normalizer import (
    PROFILES,
    ModelTransportRegistry,
    NormalizeStatus,
    ToolCallNormalizer,
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read one file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    }
]


class ToolCallNormalizerTests(unittest.TestCase):
    def normalize(self, profile: str, *, content=None, message=None, tools=TOOLS):
        return ToolCallNormalizer().normalize(
            profile=PROFILES[profile],
            offered_tools=tools,
            content=content,
            message=message,
        )

    def test_native_fast_path_accepts_json_string_arguments(self):
        result = self.normalize(
            "openai_native",
            message={
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"facts.txt"}',
                        },
                    }
                ],
            },
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.calls[0].arguments, {"path": "facts.txt"})
        self.assertEqual(result.calls[0].call_id, "call-1")

    def test_qwen_compat_accepts_each_explicit_text_format(self):
        body = '{"name":"read_file","arguments":{"path":"facts.txt"}}'
        samples = {
            "tool_call_xml": f"<tool_call>{body}</tool_call>",
            "function_call_xml": f"<function_call>{body}</function_call>",
            "tools_xml": f"<tools>{body}</tools>",
            "fenced_json": f"```json\n{body}\n```",
            "plain_json": body,
        }
        for expected, content in samples.items():
            with self.subTest(expected):
                result = self.normalize("qwen_25_compat", content=content)
                self.assertTrue(result.ok, result.errors)
                self.assertEqual(result.source_format, expected)

    def test_normal_prose_and_prose_wrapped_json_are_not_calls(self):
        normal = self.normalize("qwen_25_compat", content="The file is unavailable.")
        wrapped = self.normalize(
            "qwen_25_compat",
            content=(
                "I will call it now.\n```json\n"
                '{"name":"read_file","arguments":{"path":"facts.txt"}}\n```'
            ),
        )
        self.assertIs(normal.status, NormalizeStatus.NOT_TOOL_CALL)
        self.assertIs(wrapped.status, NormalizeStatus.NOT_TOOL_CALL)

    def test_profile_does_not_accept_unlisted_format(self):
        result = self.normalize(
            "qwen_canonical",
            content=(
                "```json\n"
                '{"name":"read_file","arguments":{"path":"facts.txt"}}\n```'
            ),
        )
        self.assertIs(result.status, NormalizeStatus.NOT_TOOL_CALL)

    def test_unknown_tool_and_schema_mismatch_fail_closed(self):
        unknown = self.normalize(
            "qwen_25_compat",
            content='{"name":"delete_everything","arguments":{}}',
        )
        wrong_type = self.normalize(
            "qwen_25_compat",
            content='{"name":"read_file","arguments":{"path":42}}',
        )
        self.assertIs(unknown.status, NormalizeStatus.INVALID_TOOL_CALL)
        self.assertIs(wrong_type.status, NormalizeStatus.INVALID_TOOL_CALL)

    def test_malformed_plain_json_is_invalid_not_terminal_text(self):
        for content in (
            '{"name":"read_file","arguments":',
            '[{"name":"read_file","arguments":',
        ):
            with self.subTest(content):
                result = self.normalize("qwen_25_compat", content=content)
                self.assertIs(result.status, NormalizeStatus.INVALID_TOOL_CALL)
                self.assertEqual(result.source_format, "plain_json")

    def test_call_shaped_object_and_array_fail_when_no_tools_were_offered(self):
        samples = (
            '{"name":"read_file","arguments":{"path":"facts.txt"}}',
            '[{"name":"read_file","arguments":{"path":"facts.txt"}}]',
        )
        for content in samples:
            with self.subTest(content):
                result = self.normalize("qwen_25_compat", content=content, tools=[])
                self.assertIs(result.status, NormalizeStatus.INVALID_TOOL_CALL)

    def test_disagreeing_message_and_content_fail_closed(self):
        result = self.normalize(
            "qwen_25_compat",
            message={"content": "ordinary response"},
            content='{"name":"read_file","arguments":{"path":"facts.txt"}}',
        )
        self.assertIs(result.status, NormalizeStatus.INVALID_TOOL_CALL)
        self.assertIn("disagrees", result.errors[0])

    def test_malformed_native_call_does_not_fall_back_to_text_parser(self):
        result = self.normalize(
            "qwen_25_compat",
            message={
                "content": '{"name":"read_file","arguments":{"path":"facts.txt"}}',
                "tool_calls": [],
            },
        )
        self.assertIs(result.status, NormalizeStatus.INVALID_TOOL_CALL)
        self.assertEqual(result.source_format, "openai_native")

    def test_limits_content_call_count_and_depth(self):
        content_limited = ToolCallNormalizer(max_content_bytes=4).normalize(
            profile=PROFILES["qwen_25_compat"],
            offered_tools=TOOLS,
            content="12345",
        )
        call_limited = ToolCallNormalizer(max_calls=1).normalize(
            profile=PROFILES["qwen_25_compat"],
            offered_tools=TOOLS,
            content=(
                '[{"name":"read_file","arguments":{"path":"a"}},'
                '{"name":"read_file","arguments":{"path":"b"}}]'
            ),
        )
        depth_limited = ToolCallNormalizer(max_json_depth=1).normalize(
            profile=PROFILES["qwen_25_compat"],
            offered_tools=TOOLS,
            content='{"name":"read_file","arguments":{"path":"facts.txt"}}',
        )
        self.assertIs(content_limited.status, NormalizeStatus.INVALID_TOOL_CALL)
        self.assertIs(call_limited.status, NormalizeStatus.INVALID_TOOL_CALL)
        self.assertIs(depth_limited.status, NormalizeStatus.INVALID_TOOL_CALL)

    def test_registry_is_exact_immutable_and_digestible(self):
        registry = ModelTransportRegistry({"exact-model": "qwen_25_compat"})
        self.assertEqual(registry.resolve("exact-model"), PROFILES["qwen_25_compat"])
        self.assertIsNone(registry.resolve("exact-model:latest"))
        self.assertEqual(len(registry.sha256), 64)
        with self.assertRaises(TypeError):
            registry._assignments["other"] = "json_call"  # type: ignore[index]

    def test_unknown_assigned_model_fails_closed(self):
        result = ToolCallNormalizer().normalize_assigned(
            model_id="unknown",
            registry=ModelTransportRegistry({}),
            offered_tools=TOOLS,
            content="hello",
        )
        self.assertIs(result.status, NormalizeStatus.UNKNOWN_MODEL)

    def test_invalid_offered_schema_fails_before_parsing(self):
        invalid_tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "parameters": {"type": "not-a-json-schema-type"},
                },
            }
        ]
        result = self.normalize(
            "qwen_25_compat",
            tools=invalid_tools,
            content='{"name":"read_file","arguments":{}}',
        )
        self.assertIs(result.status, NormalizeStatus.INVALID_TOOL_CALL)
        self.assertIn("invalid offered tool catalog", result.errors[0])


if __name__ == "__main__":
    unittest.main()
