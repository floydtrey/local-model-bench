from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

from localbench.v2.containment import (
    CommandSpec,
    ContainmentBlocked,
    ContainmentExecutor,
    ContainmentPolicy,
    preflight,
)
from localbench.v2.process_custody import StrictAssessorBackend, StrictProcessBackend


class StrictProcessCustodyTests(unittest.TestCase):
    def policy(self, **overrides):
        values = {
            "wall_seconds": 2.0,
            "max_attempts": 1,
            "network_policy": "task_allowed",
            "process_custody": "strict",
            "require_workspace_isolation": True,
            "require_assessor_isolation": False,
            "writable_paths": ("out.txt",),
            "max_output_bytes": 4096,
            "max_memory_bytes": None,
        }
        values.update(overrides)
        return ContainmentPolicy(**values)

    def test_authorized_workspace_change_is_promoted_from_disposable_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "input.txt").write_text("source", encoding="utf-8")
            command = CommandSpec(
                "authorized-write",
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('out.txt').write_text('ok', encoding='utf-8')",
                ),
                root,
            )
            result = ContainmentExecutor(StrictProcessBackend(), self.policy()).execute(command)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.exit_code, 0)
            self.assertEqual((root / "out.txt").read_text(encoding="utf-8"), "ok")
            self.assertTrue(result.evidence.payload["cleanup_performed"])

    def test_unauthorized_workspace_change_is_not_promoted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            command = CommandSpec(
                "unauthorized-write",
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('evil.txt').write_text('no', encoding='utf-8')",
                ),
                root,
            )
            result = ContainmentExecutor(StrictProcessBackend(), self.policy()).execute(command)
            self.assertEqual(result.status, "resource_limit")
            self.assertEqual(result.stop_reason, "workspace_scope_violation")
            self.assertFalse((root / "evil.txt").exists())
            self.assertFalse((root / "out.txt").exists())

    def test_output_limit_terminates_process_without_unbounded_capture(self):
        policy = self.policy(max_output_bytes=128, writable_paths=())
        with tempfile.TemporaryDirectory() as temp_dir:
            result = ContainmentExecutor(StrictProcessBackend(), policy).execute(
                CommandSpec(
                    "output-limit",
                    (sys.executable, "-c", "import sys; sys.stdout.write('x' * 100000); sys.stdout.flush()"),
                    Path(temp_dir),
                )
            )
        self.assertEqual(result.status, "resource_limit")
        self.assertEqual(result.stop_reason, "output_limit")
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 128)
        self.assertTrue(result.evidence.payload["cleanup_performed"])

    def test_wall_timeout_kills_descendant_before_it_can_act(self):
        policy = self.policy(wall_seconds=0.2, writable_paths=())
        with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as marker_dir:
            marker = Path(marker_dir) / "survived.txt"
            child_code = (
                "import pathlib,time; "
                "time.sleep(0.7); "
                f"pathlib.Path({str(marker)!r}).write_text('survived', encoding='utf-8')"
            )
            parent_code = (
                "import subprocess,sys,time; "
                f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
                "time.sleep(5)"
            )
            result = ContainmentExecutor(StrictProcessBackend(), policy).execute(
                CommandSpec("tree-timeout", (sys.executable, "-c", parent_code), Path(workspace_dir))
            )
            self.assertEqual(result.status, "timeout")
            self.assertEqual(result.stop_reason, "wall_clock_limit")
            self.assertTrue(result.evidence.payload["cleanup_performed"])
            time.sleep(0.9)
            self.assertFalse(marker.exists(), "descendant escaped process custody")

    def test_disabled_network_policy_fails_preflight_instead_of_downgrading(self):
        policy = self.policy(network_policy="disabled")
        result = preflight(policy, StrictProcessBackend().capabilities)
        self.assertFalse(result.allowed)
        self.assertIn("network_policy_not_enforced:disabled", result.issues)
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ContainmentBlocked):
                ContainmentExecutor(StrictProcessBackend(), policy).execute(
                    CommandSpec("blocked-network", (sys.executable, "-c", "pass"), Path(temp_dir))
                )

    def test_memory_limit_fails_preflight_when_backend_cannot_enforce_it(self):
        policy = self.policy(max_memory_bytes=1_000_000)
        result = preflight(policy, StrictProcessBackend().capabilities)
        self.assertIn("memory_limit_not_enforced", result.issues)

    def test_assessor_backend_requires_hidden_assessment_and_terminal_candidate(self):
        with self.assertRaises(ContainmentBlocked):
            StrictAssessorBackend(
                workspace_record={"assessment_included": True},
                candidate_terminal=True,
            )
        with self.assertRaises(ContainmentBlocked):
            StrictAssessorBackend(
                workspace_record={"assessment_included": False},
                candidate_terminal=False,
            )

        backend = StrictAssessorBackend(
            workspace_record={"assessment_included": False},
            candidate_terminal=True,
        )
        policy = self.policy(require_assessor_isolation=True, writable_paths=())
        self.assertTrue(preflight(policy, backend.capabilities).allowed)
        with tempfile.TemporaryDirectory() as temp_dir:
            result = ContainmentExecutor(backend, policy).execute(
                CommandSpec("assessor-smoke", (sys.executable, "-c", "print('assessment')"), Path(temp_dir))
            )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.stdout.decode("utf-8").splitlines(), ["assessment"])


if __name__ == "__main__":
    unittest.main()
