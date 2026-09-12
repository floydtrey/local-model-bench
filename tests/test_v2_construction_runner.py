from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "tools" / "construction" / "run-construction-task.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("construction_runner_test_module", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load construction runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConstructionRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_runner()

    def test_runner_python_source_imports(self):
        self.assertTrue(callable(self.runner.main))

    def test_evidence_directory_allocation_never_reuses_a_prior_run(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            first = self.runner.create_unique_directory(parent, "same-second")
            second = self.runner.create_unique_directory(parent, "same-second")
        self.assertEqual(first.name, "same-second")
        self.assertEqual(second.name, "same-second-01")
        self.assertNotEqual(first, second)

    def test_run_directory_pointer_is_exact_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = self.runner.create_unique_directory(root / "runs", "run")
            pointer = root / "staging" / "run-directory.txt"
            self.runner.write_run_directory_file(pointer, run_dir)
            self.assertEqual(
                Path(pointer.read_text(encoding="utf-8").strip()),
                run_dir.resolve(strict=True),
            )
            with self.assertRaises(FileExistsError):
                self.runner.write_run_directory_file(pointer, run_dir)

    def test_docker_command_is_networkless_read_only_and_pinned_no_pull(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            command = self.runner.command_from_manifest(
                "tests",
                ["python", "-m", "unittest", "discover", "-s", "tests"],
                project_root=root,
                backend="docker",
                docker_image="python:3.12-slim",
                docker_memory="512m",
                docker_cpus="2",
                docker_pids_limit=128,
            )
        argv = list(command.argv)
        self.assertEqual(argv[:3], ["docker", "run", "--rm"])
        self.assertIn("--network", argv)
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertIn("--pull", argv)
        self.assertEqual(argv[argv.index("--pull") + 1], "never")
        self.assertIn("--read-only", argv)
        self.assertIn("--pids-limit", argv)
        self.assertEqual(argv[argv.index("--pids-limit") + 1], "128")
        volume = argv[argv.index("-v") + 1]
        self.assertTrue(volume.endswith(":/workspace:ro"), volume)
        self.assertNotIn("powershell", " ".join(argv).lower())
        self.assertNotIn("cmd.exe", " ".join(argv).lower())

    def test_host_backend_requires_manifest_argv_not_shell_text(self):
        with tempfile.TemporaryDirectory() as temp:
            command = self.runner.command_from_manifest(
                "tests",
                ["python", "-m", "unittest"],
                project_root=Path(temp),
                backend="host",
                docker_image="unused",
                docker_memory="unused",
                docker_cpus="unused",
                docker_pids_limit=1,
            )
        self.assertEqual(command.command_id, "tests")
        self.assertEqual(command.argv[1:], ("-m", "unittest"))

    def test_openai_request_uses_standard_chat_endpoint_and_options(self):
        payload = self.runner.request_payload(
            "openai_compatible",
            model="exact-model",
            messages=[{"role": "user", "content": "test"}],
            tools=self.runner.provider_tools(),
            num_ctx=8192,
            num_predict=512,
        )
        self.assertEqual(
            self.runner.provider_endpoint("openai_compatible", "http://127.0.0.1:18082/"),
            "http://127.0.0.1:18082/v1/chat/completions",
        )
        self.assertEqual(payload["max_tokens"], 512)
        self.assertNotIn("options", payload)
        self.assertNotIn("num_ctx", payload)

    def test_model_aware_interface_is_distinct_and_content_addressed(self):
        tools = self.runner.provider_tools()
        native = self.runner.interface_identity(
            provider="ollama",
            model="same-model",
            profile_name="openai_native",
            tools=tools,
            provider_provenance=None,
        )
        aware = self.runner.interface_identity(
            provider="openai_compatible",
            model="same-model",
            profile_name="qwen_25_compat",
            tools=tools,
            provider_provenance={"runtime": "llama.cpp"},
        )
        self.assertNotEqual(native["sha256"], aware["sha256"])
        self.assertEqual(aware["tool_transport_mode"], "model_aware_structured")
        self.assertEqual(aware["backend_tool_execution"], "forbidden")
        self.assertEqual(aware["malformed_call_policy"], "fail_closed")

    def test_normalized_history_uses_deterministic_structured_call(self):
        call = self.runner.ToolCall(
            "interface-1-1", "read_file", {"path": "facts.txt"}
        )
        message = self.runner.provider_message_for_history(
            "openai_compatible",
            {"content": '```json\n{"name":"read_file"}\n```'},
            [(call, "normalized-1-1")],
        )
        self.assertIsNone(message["content"])
        self.assertEqual(message["tool_calls"][0]["id"], "normalized-1-1")
        self.assertEqual(
            message["tool_calls"][0]["function"]["arguments"],
            '{"path":"facts.txt"}',
        )


if __name__ == "__main__":
    unittest.main()
