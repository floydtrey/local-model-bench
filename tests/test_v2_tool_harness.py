from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from localbench.v2.records import effective_runtime_config
from localbench.v2.tool_harness import (
    BOUNDED_FILE_SURFACE_ID,
    BOUNDED_FILE_TOOL_SCHEMA_SHA256,
    ModelTurnResponse,
    ToolCall,
    run_bounded_tool_harness,
    validate_tool_execution_trace,
)


DIGEST = "a" * 64


def _ref(record_type: str, logical_id: str) -> dict[str, str]:
    return {"record_type": record_type, "logical_id": logical_id, "sha256": DIGEST}


def _config(*, max_tool_calls: int = 4, schema_sha256: str = BOUNDED_FILE_TOOL_SCHEMA_SHA256):
    return effective_runtime_config(
        "tool-config",
        runtime=_ref("runtime_profile", "runtime"),
        model=_ref("model_identity", "model"),
        settings={"schema_version": "test"},
        tool_surface={
            "id": BOUNDED_FILE_SURFACE_ID,
            "tools": ["read_file", "write_file"],
            "max_tool_calls": max_tool_calls,
            "schema_sha256": schema_sha256,
        },
        limits={"timeout_seconds": 60},
    )


def _case() -> dict:
    return {
        "case_id": "synthetic-file-task",
        "objective": "Synthetic harness contract fixture only.",
        "input": {
            "messages": [
                {"role": "system", "content": "Use only the supplied tools."},
                {"role": "user", "content": "Read input.txt and write output.txt."},
            ],
            "context_assets": [],
        },
        "requirements": {
            "configuration_profile": "synthetic",
            "response_contract": {"mode": "text", "schema": None},
            "tool_surface": {
                "id": BOUNDED_FILE_SURFACE_ID,
                "required_tools": ["read_file", "write_file"],
            },
            "minimum_context_tokens": None,
        },
        "evaluators": [
            {"evaluator_id": "synthetic", "contract_version": "v1"}
        ],
        "hard_failure_rules": [],
        "repetitions": {"screen_trials": 1, "qualification_trials": 1},
        "tags": [],
    }


class SuccessfulDriver:
    def __init__(self) -> None:
        self.turn = 0

    def __call__(self, request):
        self.turn += 1
        if self.turn == 1:
            return ModelTurnResponse(
                tool_calls=(
                    ToolCall("read-1", "read_file", {"path": "input.txt"}),
                )
            )
        if self.turn == 2:
            tool_message = request.messages[-1]
            self._read_sha = tool_message["result"]["sha256"]
            self._content = tool_message["result"]["content"]
            return ModelTurnResponse(
                tool_calls=(
                    ToolCall(
                        "write-1",
                        "write_file",
                        {
                            "path": "output.txt",
                            "content": self._content.upper(),
                            "expected_sha256": None,
                        },
                    ),
                )
            )
        return ModelTurnResponse(content="done")


