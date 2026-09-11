from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from localbench.v2 import (
    CONFIG_SPEC_VERSION,
    ModelTurnRequest,
    OllamaChatDriver,
    OllamaDriverError,
    model_identity,
    ollama_adapter_resolution,
    resolve_effective_configuration,
    runtime_profile,
)


DIGEST = "a" * 64


class _Endpoint:
    def __init__(self, response, *, status=200):
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                outer.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "json": json.loads(self.rfile.read(length)),
                    }
                )
                body = json.dumps(response).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address
        return self, f"http://{host}:{port}"

    def __exit__(self, exc_type, exc, traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _spec(*, reasoning, response_format=None, tools=False):
    return {
        "schema_version": CONFIG_SPEC_VERSION,
        "comparison_mode": "strict",
        "generation": {
            "context_tokens": 32768,
            "max_output_tokens": 4096,
            "temperature": 0,
            "seed": 42,
            "top_p": 1,
            "top_k": None,
            "repeat_penalty": None,
            "stop": [],
            "response_format": response_format or {"mode": "text", "schema": None},
            "reasoning": reasoning,
        },
        "execution": {
            "timeout_seconds": 600,
            "retries": 0,
            "retry_delay_seconds": 0,
            "concurrency": 1,
            "model_residency": {
                "mode": "unload_after_model",
                "keep_alive_seconds": 0,
            },
            "network_policy": "provider_only",
        },
        "tool_surface": {
            "id": "tools" if tools else "none",
            "tools": ["read_file", "write_file"] if tools else [],
            "max_tool_calls": 4 if tools else 0,
            "schema_sha256": "b" * 64 if tools else None,
        },
    }


def _foundation(endpoint="http://127.0.0.1:11434"):
    runtime = runtime_profile(
        "ollama-test",
        runtime_kind="ollama",
        version="0.34.0",
        build=None,
        transport={"kind": "loopback_http", "endpoint": endpoint},
        executable=None,
        installation_digest=None,
        capabilities={"chat": True, "tools": True},
    )
    model = model_identity(
        "model-test",
        family="test",
        name="candidate:tag",
        source={"kind": "provider_registry", "locator": "candidate:tag"},
        artifact_digest=None,
        provider_digest=DIGEST,
        parameter_count=None,
        quantization="test",
        precision=None,
        declared_context_tokens=32768,
    )
    return runtime, model


def _config(*, reasoning, transport, endpoint="http://127.0.0.1:11434", response_format=None, tools=False):
    runtime, model = _foundation(endpoint)
    spec = _spec(reasoning=reasoning, response_format=response_format, tools=tools)
    adapter = ollama_adapter_resolution(
        spec, runtime=runtime, model=model, reasoning_transport=transport
    )
    return resolve_effective_configuration(
        "ollama-config",
        runtime=runtime,
        model=model,
        spec=spec,
        adapter_resolution=adapter,
    )


class OllamaAdapterTests(unittest.TestCase):
    def test_boolean_and_effort_reasoning_map_exactly(self):
        runtime, model = _foundation()
        boolean = ollama_adapter_resolution(
            _spec(reasoning={"mode": "enabled", "effort": None}),
            runtime=runtime,
            model=model,
            reasoning_transport="boolean",
        )["effective_request"]
        effort = ollama_adapter_resolution(
            _spec(reasoning={"mode": "enabled", "effort": "medium"}),
            runtime=runtime,
            model=model,
            reasoning_transport="effort",
        )["effective_request"]
        self.assertIs(boolean["think"], True)
        self.assertEqual(effort["think"], "medium")
        self.assertEqual(boolean["options"]["num_ctx"], 32768)
        self.assertEqual(boolean["options"]["num_predict"], 4096)
        self.assertEqual(boolean["keep_alive"], 0)

    def test_unsupported_reasoning_is_explicitly_omitted(self):
        runtime, model = _foundation()
        request = ollama_adapter_resolution(
            _spec(reasoning={"mode": "unsupported", "effort": None}),
            runtime=runtime,
            model=model,
            reasoning_transport="unsupported",
        )["effective_request"]
        self.assertEqual(request["think_parameter"], "omitted")
        self.assertNotIn("think", request)

    def test_incompatible_reasoning_mapping_fails_closed(self):
        runtime, model = _foundation()
        with self.assertRaisesRegex(ValueError, "cannot represent an effort"):
            ollama_adapter_resolution(
                _spec(reasoning={"mode": "enabled", "effort": "medium"}),
                runtime=runtime,
                model=model,
                reasoning_transport="boolean",
            )

    def test_non_provider_network_policy_cannot_claim_exact_resolution(self):
        runtime, model = _foundation()
        spec = _spec(reasoning={"mode": "enabled", "effort": None})
        spec["execution"]["network_policy"] = "disabled"
        with self.assertRaisesRegex(ValueError, "provider_only"):
            ollama_adapter_resolution(
                spec,
                runtime=runtime,
                model=model,
                reasoning_transport="boolean",
            )


class OllamaDriverTests(unittest.TestCase):
    def test_fake_endpoint_receives_exact_neutral_request_mapping(self):
        response = {
            "model": "candidate:tag",
            "created_at": "2026-09-11T00:00:00Z",
            "message": {"role": "assistant", "content": "done", "thinking": "checked"},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 12,
            "eval_count": 3,
        }
        request = ModelTurnRequest(
            case_id="case-a",
            turn=1,
            messages=(
                {"role": "system", "content": "Follow the contract."},
                {"role": "user", "content": "Answer."},
            ),
            context_assets=(
                {
                    "asset_id": "facts",
                    "sha256": DIGEST,
                    "media_type": "text/plain",
                    "delivery": "inline_context",
                    "content_utf8": "alpha=7",
                },
            ),
            tools=(),
        )
        with _Endpoint(response) as (endpoint, base_url):
            config = _config(
                reasoning={"mode": "enabled", "effort": None},
                transport="boolean",
                endpoint=base_url,
            )
            result = OllamaChatDriver(config)(request)

        sent = endpoint.requests[0]
        self.assertEqual(sent["path"], "/api/chat")
        self.assertEqual(sent["json"]["model"], "candidate:tag")
        self.assertEqual(sent["json"]["stream"], False)
        self.assertEqual(sent["json"]["think"], True)
        self.assertEqual(sent["json"]["keep_alive"], 0)
        self.assertEqual(sent["json"]["options"]["num_ctx"], 32768)
        self.assertEqual(sent["json"]["options"]["num_predict"], 4096)
        self.assertEqual(sent["json"]["messages"][1]["role"], "system")
        self.assertIn("alpha=7", sent["json"]["messages"][1]["content"])
        self.assertEqual(result.content, "done")
        self.assertEqual(result.reasoning, "checked")
        self.assertEqual(result.provider_metadata["eval_count"], 3)
        self.assertRegex(result.provider_metadata["raw_response_sha256"], r"^[0-9a-f]{64}$")

    def test_json_schema_tools_and_tool_results_are_translated(self):
        schema = {
            "type": "object",
            "required": ["ok"],
            "properties": {"ok": {"type": "boolean"}},
        }
        response = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "read_file", "arguments": {"path": "a.txt"}}}
                ],
            },
            "done": False,
        }
        request = ModelTurnRequest(
            case_id="case-a",
            turn=2,
            messages=(
                {
                    "role": "assistant",
                    "content": None,
                    "reasoning": "I need the file.",
                    "tool_calls": [
                        {"call_id": "prior", "name": "read_file", "arguments": {"path": "a.txt"}}
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "prior",
                    "name": "read_file",
                    "result": {"ok": True, "content": "alpha"},
                },
            ),
            context_assets=(),
            tools=(
                {
                    "name": "read_file",
                    "description": "Read a file.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            ),
        )
        with _Endpoint(response) as (endpoint, base_url):
            config = _config(
                reasoning={"mode": "enabled", "effort": "medium"},
                transport="effort",
                endpoint=base_url,
                response_format={"mode": "json_schema", "schema": schema},
                tools=True,
            )
            result = OllamaChatDriver(config)(request)

        payload = endpoint.requests[0]["json"]
        self.assertEqual(payload["think"], "medium")
        self.assertEqual(payload["format"], schema)
        self.assertEqual(payload["tools"][0]["function"]["parameters"], request.tools[0]["input_schema"])
        self.assertEqual(payload["messages"][1]["tool_name"], "read_file")
        self.assertEqual(payload["messages"][0]["thinking"], "I need the file.")
        self.assertEqual(json.loads(payload["messages"][1]["content"])["content"], "alpha")
        self.assertEqual(result.tool_calls[0].call_id, "ollama-2-1")
        self.assertEqual(result.tool_calls[0].name, "read_file")

    def test_fake_endpoint_http_error_is_diagnostic(self):
        request = ModelTurnRequest(
            case_id="case-a",
            turn=1,
            messages=({"role": "user", "content": "Answer."},),
            context_assets=(),
            tools=(),
        )
        with _Endpoint({"error": "model unavailable"}, status=404) as (_, base_url):
            config = _config(
                reasoning={"mode": "unsupported", "effort": None},
                transport="unsupported",
                endpoint=base_url,
            )
            with self.assertRaisesRegex(OllamaDriverError, "HTTP 404.*model unavailable"):
                OllamaChatDriver(config)(request)


if __name__ == "__main__":
    unittest.main()
