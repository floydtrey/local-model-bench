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
            self.assertEqual(Path(pointer.read_text(encoding="utf-8").strip()), run_dir)
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


if __name__ == "__main__":
    unittest.main()
