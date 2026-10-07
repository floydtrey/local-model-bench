from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from localbench.v2.configuration import CONFIG_SPEC_VERSION, resolve_effective_configuration
from localbench.v2.contracts import canonical_json_bytes, seal_evidence
from localbench.v2.llama_cpp_driver import LlamaCppChatDriver, LlamaCppDriverError, llama_cpp_adapter_resolution
from localbench.v2.records import model_identity, runtime_profile
from localbench.v2.tool_harness import (
    BOUNDED_FILE_SURFACE_ID, BOUNDED_FILE_TOOL_DEFINITIONS,
    BOUNDED_FILE_TOOL_SCHEMA_SHA256, ModelTurnRequest,
)


class _Endpoint:
    def __init__(self, response, *, status=200, headers=None, delay=0, drip=False, short_body=False):
        self.body = response if isinstance(response, bytes) else json.dumps(response).encode("utf-8")
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": body, "json": json.loads(body)})
                if delay:
                    time.sleep(delay)
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(outer.body) + (10 if short_body else 0)))
                    for key, value in (headers or {}).items():
                        self.send_header(key, value)
                    self.end_headers()
                    if drip:
                        for byte in outer.body:
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(0.005)
                    else:
                        self.wfile.write(outer.body)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address
        return self, f"http://{host}:{port}"

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _foundation(base_url="http://127.0.0.1:8080", **transport):
    runtime = runtime_profile(
        "flashnext-runtime", runtime_kind="llama_cpp", version="fork-test",
        build="27c54b4bbcefadedcec6397477cc2e866c1db716",
        transport={"kind": "loopback_http", "base_uri": base_url, "context_tokens": 262144,
                   "model_alias": "C01", "reasoning_mode": "auto", **transport},
        executable=None, installation_digest=None, capabilities={"chat": True, "tools": True},
    )
    model = model_identity(
        "flashnext-model", family="Qwen3.8", name="Qwen3.8-Flash-Next UD-IQ3_XXS",
        source={"kind": "gguf", "locator": "fixture.gguf"}, artifact_digest="a" * 64,
        provider_digest=None, parameter_count=None, quantization="UD-IQ3_XXS", precision=None,
        declared_context_tokens=262144,
    )
    return runtime, model


def _spec(*, tools=False, timeout=1, reasoning=None, response_format=None):
    return {
        "schema_version": CONFIG_SPEC_VERSION, "comparison_mode": "strict",
        "generation": {"context_tokens": 262144, "max_output_tokens": 4096,
                       "temperature": 0, "seed": 42, "top_p": 1, "top_k": None,
                       "repeat_penalty": None, "stop": [],
                       "response_format": response_format or {"mode": "text", "schema": None},
                       "reasoning": reasoning or {"mode": "enabled", "effort": None}},
        "execution": {"timeout_seconds": timeout, "retries": 0, "retry_delay_seconds": 0,
                      "concurrency": 1, "model_residency": {"mode": "unload_after_model", "keep_alive_seconds": 0},
                      "network_policy": "provider_only"},
        "tool_surface": {"id": BOUNDED_FILE_SURFACE_ID if tools else "none",
                         "tools": ["read_file", "write_file"] if tools else [],
                         "max_tool_calls": 4 if tools else 0,
                         "schema_sha256": BOUNDED_FILE_TOOL_SCHEMA_SHA256 if tools else None},
    }


def _config(endpoint="http://127.0.0.1:8080", *, transport="server_default", **kwargs):
    runtime, model = _foundation(endpoint)
    spec = _spec(**kwargs)
    resolution = llama_cpp_adapter_resolution(spec, runtime=runtime, model=model, reasoning_transport=transport)
    return resolve_effective_configuration("flashnext-config", runtime=runtime, model=model, spec=spec, adapter_resolution=resolution)


def _request(*, tools=False, messages=None, turn=1, assets=()):
    return ModelTurnRequest(case_id="smoke", turn=turn,
                            messages=tuple(messages or [{"role": "user", "content": "Answer."}]),
                            context_assets=assets, tools=BOUNDED_FILE_TOOL_DEFINITIONS if tools else ())


def _response(*, content="done", calls=None, finish="stop", reasoning=None, **extras):
    message = {"role": "assistant", "content": content}
    if calls is not None:
        message["tool_calls"] = calls
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {"id": "chatcmpl-fixture", "model": "C01",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}], **extras}