class V2BoundedToolHarnessTests(unittest.TestCase):
    def _run_success(self, root: Path):
        (root / "input.txt").write_text("alpha\n", encoding="utf-8", newline="\n")
        result = run_bounded_tool_harness(
            trace_logical_id="synthetic-trace",
            case_definition=_case(),
            effective_config=_config(),
            workspace_root=root,
            readable_paths=["input.txt", "output.txt"],
            writable_paths=["output.txt"],
            driver=SuccessfulDriver(),
        )
        return result

    def test_successful_read_write_loop_produces_replayable_trace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._run_success(root)

            self.assertEqual(result.status, "success")
            self.assertEqual(result.stop_reason, "terminal_output")
            self.assertEqual((root / "output.txt").read_text(encoding="utf-8"), "ALPHA\n")
            validate_tool_execution_trace(result.trace)

            payload = result.trace.payload
            self.assertEqual(payload["summary"]["model_turns"], 3)
            self.assertEqual(payload["summary"]["tool_calls"], 2)
            self.assertEqual(payload["summary"]["authorized_tool_calls"], 2)
            self.assertEqual(payload["summary"]["denied_tool_calls"], 0)
            self.assertEqual(payload["summary"]["successful_tool_calls"], 2)
            self.assertEqual(len(payload["events"]), 13)
            self.assertEqual(payload["events"][-1]["event_type"], "terminal_output")
            self.assertEqual(
                payload["initial_workspace"]["files"][1]["state"], "missing"
            )
            self.assertEqual(
                payload["final_workspace"]["files"][1]["state"], "file"
            )

            serialized = json.dumps(result.trace.to_dict(), sort_keys=True)
            self.assertNotIn(str(root), serialized)

    def test_trace_identity_is_independent_of_disposable_root_location(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            left = self._run_success(Path(first))
            right = self._run_success(Path(second))

        self.assertEqual(left.trace.sha256, right.trace.sha256)
        self.assertEqual(left.trace.to_dict(), right.trace.to_dict())

    def test_traversal_request_is_denied_without_filesystem_access(self):
        class Driver:
            def __init__(self):
                self.turn = 0

            def __call__(self, request):
                self.turn += 1
                if self.turn == 1:
                    return ModelTurnResponse(
                        tool_calls=(
                            ToolCall("escape", "read_file", {"path": "../secret.txt"}),
                        )
                    )
                self.result = request.messages[-1]["result"]
                return ModelTurnResponse(content="stopped")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "input.txt").write_text("safe", encoding="utf-8")
            driver = Driver()
            result = run_bounded_tool_harness(
                trace_logical_id="denial-trace",
                case_definition=_case(),
                effective_config=_config(),
                workspace_root=root,
                readable_paths=["input.txt"],
                writable_paths=["output.txt"],
                driver=driver,
            )

        self.assertEqual(result.status, "success")
        self.assertEqual(driver.result["error"], "authorization_denied")
        self.assertEqual(driver.result["reason"], "invalid_path")
        self.assertEqual(result.trace.payload["summary"]["denied_tool_calls"], 1)
        authorization = [
            event
            for event in result.trace.payload["events"]
            if event["event_type"] == "tool_authorization"
        ][0]
        self.assertFalse(authorization["payload"]["allowed"])

    def test_unknown_tool_is_denied_and_never_executed(self):
        class Driver:
            def __init__(self):
                self.turn = 0

            def __call__(self, request):
                self.turn += 1
                if self.turn == 1:
                    return ModelTurnResponse(
                        tool_calls=(ToolCall("shell-1", "shell", {"command": "whoami"}),)
                    )
                self.result = request.messages[-1]["result"]
                return ModelTurnResponse(content="done")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver = Driver()
            result = run_bounded_tool_harness(
                trace_logical_id="unknown-tool-trace",
                case_definition=_case(),
                effective_config=_config(),
                workspace_root=root,
                readable_paths=[],
                writable_paths=["output.txt"],
                driver=driver,
            )

        self.assertEqual(driver.result["reason"], "tool_not_exposed")
        self.assertEqual(result.trace.payload["summary"]["denied_tool_calls"], 1)

    def test_stale_write_is_recorded_without_overwriting_target(self):
        original = "old\n"
        wrong_digest = hashlib.sha256(b"different").hexdigest()

        class Driver:
            def __init__(self):
                self.turn = 0

            def __call__(self, request):
                self.turn += 1
                if self.turn == 1:
                    return ModelTurnResponse(
                        tool_calls=(
                            ToolCall(
                                "write-1",
                                "write_file",
                                {
                                    "path": "output.txt",
                                    "content": "new\n",
                                    "expected_sha256": wrong_digest,
                                },
                            ),
                        )
                    )
                self.result = request.messages[-1]["result"]
                return ModelTurnResponse(content="done")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "output.txt").write_text(original, encoding="utf-8", newline="\n")
            driver = Driver()
            result = run_bounded_tool_harness(
                trace_logical_id="stale-trace",
                case_definition=_case(),
                effective_config=_config(),
                workspace_root=root,
                readable_paths=["output.txt"],
                writable_paths=["output.txt"],
                driver=driver,
            )
            self.assertEqual((root / "output.txt").read_text(encoding="utf-8"), original)

        self.assertEqual(driver.result["error"], "stale_write")
        self.assertEqual(result.trace.payload["summary"]["failed_tool_calls"], 1)
        self.assertEqual(result.trace.payload["summary"]["authorized_tool_calls"], 1)

    def test_max_tool_call_limit_stops_before_extra_execution(self):
        class Driver:
            def __init__(self):
                self.turn = 0

            def __call__(self, request):
                self.turn += 1
                return ModelTurnResponse(
                    tool_calls=(ToolCall(f"read-{self.turn}", "read_file", {"path": "input.txt"}),)
                )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "input.txt").write_text("x", encoding="utf-8")
            result = run_bounded_tool_harness(
                trace_logical_id="limit-trace",
                case_definition=_case(),
                effective_config=_config(max_tool_calls=1),
                workspace_root=root,
                readable_paths=["input.txt"],
                writable_paths=["output.txt"],
                driver=Driver(),
            )

        self.assertEqual(result.status, "resource_limit")
        self.assertEqual(result.stop_reason, "max_tool_calls")
        self.assertEqual(result.trace.payload["summary"]["tool_calls"], 1)
        self.assertEqual(result.trace.payload["summary"]["model_turns"], 2)
        self.assertEqual(result.trace.payload["events"][-1]["event_type"], "limit_reached")

    def test_surface_binding_fails_closed_on_wrong_schema_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "schema digest"):
                run_bounded_tool_harness(
                    trace_logical_id="bad-surface",
                    case_definition=_case(),
                    effective_config=_config(schema_sha256="b" * 64),
                    workspace_root=Path(temp),
                    readable_paths=[],
                    writable_paths=["output.txt"],
                    driver=lambda request: ModelTurnResponse(content="unused"),
                )

    def test_invalid_driver_response_is_protocol_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_bounded_tool_harness(
                trace_logical_id="protocol-trace",
                case_definition=_case(),
                effective_config=_config(),
                workspace_root=Path(temp),
                readable_paths=[],
                writable_paths=["output.txt"],
                driver=lambda request: {"content": "not-normalized"},
            )

        self.assertEqual(result.status, "protocol_failure")
        self.assertEqual(result.stop_reason, "invalid_model_response")
        self.assertEqual(result.trace.payload["events"][-1]["event_type"], "protocol_error")


if __name__ == "__main__":
    unittest.main()
