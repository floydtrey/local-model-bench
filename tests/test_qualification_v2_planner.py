"""Blind input, real role-engine wiring and human review regressions; no inference."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from localbench.qualification_v2.planner_packet import build_packet, prepare, verify_run, read_regular, PACKETS, sha
from localbench.qualification_v2.planner import run_planner, assess_run
from localbench.qualification_v2.planner_assessment import assess, draft_review, validate_review
from localbench.qualification_v2.planner_calibration import calibrate
from localbench.qualification_v2.__main__ import main

ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "docs/qualification-v2/planner-calibration"


def fixture(project="assistant-001", name="alternate-three"):
    text = (CAL / project / (name + ".txt")).read_text(encoding="utf-8")
    review = json.loads((CAL / project / (name + ".json")).read_text(encoding="utf-8"))
    return text, review


class BlindPlannerTests(unittest.TestCase):
    def test_historical_scaffolded_planner_remains_a_separate_unchanged_probe(self):
        from localbench.assistant001 import packet as a001
        from localbench.assistant002 import packet as a002
        from localbench.assistant001.campaign import role_prompt
        for api in (a001, a002):
            with tempfile.TemporaryDirectory() as folder:
                run = api.prepare(Path(folder), repo=ROOT)
                prompt = role_prompt("planner", run, repo=ROOT, packet_api=api)
                self.assertIn("TASKS.md", prompt)
                self.assertIn("fixed task sequence is a comparison reference", prompt)
                self.assertIn((api.packet_root(ROOT) / "TASKS.md").read_text(encoding="utf-8"), prompt)
                self.assertTrue((run / "workspace/TASKS.md").is_file())

    def test_all_candidate_surfaces_are_stable_explicit_and_free_of_scaffolding(self):
        for project in PACKETS:
            for case in ("complete", "missing-goal"):
                with self.subTest(project=project, case=case), tempfile.TemporaryDirectory() as folder:
                    first = prepare(project, Path(folder), case=case, repo=ROOT)
                    second = prepare(project, Path(folder), case=case, repo=ROOT)
                    packet = verify_run(first, ROOT)
                    self.assertEqual(packet, verify_run(second, ROOT))
                    # Candidate-visible metadata is the explicit filenames and contents only.
                    surface = packet["prompt"] + json.dumps(packet["file_sha256"])
                    for forbidden in ("TASKS.md", "REFERENCE_PLAN", "TRACEABILITY", "assessor/", "UPSTREAM.json", "T01", "T06", "OWNER_REVIEW_PENDING"):
                        self.assertNotIn(forbidden, surface)
                    self.assertNotIn(str(ROOT), surface)
                    self.assertNotIn("PLANNER_PACKET", surface)
                    self.assertEqual(set(packet["files"]), set(packet["file_sha256"]))
                    self.assertEqual(packet["input_sha256"], sha(packet["prompt"].encode()))
                    if project == "assistant-002":
                        self.assertIn("assistant_simulator/event_contract.py", packet["files"])
                        self.assertFalse(any("assistant_journal/" in x for x in packet["files"]))

    def test_all_unmodified_behavior_and_public_interfaces_are_preserved(self):
        for project in PACKETS:
            packet = build_packet(project, repo=ROOT)
            base = ROOT / "project-benchmarks" / project
            spec = json.loads((base / "qualification-v2/PLANNER_PACKET.json").read_text())
            for name, source in spec["lineage"].items():
                self.assertEqual(sha((ROOT / source["source"]).read_bytes()), source["source_sha256"])
            # Entire helper, including inert payload handling, must remain byte-identical.
            if project == "assistant-002":
                self.assertEqual(packet["files"]["assistant_simulator/event_contract.py"].encode(),
                                 (base / "v1/starter/assistant_simulator/event_contract.py").read_bytes())
            for suffix in ("__init__.py", "__main__.py"):
                name = ("assistant_journal/" if project == "assistant-001" else "assistant_simulator/") + suffix
                import ast
                self.assertEqual(ast.dump(ast.parse(packet["files"][name])).replace("complete the implementation", "complete assigned stages"),
                                 ast.dump(ast.parse((base / "v1/starter" / name).read_text())))

    def test_packet_and_rehashed_metadata_mutation_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            clone = Path(folder)
            shutil.copytree(ROOT / "docs/qualification-v2", clone / "docs/qualification-v2")
            shutil.copytree(ROOT / "project-benchmarks/assistant-001", clone / "project-benchmarks/assistant-001")
            base = clone / "project-benchmarks/assistant-001/qualification-v2"
            readme = base / "planner-input-v1/README.md"
            readme.write_text("Leaked solved plan", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "integrity"):
                build_packet("assistant-001", repo=clone)
            spec_path = base / "PLANNER_PACKET.json"
            spec = json.loads(spec_path.read_text())
            spec["files"]["README.md"] = sha(readme.read_bytes())
            spec_path.write_text(json.dumps(spec))
            with self.assertRaisesRegex(ValueError, "metadata changed"):
                build_packet("assistant-001", repo=clone)

    def test_workspace_injection_prompt_and_metadata_tamper_prevent_dispatch(self):
        for attack in ("extra", "modify", "prompt", "metadata"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as folder:
                run = prepare("assistant-001", Path(folder), repo=ROOT)
                if attack == "extra":
                    (run / "workspace/TASKS.md").write_text("SECRET")
                elif attack == "modify":
                    (run / "workspace/README.md").write_text("SECRET")
                elif attack == "prompt":
                    (run / "prompt.txt").write_text("SECRET")
                else:
                    record = json.loads((run / "run.json").read_text())
                    record["files"] = {"TASKS.md": "SECRET"}
                    (run / "run.json").write_text(json.dumps(record))
                session = Mock()
                with self.assertRaises(ValueError):
                    run_planner(run, session, repo=ROOT)
                session.assert_not_called()

    def test_symlink_files_and_ancestor_routes_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            actual = base / "actual"; actual.mkdir()
            (actual / "file").write_text("secret")
            link = base / "linked"
            try:
                link.symlink_to(actual, target_is_directory=True)
            except OSError:
                self.skipTest("Host does not permit symlinks; junction check runs separately on Windows")
            with self.assertRaises(ValueError):
                read_regular(link / "file")

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_windows_junction_ancestor_is_rejected(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            actual = base / "actual"; actual.mkdir()
            (actual / "file").write_text("secret")
            link = base / "linked"
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(actual)], check=True, capture_output=True)
            with self.assertRaises(ValueError):
                read_regular(link / "file")
            link.rmdir()  # Remove junction itself, never recurse into its target.

    def test_existing_ollama_sessions_offer_no_tools_and_deny_unsolicited_calls(self):
        from localbench.assistant001.runtime import OllamaSessions
        from localbench.v2.tool_harness import ModelTurnResponse, ToolCall
        requests = []
        effective = SimpleNamespace(reference=SimpleNamespace(to_dict=lambda: {"fixture": "sealed"}))
        def driver(request):
            requests.append(request)
            if len(request.messages) == 1:
                return ModelTurnResponse(content="Ready")
            if not any(m.get("role") == "tool" for m in request.messages):
                return ModelTurnResponse(tool_calls=tuple(ToolCall(str(i), name, args) for i, (name, args) in enumerate([
                    ("list_files", {}), ("read_file", {"path": "../REFERENCE_PLAN.md"}),
                    ("read_file", {"path": str(ROOT / 'project-benchmarks/assistant-001/v1/TASKS.md')}),
                    ("write_file", {"path": "output.py", "content": "pass"}), ("run_tests", {})])))
            return ModelTurnResponse(content="Free-form candidate plan, no enforced schema.")
        with tempfile.TemporaryDirectory() as folder, \
             patch("urllib.request.urlopen", side_effect=AssertionError("No network")), \
             patch("localbench.v2.flashnext_role_harness.run_python_check", side_effect=AssertionError("No host execution")), \
             patch("localbench.v2.ollama_role_campaign.build_foundation", return_value=({"runtime": "fixture", "model": "fixture"}, {"capabilities": ["tools"]})), \
             patch("localbench.v2.orchestrator.EvidenceStore", return_value=Mock()), \
             patch("localbench.v2.ollama_driver.ollama_adapter_resolution", return_value={}), \
             patch("localbench.v2.configuration.resolve_effective_configuration", return_value=effective), \
             patch("localbench.v2.ollama_driver.OllamaChatDriver", return_value=driver):
            runs = [prepare(p, Path(folder), repo=ROOT) for p in PACKETS]
            # Even reuse of the session factory must not reuse conversation history.
            sessions = OllamaSessions(ROOT, runs[0], "fixture")
            for run in runs:
                result = run_planner(run, sessions, repo=ROOT)
                self.assertEqual(result["authority_violations"], 5)
                self.assertEqual(result["test_tool_calls"], 0)
                with self.assertRaises(ValueError):
                    run_planner(run, sessions, repo=ROOT)
            self.assertEqual(sum(len(r.messages) == 1 for r in requests), 2)
            self.assertTrue(all(not r.tools and not r.context_assets for r in requests))
            for request in requests:
                for message in request.messages:
                    if message["role"] == "tool":
                        self.assertEqual("authorization_denied", message["result"]["error"])
                        self.assertEqual("tool_not_exposed", message["result"]["reason"])

    def test_cli_requires_consent_before_touching_ollama(self):
        with tempfile.TemporaryDirectory() as folder, patch("localbench.assistant001.runtime.OllamaSessions") as sessions:
            run = prepare("assistant-001", Path(folder), repo=ROOT)
            self.assertEqual(main(["run", "--run-dir", str(run), "--model", "fixture"]), 2)
            sessions.assert_not_called()


class PlannerReviewTests(unittest.TestCase):
    def test_corrected_controls_ground_tasks_in_outcomes_and_scopes(self):
        for project in PACKETS:
            for name in ("alternate-three", "alternate-eight"):
                text, review = fixture(project, name)
                self.assertEqual(review["verdict"], "PASS")
                if project == "assistant-001":
                    self.assertNotIn("supplied helper", text)
                for row in review["requirements"]:
                    self.assertTrue(any("Scope:" in e["quote"] and "Gate:" in e["quote"] for e in row["evidence"]))
                mapped = {tuple(e["quote"] for e in row["evidence"]) for row in review["dimensions"]}
                self.assertGreater(len(mapped), 4)  # The former repeated intro gave all dimensions one citation.
            _, omission = fixture(project, "critical-omission")
            self.assertTrue(any(r["status"] == "missing" and r["severity"] == "critical" for r in omission["requirements"]))

    def test_calibration_different_decompositions_failures_blockers_and_historical_inventory(self):
        result = calibrate(ROOT)
        self.assertEqual(len(result["fixtures"]), 10)
        self.assertEqual(len(result["historical_planner_case_ids"]), 6)
        self.assertEqual(result["semantic_calibration_status"], "HUMAN_REVIEW_PENDING")

    def test_text_labels_and_nonempty_output_never_auto_pass(self):
        for project in PACKETS:
            packet = build_packet(project, repo=ROOT)
            for text in ("", "PASS R01 R02 R03 R04 R05 R06 S01 S02 S03 S04 S05 S06", "BLOCKED", fixture(project)[0]):
                result = assess(packet, text, repo=ROOT)
                self.assertEqual(result["assessed_outcome"], "NOT_ASSESSED")
                self.assertIsNone(result["human_adjudication"])
                self.assertFalse(result["qualified_role_assignment"])

    def test_case_output_rubric_binding_and_evidence_tampering_fail(self):
        text, original = fixture()
        original["review_origin"] = "human_declared"  # synthetic declaration only within this unit test
        packet = build_packet("assistant-001", repo=ROOT)
        for mutate in (
            lambda r: r.update(case_id="assistant-002-planner-v2-complete"),
            lambda r: r.update(candidate_sha256="0" * 64),
            lambda r: r.update(input_sha256="0" * 64),
            lambda r: r.update(rubric_sha256="0" * 64),
            lambda r: r.update(reviewer=""),
            lambda r: r.update(reviewed_at="not-a-date"),
            lambda r: r["requirements"].pop(),
            lambda r: r["requirements"][0]["evidence"][0].update(quote="Invented quote"),
            lambda r: r["dimensions"][0].update(status="missing", severity="critical"),
        ):
            changed = copy.deepcopy(original); mutate(changed)
            with self.assertRaises(ValueError):
                validate_review(changed, packet, text, execution_status="success", repo=ROOT)
        for status, violations in (("error", 0), ("success", 1), ("blocked", 0)):
            with self.assertRaises(ValueError):
                validate_review(original, packet, text, execution_status=status, authority_violations=violations, repo=ROOT)

    def test_calibration_annotations_cannot_be_submitted_as_human_reviews(self):
        text, review = fixture()
        with self.assertRaisesRegex(ValueError, "origin"):
            assess(build_packet("assistant-001", repo=ROOT), text, review=review, repo=ROOT)

    def test_blocker_requires_missing_goal_and_no_actionable_tasks(self):
        text, review = fixture(name="correct-blocked")
        packet = build_packet("assistant-001", "missing-goal", ROOT)
        review["review_origin"] = "human_declared"
        self.assertEqual(assess(packet, text, review=review, repo=ROOT)["assessed_outcome"], "BLOCKED")
        review["blocker"]["no_actionable_tasks"] = False
        with self.assertRaises(ValueError):
            assess(packet, text, review=review, repo=ROOT)
        with self.assertRaises(ValueError):
            assess(build_packet("assistant-001", repo=ROOT), text, review=review, repo=ROOT)

    def test_existing_writer_keeps_execution_diagnostics_adjudication_and_imports_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            run = prepare("assistant-001", Path(folder), repo=ROOT)
            text, review = fixture()
            plan = Path(folder) / "plan.txt"; plan.write_bytes(text.encode())
            target, result = assess_run(run, plan_file=plan, repo=ROOT)
            self.assertEqual(result["execution_status"], "imported")
            self.assertEqual(result["assessed_outcome"], "NOT_ASSESSED")
            self.assertEqual(result["case_count"], 1)
            package = json.loads((target / "review/review-package.json").read_text())
            row = package["case_results"][0]
            self.assertIsNone(row["deterministic_passed"])
            self.assertFalse(row["comparison_eligible"])
            self.assertEqual(Path(row["assessment_file"]), target / "assessment.json")
            self.assertEqual(package["role_summary"][0]["deterministic_evaluated"], 0)
            with (target / "review/case-results.csv").open(encoding="utf-8", newline="") as stream:
                self.assertEqual(next(csv.DictReader(stream))["assessed_outcome"], "NOT_ASSESSED")
            review["review_origin"] = "human_declared"
            path = Path(folder) / "review.json"; path.write_text(json.dumps(review))
            second, result = assess_run(run, plan_file=plan, review_file=path, repo=ROOT)
            self.assertNotEqual(target, second)
            self.assertEqual(result["assessed_outcome"], "PASS")
            self.assertFalse(result["review_identity_verified"])
            self.assertFalse(result["project_execution_authorized"])
            self.assertTrue((target / "review-template.json").exists())

    def test_failed_sessions_retain_evidence_without_substantive_failure_invention(self):
        with tempfile.TemporaryDirectory() as folder:
            run = prepare("assistant-001", Path(folder), repo=ROOT)
            run_planner(run, Mock(side_effect=TimeoutError("fixture failure")), repo=ROOT)
            _, assessment = assess_run(run, repo=ROOT)
            self.assertEqual(assessment["execution_status"], "error")
            self.assertEqual(assessment["assessed_outcome"], "NOT_ASSESSED")
            self.assertFalse(assessment["diagnostic_passed"])


if __name__ == "__main__":
    unittest.main()