def _call(*, call_id="call_native-001", name="read_file", arguments='{"path":"a.txt"}'):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


class LlamaCppAdapterTests(unittest.TestCase):
    def test_resolution_binds_exact_runtime_alias_context_and_generation(self):
        runtime, model = _foundation()
        adapter = llama_cpp_adapter_resolution(_spec(), runtime=runtime, model=model)
        static = adapter["effective_request"]
        self.assertEqual(adapter["status"], "exact")
        self.assertEqual(static["path"], "/v1/chat/completions")
        self.assertEqual(static["model"], "C01")
        self.assertEqual(static["context_tokens"], 262144)
        self.assertEqual(static["runtime_sha256"], runtime.sha256)
        self.assertEqual(static["model_sha256"], model.sha256)
        self.assertEqual(static["parameters"]["max_tokens"], 4096)
        self.assertEqual(static["parameters"]["top_k"], 0)
        self.assertEqual(static["parameters"]["min_p"], 0)
        self.assertNotIn("chat_template_kwargs", static["parameters"])
        self.assertNotIn("num_ctx", static["parameters"])
        self.assertNotIn("keep_alive", static["parameters"])

    def test_invalid_context_alias_or_endpoint_cannot_claim_exact(self):
        for override in ({"context_tokens": 8192}, {"reasoning_mode": "off"},
                         {"base_uri": "http://example.com:8080"},
                         {"base_uri": "http://127.0.0.1:8080/v1"},
                         {"base_uri": "http://secret@127.0.0.1:8080"},
                         {"endpoint": "http://127.0.0.1:9999"}):
            with self.subTest(override=override):
                runtime, model = _foundation(**override)
                with self.assertRaises(ValueError):
                    llama_cpp_adapter_resolution(_spec(), runtime=runtime, model=model)
        runtime, model = _foundation()
        with self.assertRaisesRegex(ValueError, "alias"):
            llama_cpp_adapter_resolution(_spec(), runtime=runtime, model=model, model_alias="another-model")

    def test_unsupported_controls_and_nonfinite_parameters_fail_closed(self):
        runtime, model = _foundation()
        for section, key, value in (("generation", "temperature", float("nan")),
                                    ("generation", "top_p", float("inf")),
                                    ("execution", "timeout_seconds", float("inf")),
                                    ("execution", "concurrency", 2), ("execution", "retries", 1),
                                    ("execution", "network_policy", "task_allowed")):
            with self.subTest(key=key, value=value):
                spec = _spec()
                spec[section][key] = value
                with self.assertRaises(ValueError):
                    llama_cpp_adapter_resolution(spec, runtime=runtime, model=model)
        for reasoning in ({"mode": "disabled", "effort": None}, {"mode": "enabled", "effort": "high"}):
            with self.assertRaises(ValueError):
                llama_cpp_adapter_resolution(_spec(reasoning=reasoning), runtime=runtime, model=model)

    def test_template_boolean_is_explicit_and_changes_sealed_request(self):
        config = _config(transport="template_boolean", reasoning={"mode": "disabled", "effort": None})
        static = config.payload["settings"]["adapter_resolution"]["effective_request"]
        self.assertEqual(static["parameters"]["chat_template_kwargs"]["enable_thinking"], False)
        self.assertNotEqual(config.sha256, _config().sha256)

    def test_resealed_tampered_mapping_is_rejected_before_http(self):
        config = _config()
        for mutation in (lambda p: p["settings"]["adapter_resolution"]["effective_request"]["parameters"].update(max_tokens=8192),
                         lambda p: p["settings"]["adapter_resolution"]["effective_request"].update(path="/api/chat"),
                         lambda p: p["settings"]["adapter_resolution"]["effective_request"].update(runtime_sha256="b" * 64),
                         lambda p: p["settings"]["adapter_resolution"]["effective_request"].update(timeout_seconds=99)):
            payload = config.to_dict()["payload"]
            mutation(payload)
            sealed = seal_evidence(config.record_type, config.logical_id, payload)
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
                LlamaCppChatDriver(sealed, Path(tmp))


