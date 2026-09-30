from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from localbench.config import load_config
from localbench.evaluate import evaluate_case, evaluate_run
from localbench.providers import OllamaProvider, OpenAICompatibleProvider, ProviderError
from localbench.runner import BenchmarkRunner
from localbench.suites import load_suite
from localbench.util import atomic_write_json


class FakeHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def log_message(self, format, *args):
        return

    def _send(self, status: int, payload: dict):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        type(self).requests.append({"method": "GET", "path": self.path})
        if self.path == "/api/tags":
            self._send(
                200,
                {
                    "models": [
                        {"name": "model-a:latest", "digest": "aaa", "size": 100},
                        {"name": "model-b:latest", "digest": "bbb", "size": 200},
                    ]
                },
            )
        elif self.path == "/api/version":
            self._send(200, {"version": "test-1.0"})
        elif self.path == "/v1/models":
            self._send(200, {"data": [{"id": "open-model", "owned_by": "local"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append({"method": "POST", "path": self.path, "payload": payload})
        if self.path == "/api/chat":
            if not payload.get("messages"):
                self._send(200, {"done": True})
                return
            if payload.get("model") == "always-fails":
                self._send(500, {"error": "synthetic failure"})
                return
            response_number = len(
                [
                    request
                    for request in type(self).requests
                    if request.get("path") == "/api/chat"
                    and request.get("payload", {}).get("messages")
                ]
            )
            self._send(
                200,
                {
                    "model": payload["model"],
                    "message": {"role": "assistant", "content": f"reply-{response_number}"},
                    "done": True,
                    "done_reason": "stop",
                    "total_duration": 2_000_000_000,
                    "load_duration": 500_000_000,
                    "prompt_eval_count": 10,
                    "prompt_eval_duration": 250_000_000,
                    "eval_count": 20,
                    "eval_duration": 1_000_000_000,
                },
            )
        elif self.path == "/v1/chat/completions":
            if payload.get("model") == "echo-secret-error":
                self._send(400, {"echo": self.headers.get("Authorization")})
                return
            self._send(
                200,
                {
                    "id": "chat-1",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "open reply"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
                },
            )
        else:
            self._send(404, {"error": "not found"})


class ServerFixture:
    def __enter__(self):
        FakeHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class UtilTests(unittest.TestCase):
    def test_atomic_write_retries_transient_permission_error(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "checkpoint.json"
            target.write_text('{"old": true}\n', encoding="utf-8")
            real_replace = os.replace
            calls = 0

            def flaky_replace(source, destination):
                nonlocal calls
                calls += 1
                if calls < 3:
                    raise PermissionError("synthetic Windows reader lock")
                return real_replace(source, destination)

            with patch("localbench.util.os.replace", side_effect=flaky_replace):
                atomic_write_json(target, {"new": True})

            self.assertEqual(calls, 3)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"new": True})


class SuiteTests(unittest.TestCase):
    def test_json_and_markdown_load(self):
        project = Path(__file__).resolve().parents[1]
        json_suite = load_suite(project / "suites" / "sample.json")
        md_suite = load_suite(project / "suites" / "sample.md")
        self.assertEqual(json_suite.id, "sample-json")
        self.assertEqual(len(json_suite.cases), 6)
        self.assertEqual(json_suite.cases[-1].id, "create-tasks-from-plan")
        self.assertEqual(json_suite.cases[-1].context_group, "planning-session")
        self.assertEqual(md_suite.id, "sample-markdown")
        self.assertEqual([case.id for case in md_suite.cases], ["review-guard-clause", "refuse-secret"])
        self.assertIn("function divide", md_suite.cases[0].messages[-1]["content"])

    def test_planning_round_has_nine_preserved_pairs(self):
        project = Path(__file__).resolve().parents[1]
        suite = load_suite(project / "suites" / "planning-round-2.json")
        self.assertEqual(len(suite.cases), 18)
        groups = {}
        for case in suite.cases:
            groups.setdefault(case.context_group, []).append(case)
            self.assertIn("evaluation", case.metadata)
        self.assertEqual(len(groups), 9)
        self.assertTrue(all(len(cases) == 2 for cases in groups.values()))


class ProviderTests(unittest.TestCase):
    def test_ollama_structured_format_is_a_top_level_chat_field(self):
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }
        with ServerFixture() as fixture:
            provider = OllamaProvider(
                "test-ollama",
                {"type": "ollama", "base_url": fixture.base_url, "keep_alive": "5m"},
            )
            provider.chat(
                "model-a:latest",
                [{"role": "user", "content": "hello"}],
                {"temperature": 0, "format": schema},
                2,
            )
            request = next(
                item
                for item in FakeHandler.requests
                if item.get("path") == "/api/chat" and item.get("payload", {}).get("messages")
            )
            self.assertEqual(request["payload"]["format"], schema)
            self.assertEqual(request["payload"]["keep_alive"], "5m")
            self.assertEqual(request["payload"]["options"], {"temperature": 0})
            self.assertNotIn("format", request["payload"]["options"])

    def test_ollama_rejects_invalid_structured_format_locally(self):
        with ServerFixture() as fixture:
            provider = OllamaProvider(
                "test-ollama", {"type": "ollama", "base_url": fixture.base_url}
            )
            with self.assertRaisesRegex(ProviderError, "format"):
                provider.chat(
                    "model-a:latest",
                    [{"role": "user", "content": "hello"}],
                    {"format": "xml"},
                    2,
                )

    def test_openai_compatible_provider(self):
        with ServerFixture() as fixture:
            provider = OpenAICompatibleProvider(
                "test-openai", {"type": "openai_compatible", "base_url": fixture.base_url + "/v1"}
            )
            self.assertEqual(provider.model_metadata("open-model", 2)["owned_by"], "local")
            response = provider.chat(
                "open-model", [{"role": "user", "content": "hello"}], {"temperature": 0}, 2
            )
            self.assertEqual(response.content, "open reply")
            self.assertEqual(response.total_tokens, 7)

    def test_openai_error_body_redacts_environment_credential(self):
        secret = 'key.*[x]"slash\\value'
        with ServerFixture() as fixture, patch.dict(
            os.environ, {"LOCALBENCH_TEST_KEY": secret}, clear=False
        ):
            provider = OpenAICompatibleProvider("test-openai", {
                "type": "openai_compatible",
                "base_url": fixture.base_url + "/v1",
                "api_key_env": "LOCALBENCH_TEST_KEY",
            })
            with self.assertRaises(ProviderError) as raised:
                provider.chat(
                    "echo-secret-error",
                    [{"role": "user", "content": "hello"}],
                    {},
                    2,
                )
            body = raised.exception.body or ""
            self.assertFalse(secret in body, "credential leaked in provider error body")
            self.assertIn("[REDACTED]", body)


class EvaluatorTests(unittest.TestCase):
    def _plan_record(self):
        content = {
            "response_type": "plan",
            "status": "ready",
            "requirements": [{"id": "R1", "interpretation": "Keep the operation atomic."}],
            "assumptions": [],
            "blocking_questions": [],
            "affected_components": ["worker"],
            "steps": [{
                "id": "P1",
                "objective": "Add an atomic boundary.",
                "requirement_ids": ["R1"],
                "dependencies": [],
                "verification": ["Exercise the atomic failure point."],
            }],
            "risks": [{"risk": "partial state", "mitigation": "atomic replacement"}],
            "verification_strategy": ["Run the failure-point test."],
        }
        return {
            "status": "success",
            "suite_id": "evaluation-test",
            "case_id": "plan",
            "model": {"id": "model-a", "name": "model-a", "provider": "mock"},
            "case_metadata": {"evaluation": {
                "kind": "plan",
                "expected_status": "ready",
                "requirement_ids": ["R1"],
                "max_items": 3,
                "semantic_checks": [{"label": "atomic", "any_of": ["atomic"]}],
            }},
            "response": {"content": json.dumps(content), "finish_reason": "stop"},
        }

    def test_complete_plan_scores_one_hundred(self):
        result = evaluate_case(self._plan_record())
        self.assertIsNotNone(result)
        self.assertEqual(result["deterministic_score"], 100)
        self.assertFalse(result["hard_fail"])

    def test_evaluate_run_writes_three_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "models" / "001-model" / "cases").mkdir(parents=True)
            (root / "manifest.json").write_text(json.dumps({
                "run_id": "eval-run",
                "models": [{"sequence": 1, "id": "model-a"}],
            }), encoding="utf-8")
            (root / "models" / "001-model" / "cases" / "0001.json").write_text(
                json.dumps(self._plan_record()), encoding="utf-8"
            )
            report = evaluate_run(root)
            self.assertEqual(report["models"][0]["percent"], 100.0)
            for name in ("evaluation.json", "evaluation.csv", "evaluation.md"):
                self.assertTrue((root / name).is_file())

    def test_evaluate_snapshot_is_isolated_and_non_destructive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cases = root / "models" / "001-model" / "cases"
            cases.mkdir(parents=True)
            manifest = {
                "run_id": "eval-run",
                "status": "running",
                "models": [{"sequence": 1, "id": "model-a"}],
            }
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (cases / "0001.json").write_text(
                json.dumps(self._plan_record()), encoding="utf-8"
            )
            canonical = root / "evaluation.md"
            canonical.write_text("existing canonical report\n", encoding="utf-8")

            report = evaluate_run(root, snapshot="partial-1")

            output = root / "snapshots" / "partial-1"
            self.assertEqual(canonical.read_text(encoding="utf-8"), "existing canonical report\n")
            self.assertTrue(all((output / name).is_file() for name in (
                "evaluation.json", "evaluation.csv", "evaluation.md"
            )))
            self.assertEqual(report["snapshot"]["manifest_status"], "running")
            self.assertEqual(report["snapshot"]["terminal_case_files"], 1)
            with self.assertRaises(FileExistsError):
                evaluate_run(root, snapshot="partial-1")
            with self.assertRaises(ValueError):
                evaluate_run(root, snapshot="../escape")


class RunnerTests(unittest.TestCase):
    def _write_inputs(self, root: Path, base_url: str, *, failing: bool = False):
        suite_path = root / "suite.json"
        suite_path.write_text(
            json.dumps(
                {
                    "suite_id": "context-test",
                    "defaults": {"system": "same system"},
                    "cases": [
                        {
                            "id": "turn-1",
                            "context": {"mode": "preserve", "group": "g"},
                            "prompt": "first",
                        },
                        {
                            "id": "turn-2",
                            "context": {"mode": "preserve", "group": "g"},
                            "prompt": "second",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        config_path = root / "config.json"
        names = ["always-fails"] if failing else ["model-a:latest", "model-b:latest"]
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "result_root": "results",
                    "providers": {
                        "mock": {"type": "ollama", "base_url": base_url, "keep_alive": "1m"}
                    },
                    "models": [
                        {
                            "id": f"model-{index}",
                            "provider": "mock",
                            "name": name,
                            "options": {"temperature": 0, "seed": 42},
                        }
                        for index, name in enumerate(names, 1)
                    ],
                    "run": {
                        "timeout_seconds": 2,
                        "retries": 1,
                        "retry_delay_seconds": 0,
                        "unload_after_model": True,
                    },
                }
            ),
            encoding="utf-8",
        )
        config, config_hash = load_config(config_path)
        return config_path, config, config_hash, [load_suite(suite_path)]

    def test_model_order_context_results_and_resume(self):
        with tempfile.TemporaryDirectory() as temp, ServerFixture() as fixture:
            root = Path(temp)
            config_path, config, config_hash, suites = self._write_inputs(root, fixture.base_url)
            runner = BenchmarkRunner(
                config, config_path, config_hash, suites, run_id="test-run"
            )
            run_dir = runner.run()
            case_requests = [
                request["payload"]
                for request in FakeHandler.requests
                if request.get("path") == "/api/chat"
                and request.get("payload", {}).get("messages")
            ]
            self.assertEqual([item["model"] for item in case_requests], [
                "model-a:latest", "model-a:latest", "model-b:latest", "model-b:latest"
            ])
            self.assertEqual(
                [message["role"] for message in case_requests[1]["messages"]],
                ["system", "user", "assistant", "user"],
            )
            result_files = sorted(run_dir.glob("models/*/cases/*.json"))
            self.assertEqual(len(result_files), 4)
            first = json.loads(result_files[0].read_text(encoding="utf-8"))
            self.assertEqual(first["tokens"]["output"], 20)
            self.assertAlmostEqual(first["timing"]["output_tokens_per_second"], 20.0)
            model_record = json.loads(next(run_dir.glob("models/*/model.json")).read_text())
            self.assertEqual(model_record["provider_runtime_metadata"]["version"], "test-1.0")
            self.assertEqual(json.loads((run_dir / "manifest.json").read_text())["status"], "completed")
            checkpoint = json.loads((run_dir / "checkpoint.json").read_text())
            self.assertEqual(checkpoint["status"], "completed")
            self.assertEqual(checkpoint["progress"], {"completed": 4, "total": 4, "percent": 100.0})
            self.assertIsNone(checkpoint["current"])
            self.assertTrue((run_dir / "summary.csv").exists())

            # A running case checkpoint exposes the authoritative provider-call
            # timeout window for read-only terminal monitoring.
            runner._checkpoint(1, config["models"][0], suites[0], suites[0].cases[0], "running")
            active = json.loads((run_dir / "checkpoint.json").read_text())
            self.assertEqual(active["current"]["timeout_seconds"], 2.0)
            self.assertIn("started_at", active["current"])
            self.assertIn("deadline_at", active["current"])

            before = len(case_requests)
            resumed = BenchmarkRunner(
                config, config_path, config_hash, suites, resume_dir=run_dir
            )
            resumed.run()
            after = len(
                [
                    request
                    for request in FakeHandler.requests
                    if request.get("path") == "/api/chat"
                    and request.get("payload", {}).get("messages")
                ]
            )
            self.assertEqual(before, after)

    def test_failed_requests_are_retried_and_captured(self):
        with tempfile.TemporaryDirectory() as temp, ServerFixture() as fixture:
            root = Path(temp)
            config_path, config, config_hash, suites = self._write_inputs(
                root, fixture.base_url, failing=True
            )
            run_dir = BenchmarkRunner(
                config, config_path, config_hash, suites, run_id="failure-run"
            ).run()
            results = [json.loads(path.read_text()) for path in run_dir.glob("models/*/cases/*.json")]
            self.assertEqual(len(results), 2)
            self.assertTrue(all(item["status"] == "error" for item in results))
            self.assertTrue(all(len(item["attempts"]) == 2 for item in results))
            self.assertTrue(all(item["error"]["http_status"] == 500 for item in results))
            manifest = json.loads((run_dir / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "completed_with_errors")


if __name__ == "__main__":
    unittest.main()
