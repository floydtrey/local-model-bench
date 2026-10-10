"""No Ollama, model downloads, cameras or production databases are used here."""
from __future__ import annotations
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from localbench.assistant001.assessment import assess
from localbench.assistant001.calibration import self_test, install_reference
from localbench.assistant001.campaign import role_prompt, run_probe, run_worker_chain
from localbench.assistant001.cli import main
from localbench.assistant001.packet import (
    packet_root, prepare, read_run, scope_diff, snapshot, task_prompt, validate_packet, write_json)


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="a001-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_validate_and_prepare_do_not_contact_provider_or_execute_candidate(self):
        with patch("subprocess.Popen", side_effect=AssertionError("No process allowed")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("No provider allowed")):
            packet, sha = validate_packet()
            run = prepare(self.root)
        self.assertEqual(packet["packet_id"], "assistant-001-v1")
        self.assertEqual(len(packet["tasks"]), 6)
        self.assertEqual(len(sha), 64)
        self.assertTrue((run / "workspace/CONTRACT.md").is_file())
        self.assertFalse((run / "workspace/assessor").exists())
        self.assertFalse(any("reference" in p for p in snapshot(run / "workspace")))

    def test_unique_workspaces_and_no_overwrite(self):
        first, second = prepare(self.root), prepare(self.root)
        self.assertNotEqual(first, second)
        marker = first / "workspace/README.md"
        original = marker.read_bytes()
        prepare(self.root)
        self.assertEqual(marker.read_bytes(), original)

    def test_bad_label_and_output_in_frozen_packet_rejected(self):
        with self.assertRaises(ValueError):
            prepare(self.root, label="../escape")
        with self.assertRaises(ValueError):
            prepare(packet_root() / "nested")

    def test_corrupted_packet_is_rejected(self):
        fake_repo = self.root / "repo"
        target = fake_repo / "project-benchmarks/assistant-001/v1"
        shutil.copytree(packet_root(), target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (target / "CONTRACT.md").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "integrity"):
            validate_packet(fake_repo)

    def test_run_cannot_change_packet_identity(self):
        run = prepare(self.root)
        data = json.loads((run / "run.json").read_text()); data["packet_sha256"] = "bad"
        write_json(run / "run.json", data)
        with self.assertRaises(ValueError):
            read_run(run)

    def test_scope_finds_edits_creation_and_deletion(self):
        diff = scope_diff({"a": "old", "keep": "unchanged", "gone": "x"},
                          {"a": "new", "keep": "unchanged", "extra": "x"}, ["a"])
        self.assertEqual(diff["unauthorized_paths"], ["extra", "gone"])
        self.assertFalse(diff["passed"])

    def test_task_prompt_keeps_actual_handoff_without_label_requirements(self):
        run = prepare(self.root)
        note = "The prior task works. This is plain prose, not a Handoff note field."
        prompt = task_prompt(run, "T02", note)
        self.assertIn(note, prompt)
        self.assertIn("R01", prompt)
        self.assertNotIn("assessor/reference", prompt)
        self.assertNotIn("WORKER_READY", prompt)

    def test_task_specific_test_edit_exception_does_not_change_frozen_scope(self):
        run = prepare(self.root)
        packet, original_digest = validate_packet()
        for task in ("T01", "T02", "T03", "T04", "T05", "T06"):
            prompt = task_prompt(run, task, "")
            self.assertIn("tests/test_candidate.py is explicitly writable", prompt)
            self.assertIn("general Worker role setup prohibits editing tests", prompt)
            self.assertIn("never other test files or frozen", prompt)
        self.assertEqual(packet["tasks"][0]["requirements"], "R01")
        self.assertEqual(packet["tasks"][0]["writable_paths"],
                         ["assistant_journal/validation.py", "tests/test_candidate.py"])
        self.assertEqual(validate_packet()[1], original_digest)

    def test_validate_cli_is_safe_default_action(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = main(["validate"])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out.getvalue())["candidate_code_executed"])

    def test_run_and_assess_require_explicit_host_acknowledgement(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["run", "--model", "synthetic:fixture"]), 2)
        run = prepare(self.root)
        with self.assertRaisesRegex(ValueError, "not OS-sandboxed"):
            assess(run)

    def test_scope_violation_blocks_before_candidate_execution(self):
        run = prepare(self.root)
        (run / "workspace/CONTRACT.md").write_text("tampered", encoding="utf-8")
        with patch("subprocess.Popen", side_effect=AssertionError("Must not execute candidate")):
            result, path = assess(run, "T01", allow_host_execution=True)
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "scope_failure")
        self.assertTrue((path / "assessment.json").is_file())

    def test_assessor_does_not_accept_an_unsolved_starter(self):
        run = prepare(self.root)
        result, _ = assess(run, "T01", allow_host_execution=True)
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "completed")
        self.assertGreater(result["executed"], 0)

    def test_reference_and_ten_behavioral_mutations(self):
        result = self_test()
        self.assertTrue(result["passed"], json.dumps(result, indent=2))
        self.assertEqual(len(result["checks"]), 12)
        self.assertEqual(result["real_models_started"], 0)


