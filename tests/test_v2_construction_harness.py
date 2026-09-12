from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

from localbench.v2.construction_harness import (
    CONSTRUCTION_TOOL_DEFINITIONS,
    CONSTRUCTION_TOOL_SURFACE_ID,
    AuthorizedCommand,
    ConstructionScope,
    ConstructionWorkspace,
)
from localbench.v2.tool_harness import ToolCall


class ConstructionHarnessTests(unittest.TestCase):
    def make_workspace(self, root: Path) -> ConstructionWorkspace:
        (root / "src").mkdir()
        (root / "tests").mkdir()
        (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "src" / "obsolete.py").write_text("OLD = True\n", encoding="utf-8")
        (root / "tests" / "test_app.py").write_text(
            "import unittest\n"
            "from src.app import VALUE\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.assertEqual(VALUE, 1)\n",
            encoding="utf-8",
        )
        scope = ConstructionScope(
            readable_paths=("src/app.py", "src/obsolete.py", "tests/test_app.py"),
            writable_paths=("src/app.py", "src/new.py", "tests/test_app.py"),
            deletable_paths=("src/obsolete.py",),
            commands=(
                AuthorizedCommand(
                    "tests",
                    (sys.executable, "-m", "unittest", "discover", "-s", "tests"),
                    timeout_seconds=30,
                ),
            ),
        )
        return ConstructionWorkspace(root, scope)

    def test_surface_exposes_bounded_mutation_and_opaque_command_id(self):
        names = [item["name"] for item in CONSTRUCTION_TOOL_DEFINITIONS]
        self.assertEqual(
            names,
            ["read_file", "write_file", "delete_file", "run_command"],
        )
        run_schema = CONSTRUCTION_TOOL_DEFINITIONS[-1]["input_schema"]
        self.assertEqual(set(run_schema["properties"]), {"command_id"})
        self.assertEqual(CONSTRUCTION_TOOL_SURFACE_ID, "lab-construction-tools:v1")

    def test_delete_requires_exact_authorized_path_and_current_sha(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_workspace(root)
            target = root / "src" / "obsolete.py"
            actual = hashlib.sha256(target.read_bytes()).hexdigest()

            wrong = workspace.execute(
                ToolCall(
                    "delete-wrong",
                    "delete_file",
                    {"path": "src/obsolete.py", "expected_sha256": "0" * 64},
                )
            )
            self.assertFalse(wrong["ok"])
            self.assertEqual(wrong["error"], "sha256_mismatch")
            self.assertTrue(target.exists())

            blocked = workspace.execute(
                ToolCall(
                    "delete-blocked",
                    "delete_file",
                    {"path": "src/app.py", "expected_sha256": hashlib.sha256((root / "src" / "app.py").read_bytes()).hexdigest()},
                )
            )
            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["error"], "path_not_deletable")
            self.assertTrue((root / "src" / "app.py").exists())

            allowed = workspace.execute(
                ToolCall(
                    "delete-ok",
                    "delete_file",
                    {"path": "src/obsolete.py", "expected_sha256": actual},
                )
            )
            self.assertTrue(allowed["ok"])
            self.assertEqual(allowed["deleted_sha256"], actual)
            self.assertFalse(target.exists())

    def test_authorized_command_runs_without_accepting_shell_text(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.make_workspace(Path(temp))
            result = workspace.execute(
                ToolCall("run-tests", "run_command", {"command_id": "tests"})
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["exit_code"], 0)
            self.assertIn("OK", result["stderr"])

            blocked = workspace.execute(
                ToolCall("run-shell", "run_command", {"command_id": "powershell -Command whoami"})
            )
            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["error"], "command_not_authorized")

            injected = workspace.execute(
                ToolCall(
                    "run-injected",
                    "run_command",
                    {"command_id": "tests", "argv": ["whoami"]},
                )
            )
            self.assertFalse(injected["ok"])
            self.assertEqual(injected["error"], "invalid_arguments")

    def test_existing_read_write_semantics_are_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_workspace(root)
            read = workspace.execute(
                ToolCall("read", "read_file", {"path": "src/app.py"})
            )
            self.assertTrue(read["ok"])
            old_sha = read["sha256"]

            write = workspace.execute(
                ToolCall(
                    "write",
                    "write_file",
                    {
                        "path": "src/app.py",
                        "content": "VALUE = 2\n",
                        "expected_sha256": old_sha,
                    },
                )
            )
            self.assertTrue(write["ok"])
            self.assertEqual((root / "src" / "app.py").read_text(encoding="utf-8"), "VALUE = 2\n")

            create = workspace.execute(
                ToolCall(
                    "create",
                    "write_file",
                    {
                        "path": "src/new.py",
                        "content": "NEW = True\n",
                        "expected_sha256": None,
                    },
                )
            )
            self.assertTrue(create["ok"])
            self.assertTrue((root / "src" / "new.py").is_file())

    def test_snapshot_includes_deletable_only_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.make_workspace(Path(temp))
            snapshot = workspace.snapshot()
            states = {item["path"]: item["state"] for item in snapshot["files"]}
            self.assertEqual(states["src/obsolete.py"], "file")
            self.assertEqual(states["src/new.py"], "missing")


if __name__ == "__main__":
    unittest.main()
