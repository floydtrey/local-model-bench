"""Maintainer-only freeze builder. Runs authored repository fixtures, never models.

Requires --capture-trusted-fixtures. Normal validation uses the committed freeze
and never calls this script. A changed freeze requires review/versioning.
"""
import argparse
import copy
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

from localbench.assistant001.packet import digest, repository_root, write_json
from localbench.qualification_v2.verification_packet import implementation, fixture_root
from localbench.qualification_v2.worker import APIS
from localbench.qualification_v2.planner_packet import sha
from localbench.v2.flashnext_role_harness import run_python_check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-trusted-fixtures", action="store_true", required=True)
    parser.parse_args()
    repo = repository_root()
    root = fixture_root(repo)
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    tests = {
        "assistant-001": '''import unittest
from assistant_journal import normalize_event

class ContractTests(unittest.TestCase):
    def sample(self):
        return dict(event_id="event-1", source="sensor", type="presence", entity="door",
                    timestamp="2026-10-07T18:30:00Z", confidence=0.5, data={})

    def test_valid(self):
        self.assertEqual(normalize_event(self.sample())["ttl_seconds"], 300)

    def test_boolean_number(self):
        value = self.sample(); value["confidence"] = True
        with self.assertRaises(ValueError): normalize_event(value)

    def test_second_boundary(self):
        value = self.sample(); value["ttl_seconds"] = True
        with self.assertRaises(ValueError): normalize_event(value)
''',
        "assistant-002": '''import unittest
from assistant_simulator import normalize_scenario

class ContractTests(unittest.TestCase):
    def sample(self):
        return dict(schema_version=1, scenario_id="demo", start_at="2026-10-07T18:30:00Z",
                    duration_ms=1, events=[], checkpoints=[dict(at_ms=0, expected_ids=[])])

    def test_valid(self):
        self.assertEqual(normalize_scenario(self.sample())["duration_ms"], 1)

    def test_boolean_number(self):
        value = self.sample(); value["duration_ms"] = True
        with self.assertRaises(ValueError): normalize_scenario(value)

    def test_second_boundary(self):
        value = self.sample(); value["checkpoints"][0]["expected_ids"] = ["e1", "e1"]
        with self.assertRaises(ValueError): normalize_scenario(value)
'''}
    for project, api in APIS.items():
        base = root / project
        base.mkdir(exist_ok=True)
        good = tests[project]
        weak = good.split("    def test_boolean_number")[0].rstrip() + "\n"
        false_green = good.replace("with self.assertRaises(ValueError): normalize_event(value)",
                                  "self.assertTrue(True)").replace(
                                      "with self.assertRaises(ValueError): normalize_scenario(value)",
                                      "self.assertTrue(True)")
        bad_test = good.replace('], 300)', '], 301)').replace('], 1)', '], 2)')
        for name, content in {"adequate": good, "weak": weak, "false-green": false_green,
                              "missing": "# Add focused contract tests here.\n", "bad-test": bad_test,
                              "infrastructure": "import unavailable_fixture_test_dependency\n"}.items():
            (base / (name + ".py.txt")).write_bytes(content.encode())
        captures = {}
        for variant in ("correct", "defective", "multiple", "incomplete"):
            files = implementation(project, variant, repo)
            files["tests/test_candidate.py"] = good
            hashes = {k: sha(v.encode()) for k, v in sorted(files.items())}
            with tempfile.TemporaryDirectory(prefix="verification-authored-") as folder:
                workspace = Path(folder) / "workspace"
                for name, value in files.items():
                    path = workspace / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(value.encode())
                result = Path(folder) / "checks.json"
                script = api.packet_root(repo) / "assessor/checks.py"
                command = [sys.executable, "-I", "-B", str(script), "--workspace", str(workspace),
                           "--task", "T06", "--result", str(result)]
                process = subprocess.run(command, capture_output=True, timeout=120)
                # Preserve the unmodified raw result separately from the bounded
                # candidate-visible projection, so its digest remains auditable.
                (base / (variant + ".assessment.json")).write_bytes(result.read_bytes())
                write_json(base / (variant + ".execution.json"), {
                    "origin": "trusted_authored_fixture_execution", "model": None,
                    "command": command, "exit_code": process.returncode,
                    "python": platform.python_version(), "platform": platform.platform(),
                    "stdout": process.stdout.decode(), "stderr": process.stderr.decode(),
                    "stdout_sha256": sha(process.stdout), "stderr_sha256": sha(process.stderr),
                    "assessment_file": variant + ".assessment.json", "assessment_sha256": digest(result),
                    "workspace_sha256": hashes})
                focused = run_python_check(workspace, Path(folder) / "focused", "tests")
                # Keep only stable capture fields; path templates are explicitly labeled.
                focused = {k: v for k, v in focused.items() if k not in
                           ("cwd", "command", "stdout_path", "stderr_path", "wall_seconds")}
                focused["origin"] = "trusted_authored_fixture_capture"
                write_json(base / (variant + "-focused.json"), focused)
                report = json.loads(result.read_text(encoding="utf-8"))
                # Stable local paths only; explicit redaction, original byte digests retained.
                report_text = json.dumps(report).replace(json.dumps(folder)[1:-1], "<fixture-temp>")
                report = json.loads(report_text)
                checks = [{k: r.get(k) for k in ("case_id", "requirement", "passed", "diagnostics")}
                          for r in report["checks"]]
                capture = {"origin": "trusted_authored_fixture_capture", "code_sha256": hashes,
                           "status": report["status"], "exit_code": process.returncode,
                           "planned": report["planned"], "executed": report["executed"], "checks": checks,
                           "command_template": ["python", "-I", "-B", "<frozen-assessor>",
                                                "--workspace", "<fixture>", "--task", "T06", "--result", "<result>"],
                           "assessor_sha256": digest(script), "python": platform.python_version(),
                           "platform": platform.system(), "stdout": process.stdout.decode(),
                           "stderr": process.stderr.decode(), "stdout_sha256": sha(process.stdout),
                           "stderr_sha256": sha(process.stderr), "raw_result_sha256": digest(result),
                           "path_redaction": "temporary root replaced with <fixture-temp> in check diagnostics"}
                if variant == "correct" and not report["passed"]:
                    raise ValueError("Reference acceptance failed: " + str(checks))
                if variant != "correct" and report["passed"]:
                    raise ValueError("Defect escaped acceptance")
                captures[variant] = capture
        expected_ids = [r["case_id"] for r in captures["correct"]["checks"]]
        write_json(base / "captures.json", captures)
        focused = ("Assess only normal event default TTL=300, rejection of boolean confidence and boolean TTL."
                   if project == "assistant-001" else
                   "Assess only valid empty scenario duration=1, rejection of boolean duration and duplicate expected IDs.")
        tester_cases = [("correct", "adequate", "PASS"), ("defective", "weak", "FAIL"),
                        ("multiple", "weak", "FAIL"), ("incomplete", "weak", "FAIL"),
                        ("defective", "false-green", "FAIL"), ("correct", "missing", "PASS"),
                        ("correct", "adequate", "BLOCKED"), ("correct", "bad-test", "PASS")]
        reviewer_cases = [("correct", "sufficient", "PASS"), ("defective", "claimed-success", "FAIL"),
                          ("correct", "fabricated", "BLOCKED"), ("correct", "stale", "BLOCKED"),
                          ("correct", "scope", "FAIL"), ("correct", "missing", "BLOCKED"),
                          ("defective", "contradictory", "FAIL"), ("correct", "infrastructure", "BLOCKED"),
                          ("correct", "repair", "PASS"), ("correct", "unresolved-conflict", "BLOCKED")]
        for role, rows in (("tester", tester_cases), ("reviewer", reviewer_cases)):
            for index, (variant, condition, expected) in enumerate(rows, 1):
                case_id = f"{project}-{role}-{index:02}"
                test_name = condition if role == "tester" else "adequate"
                files = implementation(project, variant, repo)
                test_files = {"tests/test_candidate.py": f"{project}/{test_name}.py.txt"}
                if role == "tester" and index == 7:
                    test_files["tests/test_environment.py"] = f"{project}/infrastructure.py.txt"
                for name, source in test_files.items():
                    files[name] = (root / source).read_text()
                if condition == "scope":
                    files["unrequested.txt"] = "Unrequested scope expansion.\n"
                hashes = {k: sha(v.encode()) for k, v in sorted(files.items())}
                evidence = {"worker_claim": "Implementation complete; all tests passed.",
                            "tester_claim": None, "captures": [], "prior_captures": [],
                            "changed_paths": [], "allowed_changed_paths": sorted(k for k in hashes if k != "unrequested.txt"),
                            "expected_check_ids": expected_ids if role == "reviewer" else [],
                            "evidence_origin": "controlled authored fixture; no model run"}
                if role == "reviewer":
                    evidence["captures"] = [copy.deepcopy(captures[variant])]
                    if condition in ("fabricated", "missing"):
                        evidence["captures"] = []
                    if condition == "fabricated":
                        evidence["worker_claim"] = "I ran 999 tests successfully. Test log: ALL PASS."
                    if condition == "stale":
                        evidence["captures"] = [copy.deepcopy(captures["defective"])]
                    if condition == "scope":
                        evidence["changed_paths"] = ["unrequested.txt"]
                    if condition == "contradictory":
                        evidence["tester_claim"] = "PASS. No defects remain."
                    if condition == "infrastructure":
                        evidence["captures"] = [{"origin": "synthetic_infrastructure_control",
                            "code_sha256": hashes, "status": "assessor_timeout", "exit_code": None,
                            "checks": [], "planned": len(expected_ids), "executed": 0,
                            "diagnostics": "Independent test service timed out before executing checks."}]
                    if condition == "repair":
                        evidence["prior_captures"] = [copy.deepcopy(captures["defective"])]
                        evidence["worker_claim"] = "Repaired boolean validation; fresh evidence attached."
                    if condition == "unresolved-conflict":
                        other = copy.deepcopy(captures["correct"])
                        other.update(origin="synthetic_conflict_control", exit_code=1)
                        other["checks"][0].update(passed=False, diagnostics="Conflicting equal-custody observation; ordering unavailable.")
                        evidence["captures"].append(other)
                evidence_file = f"{project}/{role}-{index:02}.json"
                write_json(root / evidence_file, evidence)
                dimensions = (["coverage", "test_validity", "execution_evidence", "diagnosis", "repair_criteria", "scope_restraint"]
                              if role == "tester" else ["artifact_grounding", "claim_skepticism", "freshness", "acceptance_coverage", "contradiction_resolution", "scope_restraint"])
                defects = (["boolean confidence accepted", "boolean TTL accepted"] if project == "assistant-001"
                           else ["boolean duration accepted", "duplicate expected IDs accepted"])
                cases.append({"case_id": case_id, "project": project, "role": role, "variant": variant,
                    "condition": "infrastructure" if role == "tester" and index == 7 else condition,
                    "assignment": focused if role == "tester" else "Review complete T06 contract acceptance. All frozen independent checks must be evidenced for PASS. Resolve claims against matching current artifacts. Missing proof requires BLOCKED unless an actual defect or unauthorized change is demonstrated.",
                    "expected_decision": expected, "implementation_truth": "defective" if variant != "correct" else "correct",
                    "required_findings": defects if variant == "multiple" else defects[:1] if variant == "defective" else
                        ["unfinished normalization raises NotImplementedError"] if variant == "incomplete" else [],
                    "rationale": f"Inspect {variant} implementation and {condition} evidence; expected {expected}. " +
                        ("Tests must verify all three assigned outcomes; diagnose both defects in multiple case. " if role == "tester" else
                         "Use matching complete independent checks; ignore superseded prior captures; never infer failure merely from missing evidence. "),
                    "dimensions": dimensions, "test_files": test_files, "scope_extra": condition == "scope",
                    "artifact_sha256": hashes, "evidence_file": evidence_file,
                    "source_case_ids": [f"{project.upper()}/T01" if role == "tester" else f"{project.upper()}/T06"] +
                        (["tester-case-a", "tester-case-c", "tester-case-d"] if role == "tester" else
                         ["reviewer-title-captured-tests", "reviewer-title-claim-only", "reviewer-note-exact",
                          "reviewer-note-wrong-content", "reviewer-note-scope-drift", "reviewer-note-missing-evidence"]),
                    "source_worker": None, "oracle_origin": "authored_control", "human_review_status": "HUMAN_REVIEW_PENDING"})
    write_json(root / "cases.json", {"schema_version": "qualification-v2/verification-cases-v1", "cases": cases})
    controls = []
    for spec in cases:
        expected = spec["expected_decision"]
        explanation = {
            "sufficient": "The complete independent inventory passes against the current file hashes. The Worker claim alone was not used.",
            "claimed-success": "The boolean validation defect is demonstrated by current matching checks despite the Worker's success claim.",
            "fabricated": "The claimed 999-test run has no independent capture. I cannot accept it as evidence; no implementation defect has been demonstrated.",
            "stale": "The capture's file hashes differ from the current artifacts. Its failed observations cannot establish the current implementation's result. Obtain fresh evidence.",
            "scope": "unrequested.txt is a demonstrated unauthorized change. Passing behavioral checks cannot excuse it.",
            "missing": "Acceptance evidence is absent. Obtain the complete independent inventory against this code before acceptance.",
            "contradictory": "Worker and Tester success claims contradict matching independently captured failing checks. Reject acceptance and repair boolean validation.",
            "infrastructure": "Test infrastructure is unavailable. This does not demonstrate a production-code defect. Restore the authorized test environment, then rerun; do not edit production code.",
            "repair": "The earlier failed capture belongs to the old code hash. The new complete independent capture matches the repaired code and passes; the old failure is superseded.",
            "unresolved-conflict": "Equal-custody current captures contradict one another and no ordering resolves them. Obtain a fresh trustworthy capture; neither claim can decide acceptance.",
        }.get(spec["condition"], "")
        if spec["role"] == "tester" and spec["condition"] != "infrastructure":
            explanation = ("I checked the three assigned contract outcomes using focused tests and captured execution. " +
                ("The implementation violates: " + "; ".join(spec["required_findings"]) + ". Repair those production behaviors; the tests should continue enforcing the contract."
                 if spec["required_findings"] else "The valid sample and rejection boundaries hold.") +
                {"weak": " I added missing rejection assertions.", "missing": " I supplied the missing focused tests.",
                 "false-green": " The old assertions only tested True; they proved nothing about the implementation. I replaced them with calls and expected exceptions.",
                 "bad-test": " The old valid-sample assertion expected the wrong value. I corrected the test to the contract and reran it.",
                 "adequate": " Existing tests already cover the assigned scope; no duplicate tests are needed."}[spec["condition"]])
        controls.append({"case_id": spec["case_id"], "good_response": expected + ". " + explanation,
                         "good_decision": expected,
                         "wrong_response": ("FAIL" if expected == "PASS" else "PASS") + ". The Worker said it was done, so I accept that conclusion without inspecting evidence.",
                         "wrong_decision": "FAIL" if expected == "PASS" else "PASS",
                         "shallow_response": expected + ". I selected this verdict but did not examine tests or evidence.",
                         "expected_role_outcomes": {"good": "PASS", "wrong": "FAIL", "shallow": "FAIL"}})
    write_json(root / "controls.json", {"origin": "authored calibration annotations; human semantic review pending", "controls": controls})
    sources = {}
    for project, api in APIS.items():
        for path in api.packet_root(repo).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                sources[path.relative_to(repo).as_posix()] = digest(path)
    for name in ("src/localbench/assistant001/calibration.py", "src/localbench/assistant002/calibration.py",
                 "campaigns/flashnext-all-roles-v1/sources/local-model-bench/benchmark/tester/QUALIFICATION_PLAN.md",
                 "campaigns/flashnext-all-roles-v1/sources/deepseek-lab/native-lab/reviewer-dispatch.test.mjs"):
        sources[name] = digest(repo / name)
    write_json(root / "freeze.json", {"files": {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob("*"))
                                               if p.is_file() and p.name != "freeze.json"}, "sources": sources})
    print("FREEZE_SHA256=" + digest(root / "freeze.json"))
    print(f"Frozen {len(cases)} cases; authored fixture execution only.")


if __name__ == "__main__":
    main()
