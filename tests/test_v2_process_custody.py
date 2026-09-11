from __future__ import annotations

import os
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
            "process_custody": "best_effort",
            "require_workspace_isolation": False,
            "require_assessor_isolation": False,
            "writable_paths": ("out.txt",),
            "max_output_bytes": 4096,
            "max_memory_bytes": None,
        }
        values.update(overrides)
        return ContainmentPolicy(**values)

    def test_capabilities_do_not_overclaim_host_filesystem_or_assessor_isolation(self):
        backend = StrictProcessBackend().capabilities
        self.assertFalse(backend.workspace_isolation)
        self.assertTrue(backend.workspace_write_scope)
        self.assertFalse(backend.assessor_isolation)
        self.assertEqual(backend.network_policies, ("task_allowed",))
        self.assertEqual(backend.process_custody, "strict" if os.name == "nt" else "best_effort")

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

    def test_external_host_path_is_reachable_so_workspace_isolation_is_not_claimed(self):
        with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as outside_dir:
            marker = Path(outside_dir) / "external-write.txt"
            code = f"from pathlib import Path; Path({str(marker)!r}).write_text('reachable', encoding='utf-8')"
            result = ContainmentExecutor(StrictProcessBackend(), self.policy(writable_paths=())).execute(
                CommandSpec("external-write-proof", (sys.executable, "-c", code), Path(workspace_dir))
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(marker.read_text(encoding="utf-8"), "reachable")
            self.assertFalse(StrictProcessBackend().capabilities.workspace_isolation)

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

    def test_wall_timeout_kills_normal_descendant_before_it_can_act(self):
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
            self.assertFalse(marker.exists(), "ordinary descendant escaped process cleanup")

    def test_strict_process_custody_claim_is_windows_only(self):
        policy = self.policy(process_custody="strict", writable_paths=())
        result = preflight(policy, StrictProcessBackend().capabilities)
        if os.name == "nt":
            self.assertTrue(result.allowed)
        else:
            self.assertFalse(result.allowed)
            self.assertIn("process_custody_too_weak", result.issues)

    def test_disabled_network_and_workspace_isolation_fail_preflight(self):
        policy = self.policy(
            network_policy="disabled",
            require_workspace_isolation=True,
            writable_paths=(),
        )
        result = preflight(policy, StrictProcessBackend().capabilities)
        self.assertFalse(result.allowed)
        self.assertIn("network_policy_not_enforced:disabled", result.issues)
        self.assertIn("workspace_isolation_not_enforced", result.issues)
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ContainmentBlocked):
                ContainmentExecutor(StrictProcessBackend(), policy).execute(
                    CommandSpec("blocked-isolation", (sys.executable, "-c", "pass"), Path(temp_dir))
                )

    def test_memory_limit_fails_preflight_when_backend_cannot_enforce_it(self):
        policy = self.policy(max_memory_bytes=1_000_000)
        result = preflight(policy, StrictProcessBackend().capabilities)
        self.assertIn("memory_limit_not_enforced", result.issues)

    def test_assessor_backend_validates_staging_but_does_not_claim_os_isolation(self):
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
        self.assertFalse(backend.capabilities.assessor_isolation)
        strict_assessor_policy = self.policy(require_assessor_isolation=True, writable_paths=())
        strict_preflight = preflight(strict_assessor_policy, backend.capabilities)
        self.assertIn("assessor_isolation_not_enforced", strict_preflight.issues)

        staging_only_policy = self.policy(writable_paths=())
        self.assertTrue(preflight(staging_only_policy, backend.capabilities).allowed)
        with tempfile.TemporaryDirectory() as temp_dir:
            result = ContainmentExecutor(backend, staging_only_policy).execute(
                CommandSpec("assessor-smoke", (sys.executable, "-c", "print('assessment')"), Path(temp_dir))
            )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.stdout.decode("utf-8").splitlines(), ["assessment"])


if __name__ == "__main__":
    unittest.main()
