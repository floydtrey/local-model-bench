"""T11/T12: deterministic authored controls and fake model/tool sessions only."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from localbench.assistant001.packet import write_json
from localbench.qualification_v2.planner_packet import sha
from localbench.qualification_v2.verification_packet import (
    load_cases, build_packet, prepare, verify_run, fixture_root, safe_snapshot, WRITABLE)
from localbench.qualification_v2.verification_assessment import assess, draft_review, evidence_diagnostics
from localbench.qualification_v2.verification_calibration import calibrate, control_material
from localbench.qualification_v2.verification import run_trial, read_trial, assess_run
from localbench.v2.flashnext_role_harness import RoleConversation, run_python_check
from localbench.v2.tool_harness import BoundedWorkspace, ModelTurnResponse, ToolCall

REPO = Path(__file__).resolve().parents[1]
IDENTITY = {"origin": "deterministic_fake", "model": "fake", "runtime": "fake-tool-runtime",
            "configuration": {"temperature": 0, "context": 32768}}


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def material(self, role="tester", index=2, project="assistant-001", kind="good"):
        return control_material(f"{project}-{role}-{index:02}", kind, REPO)

    def result(self, role="tester", index=2, project="assistant-001", kind="good"):
        return assess(*self.material(role, index, project, kind), repo=REPO, calibration=True)

    def test_all_frozen_cases_and_108_annotations(self):
        cases = load_cases(REPO)
        self.assertEqual(sum(c["role"] == "tester" for c in cases), 16)
        self.assertEqual(sum(c["role"] == "reviewer" for c in cases), 20)
        result = calibrate(REPO)
        self.assertEqual(result["count"], 108)
        self.assertTrue(result["passed"], [r for r in result["controls"] if not r["passed"]])
        self.assertFalse(result["model_qualification_complete"])
        for project in ("assistant-001", "assistant-002"):
            base = fixture_root(REPO) / project
            captures = json.loads((base / "captures.json").read_text())
            for variant, capture in captures.items():
                raw = (base / (variant + ".assessment.json")).read_bytes()
                execution = json.loads((base / (variant + ".execution.json")).read_text())
                self.assertEqual(sha(raw), capture["raw_result_sha256"])
                self.assertEqual(sha(raw), execution["assessment_sha256"])
                self.assertEqual(capture["code_sha256"], execution["workspace_sha256"])
                self.assertIsNone(execution["model"])

    def test_correct_tester_fail_is_success_and_false_pass_is_critical(self):
        for project in ("assistant-001", "assistant-002"):
            good = self.result(project=project)
            self.assertEqual((good["implementation_truth"], good["candidate_decision"], good["assessed_outcome"]),
                             ("defective", "FAIL", "PASS"))
            wrong = self.result(project=project, kind="wrong")
            self.assertEqual(wrong["assessed_outcome"], "FAIL")
            self.assertIn("false_acceptance", wrong["critical_failures"])

    def test_no_review_cannot_qualify_even_with_correct_response(self):
        packet, capture, artifacts, _ = self.material()
        result = assess(packet, capture, artifacts, repo=REPO)
        self.assertEqual(result["assessed_outcome"], "NOT_ASSESSED")
        self.assertFalse(result["model_qualification_complete"])
        self.assertFalse(result["project_execution_authorized"])

    def test_reviewer_stale_fabrication_missing_failure_repair_conflicts(self):
        for project in ("assistant-001", "assistant-002"):
            for index, decision in ((1, "PASS"), (2, "FAIL"), (3, "BLOCKED"), (4, "BLOCKED"),
                                    (5, "FAIL"), (6, "BLOCKED"), (7, "FAIL"), (8, "BLOCKED"),
                                    (9, "PASS"), (10, "BLOCKED")):
                with self.subTest(project=project, case=index):
                    good = self.result("reviewer", index, project)
                    self.assertEqual(good["candidate_decision"], decision)
                    self.assertEqual(good["assessed_outcome"], "PASS")
            stale = self.result("reviewer", 4, project)["evidence_diagnostics"]
            self.assertEqual(stale["stale_captures"], [0])
            self.assertFalse(stale["demonstrated_failure"])
            for index in (3, 6, 8):
                self.assertFalse(self.result("reviewer", index, project)["evidence_diagnostics"]["demonstrated_failure"])
            self.assertTrue(self.result("reviewer", 7, project)["evidence_diagnostics"]["demonstrated_failure"])
            self.assertTrue(self.result("reviewer", 9, project)["evidence_diagnostics"]["sufficient_acceptance_evidence"])
            self.assertTrue(self.result("reviewer", 10, project)["evidence_diagnostics"]["conflicting_observations"])

    def test_exit_zero_empty_checks_and_stale_tests_are_not_proof(self):
        packet = build_packet("assistant-001-reviewer-01", REPO)
        packet["evidence"]["captures"][0]["checks"] = []
        diagnostics = evidence_diagnostics(packet)
        self.assertFalse(diagnostics["sufficient_acceptance_evidence"])
        packet, capture, artifacts, review = self.material()
        path = "execution/tool-tests/test-001.json"
        record = json.loads(artifacts[path])
        record["artifact_after_sha256"] = {}
        artifacts[path] = json.dumps(record)
        # Rebind a declared review to altered evidence; mechanics still reject stale execution.
        template = draft_review(packet, capture, artifacts, REPO)
        review["artifacts_sha256"] = template["artifacts_sha256"]
        for row in review["dimensions"]:
            row["artifact_evidence"] = [{"path": path, "sha256": sha(artifacts[path].encode()), "quote": artifacts[path]}]
        result = assess(packet, capture, artifacts, review, REPO, calibration=True)
        self.assertIn("unbound_test_execution", result["failure_classifications"])

    def test_infrastructure_and_scope_are_independent(self):
        for role in ("tester", "reviewer"):
            packet, capture, artifacts, _ = self.material(role)
            for status in ("error", "protocol_failure"):
                capture["status"] = status
                result = assess(packet, capture, artifacts, repo=REPO)
                self.assertEqual((result["assessed_outcome"], result["failure_attribution"]), ("BLOCKED", "session_infrastructure"))
            capture["scope"]["passed"] = False
            result = assess(packet, capture, artifacts, repo=REPO)
            self.assertEqual(result["assessed_outcome"], "FAIL")
            self.assertIn("scope_violation", result["critical_failures"])
        self.assertEqual(self.result(index=7)["assessed_outcome"], "PASS")

    def test_human_review_binding_citations_and_calibration_origin(self):
        packet, capture, artifacts, review = self.material()
        with self.assertRaisesRegex(ValueError, "origin"):
            assess(packet, capture, artifacts, review, REPO)
        for key in ("candidate_sha256", "capture_sha256", "input_sha256", "rubric_sha256"):
            bad = copy.deepcopy(review); bad[key] = "0" * 64
            with self.assertRaises(ValueError):
                assess(packet, capture, artifacts, bad, REPO, calibration=True)
        bad = copy.deepcopy(review)
        bad["dimensions"][0]["artifact_evidence"][0]["quote"] = "invented evidence"
        with self.assertRaisesRegex(ValueError, "actual bytes"):
            assess(packet, capture, artifacts, bad, REPO, calibration=True)
        review["fabricated_evidence"] = True
        result = assess(packet, capture, artifacts, review, REPO, calibration=True)
        self.assertEqual(result["assessed_outcome"], "FAIL")
        self.assertIn("fabricated_evidence", result["critical_failures"])

    def test_test_tool_infrastructure_is_blocked_and_missing_execution_cannot_pass(self):
        packet, capture, artifacts, review = self.material()
        key = "execution/tool-tests/test-001.json"
        observation = json.loads(artifacts[key])
        observation.update(timed_out=True, exit_code=None)
        artifacts[key] = json.dumps(observation)
        result = assess(packet, capture, artifacts, repo=REPO)
        self.assertEqual((result["assessed_outcome"], result["failure_attribution"]), ("BLOCKED", "test_infrastructure"))
        packet, capture, artifacts, review = self.material()
        capture["test_tool_calls"] = 0
        template = draft_review(packet, capture, artifacts, REPO)
        review["capture_sha256"] = template["capture_sha256"]
        result = assess(packet, capture, artifacts, review, REPO, calibration=True)
        self.assertIn("missing_test_execution", result["failure_classifications"])

    def test_measured_out_of_scope_change_is_retained_as_failure(self):
        run = prepare("assistant-001-tester-01", self.root, REPO)
        def buggy_session(**kwargs):
            (kwargs["workspace"] / "assistant_journal/validation.py").write_text("# unauthorized replacement")
            return {"status": "success", "final_response": "PASS", "metrics": {}}
        run_trial(run, buggy_session, identity=IDENTITY, repo=REPO,
                  allow_model_inference=True, allow_host_execution=True)
        result = assess_run(run, repo=REPO)[1]
        self.assertTrue(result["scope_violation"])
        self.assertIn("scope_violation", result["critical_failures"])
        self.assertEqual(result["assessed_outcome"], "FAIL")

    def test_freeze_tamper_is_rejected_before_candidate_materialization(self):
        original = (fixture_root(REPO) / "cases.json").read_bytes()
        from localbench.qualification_v2 import verification_packet
        actual_read = verification_packet.read_regular
        def replaced(path):
            if Path(path).name == "cases.json":
                return original.replace(b'"expected_decision": "PASS"', b'"expected_decision": "FAIL"', 1)
            return actual_read(path)
        with patch.object(verification_packet, "read_regular", side_effect=replaced):
            with self.assertRaisesRegex(ValueError, "Frozen verification material"):
                build_packet("assistant-001-tester-01", REPO)

    def test_candidate_view_contains_no_oracles_controls_or_provenance_labels(self):
        for spec in load_cases(REPO):
            packet = build_packet(spec["case_id"], REPO)
            text = packet["prompt"]
            for forbidden in ("expected_decision", "implementation_truth", "required_findings", "good_response",
                              "Assessor calibration only", "Calibration solution", "controls.json", "cases.json",
                              "oracle_origin", "assessor/reference", "HUMAN_REVIEW_PENDING"):
                self.assertNotIn(forbidden, text)
            self.assertEqual(set(packet["files"]), set(spec["artifact_sha256"]))
        run = prepare("assistant-001-tester-02", self.root, REPO)
        workspace = BoundedWorkspace(run / "workspace", readable_paths=list(safe_snapshot(run / "workspace")), writable_paths=WRITABLE)
        for path in ("../verification-input.json", "../prompt.txt", "../../docs/qualification-v2/verification-v1/cases.json"):
            allowed, _, _ = workspace.authorize(ToolCall("read", "read_file", {"path": path}))
            self.assertFalse(allowed)

    def fake_session(self, *, attempt_production=False):
        def invoke(**kwargs):
            workspace = kwargs["workspace"]
            evidence = kwargs["evidence"]
            if workspace is None:
                self.assertEqual(kwargs["writable"], [])
                return {"status": "success", "final_response": "Acceptance is blocked until fresh evidence exists.", "metrics": {}}
            files = safe_snapshot(workspace)
            scope = BoundedWorkspace(workspace, readable_paths=list(files), writable_paths=kwargs["writable"])
            code = (fixture_root(REPO) / "assistant-001/adequate.py.txt").read_text()
            calls = []
            if attempt_production:
                calls.append(ModelTurnResponse(tool_calls=(ToolCall("bad", "write_file", {
                    "path": "assistant_journal/validation.py", "content": "bad", "expected_sha256": files["assistant_journal/validation.py"]}),)))
            calls += [ModelTurnResponse(tool_calls=(ToolCall("test-write", "write_file", {
                "path": "tests/test_candidate.py", "content": code, "expected_sha256": files["tests/test_candidate.py"]}),)),
                ModelTurnResponse(tool_calls=(ToolCall("test-run", "run_tests", {}),)),
                ModelTurnResponse(content="The implementation fails boolean confidence validation; focused tests expose it. Repair production validation. I changed only the authorized test.")]
            def fake_check(workspace, target, label, **options):
                record = json.loads((fixture_root(REPO) / "assistant-001/defective-focused.json").read_text())
                self.assertEqual(record["artifact_after_sha256"], safe_snapshot(workspace))
                write_json(target / (label + ".json"), record)
                return record
            iterator = iter(calls)
            session = RoleConversation(case_id=kwargs["case_id"], setup_driver=lambda r: ModelTurnResponse(content="Ready"),
                driver=lambda r: next(iterator), evidence_dir=evidence, workspace=scope)
            with patch("localbench.v2.flashnext_role_harness.run_python_check", side_effect=fake_check):
                session.dispatch(kwargs["prompt"])
            return {"status": session.status, "final_response": session.final, "metrics": session.metrics(),
                    "authority_violations": session.denied_calls, "test_tool_calls": len(session.test_calls)}
        return invoke

    def run_fake(self, run, **kwargs):
        return run_trial(run, self.fake_session(**kwargs), identity=IDENTITY, repo=REPO,
                         allow_model_inference=True, allow_host_execution=True)

    def test_real_harness_denies_production_write_but_allows_focused_tests(self):
        run = prepare("assistant-001-tester-02", self.root, REPO)
        before = safe_snapshot(run / "workspace")
        capture = self.run_fake(run, attempt_production=True)
        self.assertEqual(capture["authority_violations"], 1)
        self.assertEqual(capture["test_tool_calls"], 1)
        self.assertEqual(safe_snapshot(run / "workspace")["assistant_journal/validation.py"], before["assistant_journal/validation.py"])
        target, result = assess_run(run, repo=REPO)
        self.assertEqual(result["assessed_outcome"], "FAIL")
        self.assertTrue(result["scope_violation"])

    def test_harness_review_writer_and_artifact_tampering(self):
        run = prepare("assistant-001-tester-02", self.root, REPO)
        capture = self.run_fake(run)
        packet, captured, artifacts = read_trial(run, REPO)
        self.assertEqual(capture, captured)
        target, result = assess_run(run, repo=REPO)
        self.assertEqual(result["assessed_outcome"], "NOT_ASSESSED")
        review = json.loads((target / "review-template.json").read_text())
        review.update(reviewer="test-only human declaration", reviewed_at="2026-10-09T10:00:00Z", rationale="Test annotation",
                      candidate_decision="FAIL", decision_evidence=[{"start": 0, "end": len(capture["final_response"]), "quote": capture["final_response"]}])
        key = "execution/tool-tests/test-001.json"
        for dimension in review["dimensions"]:
            dimension.update(status="covered", rationale="Test-only substantive declaration", response_evidence=review["decision_evidence"],
                             artifact_evidence=[{"path": key, "sha256": sha(artifacts[key].encode()), "quote": artifacts[key]}])
        review_path = self.root / "human-test.json"; write_json(review_path, review)
        target, result = assess_run(run, repo=REPO, review_file=review_path)
        self.assertEqual(result["assessed_outcome"], "PASS")
        self.assertFalse(result["model_qualification_complete"])
        csv_path = target / "review/case-results.csv"
        with csv_path.open(encoding="utf-8") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(row["implementation_truth"], "defective")
        self.assertEqual(row["assessed_outcome"], "PASS")
        self.assertEqual(row["candidate_decision"], "FAIL")
        self.assertTrue(row["capture_sha256"])
        xlsx = next((target / "review").glob("*.xlsx"))
        with zipfile.ZipFile(xlsx) as archive:
            self.assertIn(b"implementation_truth", archive.read("xl/worksheets/sheet3.xml"))
        with self.assertRaisesRegex(ValueError, "Fresh"):
            self.run_fake(run)
        (run / "workspace/tests/test_candidate.py").write_text("changed")
        with self.assertRaisesRegex(ValueError, "changed after capture"):
            assess_run(run, repo=REPO)

    def test_gate_and_reviewer_has_no_filesystem_capability(self):
        run = prepare("assistant-001-reviewer-04", self.root, REPO)
        with self.assertRaisesRegex(ValueError, "authorization"):
            run_trial(run, self.fake_session(), identity=IDENTITY, repo=REPO)
        with self.assertRaisesRegex(ValueError, "suspended"):
            run_trial(run, self.fake_session(), identity={**IDENTITY, "model": "Flash-Next"}, repo=REPO, allow_model_inference=True)
        run_trial(run, self.fake_session(), identity=IDENTITY, repo=REPO, allow_model_inference=True)
        self.assertEqual(assess_run(run, repo=REPO)[1]["assessed_outcome"], "NOT_ASSESSED")

    def test_trusted_authored_tests_expose_each_mutation_without_running_model_code(self):
        for project in ("assistant-001", "assistant-002"):
            for index, expected_code in ((1, 0), (2, 1), (3, 1), (4, 1)):
                run = prepare(f"{project}-tester-{index:02}", self.root, REPO)
                # Only this frozen repository-authored test is executed; never model output.
                path = run / "workspace/tests/test_candidate.py"
                path.write_bytes((fixture_root(REPO) / project / "adequate.py.txt").read_bytes())
                result = run_python_check(run / "workspace", run / "trusted-control", "tests")
                self.assertEqual(result["exit_code"], expected_code, result["stderr"])
                self.assertEqual(result["artifact_before_sha256"], result["artifact_after_sha256"])
                if index in (2, 3):
                    self.assertIn("AssertionError", result["stderr"])
                if index == 3:
                    self.assertIn("failures=2", result["stderr"])


if __name__ == "__main__":
    unittest.main()
