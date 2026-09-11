from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from localbench.v2.containment import (
    BackendExecution,
    CommandSpec,
    ContainmentBlocked,
    ContainmentCapabilities,
    ContainmentExecutor,
    ContainmentPolicy,
    NativeSubprocessBackend,
    preflight,
    validate_assessor_staging,
)
from localbench.v2.validation_adapter import adapt_legacy_validation_task


class FakeStrictBackend:
    def __init__(self, *, status: str = "completed") -> None:
        self.calls = 0
        self.status = status

    @property
    def capabilities(self) -> ContainmentCapabilities:
        return ContainmentCapabilities(
            backend_id="fake-strict",
            backend_version="1",
            wall_clock_timeout=True,
            process_custody="strict",
            network_policies=("disabled", "provider_only", "task_allowed"),
            workspace_isolation=True,
            workspace_write_scope=True,
            assessor_isolation=True,
            output_limit=True,
            memory_limit=True,
        )

    def execute(self, command: CommandSpec, policy: ContainmentPolicy) -> BackendExecution:
        self.calls += 1
        if self.status == "timeout":
            return BackendExecution(
                status="timeout",
                stop_reason="wall_clock_limit",
                exit_code=-1,
                stdout=b"partial",
                stderr=b"",
                duration_seconds=policy.wall_seconds,
                cleanup_performed=True,
            )
        return BackendExecution(
            status="completed",
            stop_reason="process_exit",
            exit_code=0,
            stdout=b"ok\n",
            stderr=b"",
            duration_seconds=0.01,
            cleanup_performed=False,
        )


class ContainmentTests(unittest.TestCase):
    def strict_policy(self, **overrides):
        values = {
            "wall_seconds": 30,
            "max_attempts": 1,
            "network_policy": "disabled",
            "process_custody": "strict",
            "require_workspace_isolation": True,
            "require_assessor_isolation": True,
            "writable_paths": ("src/example.py",),
            "max_output_bytes": 100_000,
            "max_memory_bytes": 256_000_000,
        }
        values.update(overrides)
        return ContainmentPolicy(**values)

    def test_policy_digest_is_canonical_and_path_order_independent(self):
        left = self.strict_policy(writable_paths=("z.txt", "a.txt"))
        right = self.strict_policy(writable_paths=("a.txt", "z.txt"))
        self.assertEqual(left.sha256, right.sha256)
        self.assertEqual(left.writable_paths, ("a.txt", "z.txt"))

    def test_native_backend_fails_closed_for_strict_real_task_policy(self):
        result = preflight(self.strict_policy(), NativeSubprocessBackend().capabilities)
        self.assertFalse(result.allowed)
        self.assertIn("process_custody_too_weak", result.issues)
        self.assertIn("network_policy_not_enforced:disabled", result.issues)
        self.assertIn("workspace_isolation_not_enforced", result.issues)
        self.assertIn("workspace_write_scope_not_enforced", result.issues)
        self.assertIn("assessor_isolation_not_enforced", result.issues)
        self.assertIn("output_limit_not_enforced", result.issues)
        self.assertIn("memory_limit_not_enforced", result.issues)

    def test_unresolved_write_scope_blocks_even_strict_backend(self):
        policy = self.strict_policy(writable_paths=None, max_output_bytes=None, max_memory_bytes=None)
        result = preflight(policy, FakeStrictBackend().capabilities)
        self.assertEqual(result.issues, ("workspace_write_scope_unresolved",))

    def test_executor_enforces_attempt_limit_and_seals_evidence_without_workspace_locator(self):
        backend = FakeStrictBackend()
        policy = self.strict_policy(max_output_bytes=None, max_memory_bytes=None)
        with tempfile.TemporaryDirectory() as temp_dir:
            command = CommandSpec(
                command_id="assessor-smoke",
                argv=("python", "-c", "print('ok')"),
                cwd=Path(temp_dir),
                cwd_role="candidate_workspace",
            )
            executor = ContainmentExecutor(backend, policy)
            result = executor.execute(command)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.attempt, 1)
            self.assertEqual(result.evidence.record_type, "containment_execution")
            serialized = json.dumps(result.evidence.to_dict(), sort_keys=True)
            self.assertNotIn(str(Path(temp_dir).resolve()), serialized)
            self.assertEqual(result.evidence.payload["policy_sha256"], policy.sha256)
            self.assertEqual(result.evidence.payload["stdout"]["sha256"], "dc51b8c96c2d745df3bd5590d990230a482fd247123599548e0632fdbf97fc22")
            with self.assertRaisesRegex(ContainmentBlocked, "maximum attempt count"):
                executor.execute(command)
        self.assertEqual(backend.calls, 1)

    def test_command_identity_ignores_disposable_workspace_location(self):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            a = CommandSpec("fixed-command", ("python", "-V"), Path(left))
            b = CommandSpec("fixed-command", ("python", "-V"), Path(right))
            self.assertEqual(a.command_sha256, b.command_sha256)

    def test_timeout_is_preserved_as_containment_evidence(self):
        backend = FakeStrictBackend(status="timeout")
        policy = self.strict_policy(max_output_bytes=None, max_memory_bytes=None)
        with tempfile.TemporaryDirectory() as temp_dir:
            result = ContainmentExecutor(backend, policy).execute(
                CommandSpec("timeout-case", ("python", "-c", "pass"), Path(temp_dir))
            )
        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.stop_reason, "wall_clock_limit")
        self.assertTrue(result.evidence.payload["cleanup_performed"])

    def test_assessor_staging_requires_terminal_candidate_and_hidden_assessment(self):
        record = {"assessment_included": False}
        validate_assessor_staging(record, candidate_terminal=True)
        with self.assertRaises(ContainmentBlocked):
            validate_assessor_staging(record, candidate_terminal=False)
        with self.assertRaises(ContainmentBlocked):
            validate_assessor_staging({"assessment_included": True}, candidate_terminal=True)

    def test_legacy_packet_adapter_preserves_source_bytes_and_requires_v2_write_overlay(self):
        root = Path(__file__).resolve().parents[1]
        packet_path = root / "validation-packets" / "real-tasks-v1" / "packet.json"
        source = packet_path.read_bytes()
        unresolved = adapt_legacy_validation_task(source, task_id="RT-001")
        self.assertFalse(unresolved.qualification_ready)
        self.assertEqual(
            unresolved.unresolved_requirements,
            ("explicit_workspace_write_scope_required",),
        )
        self.assertEqual(unresolved.policy.network_policy, "disabled")
        self.assertEqual(unresolved.policy.wall_seconds, 1200.0)
        self.assertEqual(unresolved.policy.max_attempts, 1)
        self.assertIn("assessment/RT-001/test_checkpoint_lock.py", unresolved.assessor_files)

        adapted = adapt_legacy_validation_task(
            source,
            task_id="RT-001",
            writable_paths=("src/localbench/runner.py", "tests/test_runner.py"),
        )
        self.assertTrue(adapted.qualification_ready)
        self.assertTrue(preflight(adapted.policy, FakeStrictBackend().capabilities).allowed)
        self.assertEqual(adapted.packet_sha256, unresolved.packet_sha256)
        self.assertEqual(adapted.policy.writable_paths, ("src/localbench/runner.py", "tests/test_runner.py"))


if __name__ == "__main__":
    unittest.main()