class LlamaCppDriverTests(unittest.TestCase):
    def assertArtifact(self, directory, artifact, expected):
        body = (Path(directory) / artifact["path"]).read_bytes()
        self.assertEqual(body, expected)
        self.assertEqual(artifact["size_bytes"], len(expected))
        self.assertEqual(artifact["sha256"], hashlib.sha256(expected).hexdigest())

    def test_real_http_bytes_and_measured_throughput_are_preserved(self):
        response = _response(reasoning="checked", usage={"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52},
                             timings={"prompt_n": 30, "cache_n": 10, "prompt_ms": 200, "predicted_n": 12,
                                      "predicted_ms": 120, "predicted_per_second": 100})
        context = "alpha=7"
        assets = ({"asset_id": "facts", "sha256": hashlib.sha256(context.encode()).hexdigest(),
                   "delivery": "inline_context", "media_type": "text/plain", "content_utf8": context},)
        with tempfile.TemporaryDirectory() as tmp, _Endpoint(response) as (endpoint, url):
            driver = LlamaCppChatDriver(_config(url), Path(tmp))
            result = driver(_request(messages=[{"role": "system", "content": "Follow."}, {"role": "user", "content": "Answer."}], assets=assets))
            metadata = driver.observations[0]
            self.assertArtifact(tmp, metadata["artifacts"]["request_body"], endpoint.requests[0]["body"])
            self.assertArtifact(tmp, metadata["artifacts"]["response_body"], endpoint.body)
            self.assertTrue((Path(tmp) / metadata["observation_file"]).exists())
            self.assertEqual(endpoint.requests[0]["path"], "/v1/chat/completions")
            self.assertEqual(endpoint.requests[0]["json"]["messages"][1]["role"], "system")
            self.assertEqual(endpoint.requests[0]["json"]["model"], "C01")
            self.assertEqual(result.content, "done")
            self.assertEqual(result.reasoning, "checked")
            self.assertEqual(metadata["prompt_tokens"], 40)
            self.assertEqual(metadata["output_tokens"], 12)
            self.assertEqual(metadata["cached_prompt_tokens"], 10)
            self.assertEqual(metadata["generation_tokens_per_second"], 100)
            self.assertEqual(metadata["generation_seconds"], .12)
            self.assertGreater(metadata["request_wall_seconds"], 0)
            self.assertTrue(metadata["response_complete"])
            self.assertEqual(metadata["output_characters"], 4)

    def test_native_ids_arguments_and_reasoning_round_trip_without_prose_parser(self):
        response = _response(content=None, calls=[_call()], finish="tool_calls", reasoning="Read the file.")
        with tempfile.TemporaryDirectory() as tmp, _Endpoint(response) as (endpoint, url):
            driver = LlamaCppChatDriver(_config(url, tools=True), Path(tmp))
            result = driver(_request(tools=True))
            self.assertEqual(result.tool_calls[0].call_id, "call_native-001")
            history = [{"role": "assistant", "content": result.content, "reasoning": result.reasoning,
                        "tool_calls": [call.to_dict() for call in result.tool_calls]},
                       {"role": "tool", "tool_call_id": "call_native-001", "name": "read_file", "result": {"ok": True, "content": "alpha"}}]
            # Reusing the same reply ID would be ambiguous, but its outgoing
            # replay must preserve the ID and exact arguments on the wire.
            with self.assertRaises(LlamaCppDriverError) as raised:
                driver(_request(tools=True, messages=history, turn=2))
            self.assertEqual(raised.exception.category, "tool_transport_incompatible")
            sent = endpoint.requests[1]["json"]["messages"]
            self.assertEqual(sent[0]["tool_calls"][0]["id"], "call_native-001")
            self.assertEqual(sent[1]["tool_call_id"], "call_native-001")
            self.assertEqual(sent[0]["reasoning_content"], "Read the file.")
            self.assertEqual(json.loads(sent[0]["tool_calls"][0]["function"]["arguments"]), {"path": "a.txt"})
            self.assertEqual(json.loads(sent[1]["content"]), {"ok": True, "content": "alpha"})

    def test_duplicate_malformed_or_ambiguous_tool_arguments_are_not_executed(self):
        invalid = ['{"path":"a","path":"b"}', '{"path":"a",}', '[]', '"read_file a"',
                   '{"number":NaN}', '{"number":1e999}', '{"nested":{"x":1,"x":2}}', {"path": "a"}]
        for arguments in invalid:
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as tmp, _Endpoint(
                _response(content=None, calls=[_call(arguments=arguments)], finish="tool_calls")
            ) as (endpoint, url):
                driver = LlamaCppChatDriver(_config(url, tools=True), Path(tmp))
                with self.assertRaises(LlamaCppDriverError) as raised:
                    driver(_request(tools=True))
                self.assertEqual(raised.exception.category, "tool_transport_incompatible")
                self.assertArtifact(tmp, raised.exception.provider_metadata["artifacts"]["response_body"], endpoint.body)

    def test_duplicate_ids_missing_ids_and_mismatched_finish_are_protocol_errors(self):
        invalid = [_response(calls=[_call(), _call()], finish="tool_calls"),
                   _response(calls=[_call(call_id="bad:id")], finish="tool_calls"),
                   _response(calls=[_call(call_id=None)], finish="tool_calls"),
                   _response(calls=[_call()], finish="stop"),
                   _response(calls=[], finish="tool_calls")]
        for response in invalid:
            with self.subTest(response=response), tempfile.TemporaryDirectory() as tmp, _Endpoint(response) as (_, url):
                driver = LlamaCppChatDriver(_config(url, tools=True), Path(tmp))
                with self.assertRaises(LlamaCppDriverError) as raised:
                    driver(_request(tools=True))
                self.assertEqual(raised.exception.category, "tool_transport_incompatible")

    def test_prose_that_looks_like_a_tool_is_only_text(self):
        prose = '{"name":"write_file","arguments":{"path":"a.txt","content":"oops"}}'
        with tempfile.TemporaryDirectory() as tmp, _Endpoint(_response(content=prose)) as (_, url):
            result = LlamaCppChatDriver(_config(url, tools=True), Path(tmp))(_request(tools=True))
            self.assertEqual(result.content, prose)
            self.assertEqual(result.tool_calls, ())
            self.assertEqual(result.provider_metadata["tool_protocol"], "not_observed")
            self.assertTrue(result.provider_metadata["native_calls_absent"])
            self.assertEqual(result.provider_metadata["tool_text_diagnostic"], "potential_tool_shaped_prose")

    def test_malformed_response_preserves_original_invalid_bytes(self):
        for body in (b'{"choices": [', b'\xff invalid utf8', b'{"choices":[],"choices":[]}',
                     b'{"timings":{"predicted_ms":Infinity}}', b'{"x":1e999}'):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as tmp, _Endpoint(body) as (_, url):
                driver = LlamaCppChatDriver(_config(url), Path(tmp))
                with self.assertRaises(LlamaCppDriverError) as raised:
                    driver(_request())
                self.assertEqual(raised.exception.category, "response_parse_error")
                self.assertArtifact(tmp, raised.exception.provider_metadata["artifacts"]["response_body"], body)
                self.assertTrue(raised.exception.provider_metadata["response_complete"])

    def test_http_error_full_body_and_redirect_are_preserved_without_retry(self):
        body = b"model unavailable\n" + b"x" * 9000
        for status in (404, 503, 307):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp, _Endpoint(
                body, status=status, headers={"Location": "http://127.0.0.1:9/other-runtime"}
            ) as (endpoint, url):
                driver = LlamaCppChatDriver(_config(url), Path(tmp))
                with self.assertRaises(LlamaCppDriverError) as raised:
                    driver(_request())
                self.assertEqual(raised.exception.category, "http_error")
                self.assertEqual(len(endpoint.requests), 1)
                self.assertEqual(raised.exception.provider_metadata["http_status"], status)
                self.assertArtifact(tmp, raised.exception.provider_metadata["artifacts"]["response_body"], body)

    def test_length_stop_retains_metrics_and_never_releases_partial_calls(self):
        response = _response(content="partial", calls=[_call()], finish="length",
                             usage={"prompt_tokens": 10, "completion_tokens": 4096})
        with tempfile.TemporaryDirectory() as tmp, _Endpoint(response) as (endpoint, url):
            driver = LlamaCppChatDriver(_config(url, tools=True), Path(tmp))
            with self.assertRaises(LlamaCppDriverError) as raised:
                driver(_request(tools=True))
            metadata = raised.exception.provider_metadata
            self.assertEqual(raised.exception.category, "generation_truncated")
            self.assertTrue(metadata["truncated"])
            self.assertEqual(metadata["finish_reason"], "length")
            self.assertEqual(metadata["output_tokens"], 4096)
            self.assertEqual(metadata["output_characters"], 7)
            self.assertArtifact(tmp, metadata["artifacts"]["response_body"], endpoint.body)

    def test_total_deadline_cuts_off_dripping_response_and_keeps_received_prefix(self):
        with tempfile.TemporaryDirectory() as tmp, _Endpoint(_response(content="x" * 100), drip=True) as (endpoint, url):
            driver = LlamaCppChatDriver(_config(url, timeout=.07), Path(tmp))
            started = time.monotonic()
            with self.assertRaises(LlamaCppDriverError) as raised:
                driver(_request())
            self.assertLess(time.monotonic() - started, .8)
            self.assertEqual(raised.exception.category, "timeout")
            metadata = raised.exception.provider_metadata
            self.assertFalse(metadata["response_complete"])
            received = (Path(tmp) / metadata["artifacts"]["response_body"]["path"]).read_bytes()
            self.assertGreater(len(received), 0)
            self.assertTrue(endpoint.body.startswith(received))
            self.assertLess(len(received), len(endpoint.body))

    def test_short_content_length_response_is_transport_failure(self):
        with tempfile.TemporaryDirectory() as tmp, _Endpoint(_response(), short_body=True) as (endpoint, url):
            driver = LlamaCppChatDriver(_config(url), Path(tmp))
            with self.assertRaises(LlamaCppDriverError) as raised:
                driver(_request())
            self.assertEqual(raised.exception.category, "transport_error")
            self.assertFalse(raised.exception.provider_metadata["response_complete"])
            self.assertArtifact(tmp, raised.exception.provider_metadata["artifacts"]["response_body"], endpoint.body)

    def test_unmeasured_throughput_is_null_and_timings_can_supply_derived_rate(self):
        for extras, expected in (({}, None), ({"usage": {"completion_tokens": 30}}, None),
                                 ({"timings": {"predicted_n": 30, "predicted_ms": 500}}, 60.0)):
            with self.subTest(extras=extras), tempfile.TemporaryDirectory() as tmp, _Endpoint(_response(**extras)) as (_, url):
                result = LlamaCppChatDriver(_config(url), Path(tmp))(_request())
                self.assertEqual(result.provider_metadata["generation_tokens_per_second"], expected)

    def test_bad_usage_or_model_identity_is_interface_failure(self):
        for response, category in ((_response(usage={"completion_tokens": True}), "response_parse_error"),
                                   (_response(timings={"predicted_ms": -3}), "response_parse_error"),
                                   (_response(model="wrong-model"), "model_identity_mismatch")):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as tmp, _Endpoint(response) as (_, url):
                with self.assertRaises(LlamaCppDriverError) as raised:
                    LlamaCppChatDriver(_config(url), Path(tmp))(_request())
                self.assertEqual(raised.exception.category, category)

    def test_sealed_tool_surface_and_native_result_ids_are_checked_before_http(self):
        with tempfile.TemporaryDirectory() as tmp, _Endpoint(_response()) as (endpoint, url):
            driver = LlamaCppChatDriver(_config(url, tools=True), Path(tmp))
            with self.assertRaises(LlamaCppDriverError) as raised:
                driver(_request())
            self.assertEqual(raised.exception.category, "request_contract_error")
            with self.assertRaises(LlamaCppDriverError):
                driver(_request(tools=True, messages=[{"role": "tool", "tool_call_id": "unknown", "name": "read_file", "result": {"ok": True}}]))
            self.assertEqual(endpoint.requests, [])

    def test_json_schema_is_mapped_without_changing_prompt_content(self):
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        with tempfile.TemporaryDirectory() as tmp, _Endpoint(_response(content='{"ok":true}')) as (endpoint, url):
            config = _config(url, response_format={"mode": "json_schema", "schema": schema})
            LlamaCppChatDriver(config, Path(tmp))(_request())
            self.assertEqual(endpoint.requests[0]["json"]["response_format"], {"type": "json_schema", "schema": schema})
            self.assertEqual(endpoint.requests[0]["json"]["messages"][0]["content"], "Answer.")


if __name__ == "__main__":
    unittest.main()