class FakeSessions:
    """Controlled source-writing stand-in, not a benchmarked model."""
    def __init__(self, root, *, fail_task=None, empty_handoff=None):
        self.reference = install_reference(Path(root) / "oracle")
        self.calls = []; self.fail_task = fail_task; self.empty_handoff = empty_handoff

    def __call__(self, *, role, case_id, prompt, workspace, writable, evidence):
        evidence = Path(evidence); evidence.mkdir(parents=True, exist_ok=False)
        task = case_id[-3:].upper()
        self.calls.append(dict(task=task, role=role, prompt=prompt, workspace=workspace, writable=writable))
        if role == "worker" and task != self.fail_task:
            for name in writable:
                src = self.reference / name
                if src.exists():
                    shutil.copyfile(src, Path(workspace) / name)
        final = "" if task == self.empty_handoff else f"Actual output from {task}: implemented and checked assigned task."
        (evidence / "final.txt").write_text(final, encoding="utf-8")
        (evidence / "dispatch.txt").write_text(prompt, encoding="utf-8")
        return dict(status="success", stop_reason="terminal_output", final_response=final,
                    metrics={}, authority_violations=0)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="a001-flow-")
        self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name)
        self.run = prepare(self.root / "runs")

    def execute(self, sessions, through="T06", assessor=assess):
        with contextlib.redirect_stdout(io.StringIO()):
            return run_worker_chain(self.run, sessions, through=through,
                                    allow_host_execution=True, assessor=assessor)

    def test_diagnostics_separate_transport_output_limits_and_implementation(self):
        from localbench.assistant001.campaign import classify_worker_failure
        cases = [
            ({"status": "protocol_failure", "stop_reason": "tool_transport_incompatible"},
             "tool_transport_incompatible"),
            ({"status": "protocol_failure", "stop_reason": "runtime_or_interface_failure"},
             "tool_protocol_or_transport_failure"),
            ({"status": "resource_limit", "stop_reason": "output_token_limit"}, "output_limit"),
            ({"status": "blocked", "stop_reason": "unauthorized_role_setup_tool_call"},
             "setup_tool_boundary_violation"),
            ({"status": "success", "final_response": "Done"}, "implementation_acceptance_failure"),
        ]
        for source, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(classify_worker_failure(source, {"passed": False}), expected)
        self.assertIsNone(classify_worker_failure(
            {"status": "success", "final_response": "Done"}, {"passed": True}))

    def test_failed_impl_remains_failed_with_independent_diagnostic(self):
        sessions = FakeSessions(self.root, fail_task="T01")
        row = self.execute(sessions, "T01")["results"][0]
        self.assertEqual(row["failure_attribution"], "implementation_acceptance_failure")
        self.assertFalse(row["deterministic_passed"])

    def test_six_stages_use_actual_workspace_and_predecessor_prose(self):
        sessions = FakeSessions(self.root)
        result = self.execute(sessions)
        self.assertTrue(result["passed"], json.dumps(result, indent=2))
        self.assertEqual(len(sessions.calls), 6)
        self.assertTrue(all(call["workspace"] == self.run / "workspace" for call in sessions.calls))
        for previous, call in zip(sessions.calls, sessions.calls[1:]):
            self.assertIn(f"Actual output from {previous['task']}", call["prompt"])
        self.assertEqual(result["guided_repairs"], 0)
        self.assertEqual(result["qualification_status"], "human-review-pending")
        self.assertTrue((self.run / "roles/worker/T06/handoff-link.json").is_file())

    def test_failed_task_blocks_successors_without_gold_continuation(self):
        sessions = FakeSessions(self.root, fail_task="T02")
        result = self.execute(sessions)
        self.assertFalse(result["passed"])
        self.assertEqual([call["task"] for call in sessions.calls], ["T01", "T02"])
        self.assertEqual(result["completed_cases"], 2)
        self.assertTrue(all(row["stop_reason"] == "predecessor_not_accepted" for row in result["results"][2:]))
        self.assertIn("NotImplementedError", (self.run / "workspace/assistant_journal/journal.py").read_text())

    def test_empty_handoff_is_not_an_accepted_predecessor(self):
        sessions = FakeSessions(self.root, empty_handoff="T01")
        result = self.execute(sessions, "T02")
        self.assertFalse(result["passed"])
        self.assertEqual(len(sessions.calls), 1)
        self.assertFalse(result["results"][0]["handoff_present"])

    def test_engine_failure_preserves_partial_summary(self):
        def broken(**kwargs):
            raise OSError("synthetic engine failure")
        result = self.execute(broken, "T02")
        self.assertEqual(result["results"][0]["status"], "error")
        self.assertEqual(result["results"][1]["status"], "blocked")
        self.assertTrue((self.run / "summary.json").is_file())

    def test_handoff_checkpoint_failure_cannot_be_reported_as_success(self):
        from localbench.assistant001.packet import write_json as real_write
        sessions = FakeSessions(self.root)
        def fail_link(path, value):
            if Path(path).name == "handoff-link.json":
                raise OSError("synthetic evidence write failure")
            real_write(path, value)
        with patch("localbench.assistant001.campaign.write_json", side_effect=fail_link):
            result = self.execute(sessions, "T01")
        self.assertFalse(result["passed"])
        self.assertFalse(result["results"][0]["deterministic_passed"])
        self.assertEqual(result["results"][0]["status"], "error")
        self.assertTrue((self.run / "summary.json").is_file())

    def test_no_resume_overwrite_or_automatic_repair(self):
        sessions = FakeSessions(self.root)
        self.execute(sessions, "T01")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            self.execute(sessions, "T01")
        self.assertEqual(len(sessions.calls), 1)

    def test_probe_is_advisory_and_keeps_source_unchanged(self):
        sessions = FakeSessions(self.root)
        target = prepare(self.root / "probes")
        before = snapshot(self.run / "workspace")
        summary = run_probe(target, self.run, sessions, role="planner")
        self.assertEqual(snapshot(self.run / "workspace"), before)
        self.assertIsNone(summary["results"][0]["deterministic_passed"])
        self.assertEqual(summary["track"], "advisory-role-probe")
        self.assertIsNone(sessions.calls[0]["workspace"])

    def test_governor_without_canonical_docs_or_plan_is_blocked(self):
        with self.assertRaisesRegex(ValueError, "canonical"):
            role_prompt("governor", self.run)
        target = prepare(self.root / "probes")
        with self.assertRaisesRegex(ValueError, "actual --plan-file"):
            run_probe(target, self.run, FakeSessions(self.root), role="governor")

    def test_tester_requires_acknowledgement_and_cannot_touch_source(self):
        target = prepare(self.root / "probes")
        with self.assertRaisesRegex(ValueError, "host-execution"):
            run_probe(target, self.run, FakeSessions(self.root), role="tester")

    def test_probe_refuses_target_equal_to_source(self):
        with self.assertRaises(ValueError):
            run_probe(self.run, self.run, FakeSessions(self.root), role="reviewer")


if __name__ == "__main__":
    unittest.main()
