"""Batch-1 reference-plan provenance, requirement coverage, and non-disclosure tests.

These tests use exact existing frozen packet/assessor bytes, temporary workspaces,
and standard-library parsing. No model, DSH session, candidate code or service.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from localbench.assistant001 import packet as a001
from localbench.assistant002 import packet as a002


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "qualification-v2/reference-trace-v1"
PROJECTS = {
    "assistant-001": {"prefix": "R", "check_count": 79, "named": 45, "scenarios": 0, "packet": a001},
    "assistant-002": {"prefix": "S", "check_count": 96, "named": 44, "scenarios": 8, "packet": a002},
}
DECORATED = re.compile(
    r"@check\(\s*(\d+)\s*,\s*['\"]([^'\"]+)['\"](?:[^)]*)\)\s*\n\s*def (test_\w+)\("
)


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\x00" + data).hexdigest()


def verify_trace(project: str, trace: dict) -> None:
    """Raises an assertion for a broken plan lineage, scope or acceptance map."""
    details = PROJECTS[project]
    source_root = ROOT / "project-benchmarks" / project / "v1"
    name = project + "-v1"
    assert trace["schema_version"] == SCHEMA_VERSION
    assert trace["source_packet_id"] == name
    assert trace["reference_version"] == "draft-1"
    assert trace["approval_status"] == "OWNER_REVIEW_PENDING"
    assert trace["distribution"] == "ASSESSOR_ONLY_HIDE_FROM_INDEPENDENT_PLANNER"
    assert trace["qualified_role_assignment"] is False
    assert "v1/TASKS.md" in trace["withheld_from_planner"]
    assert trace["frozen_cumulative_assessor_checks_count"] == details["check_count"]
    assert trace["named_assessor_methods_count"] == details["named"]

    for relative, blob_id in trace["source_git_blobs_sha1"].items():
        assert relative.startswith("project-benchmarks/" + project + "/v1/"), relative
        assert git_blob_sha1((ROOT / relative).read_bytes()) == blob_id, relative

    packet, packet_sha = details["packet"].validate_packet(ROOT)
    assert packet["packet_id"] == name
    assert isinstance(packet_sha, str) and packet_sha
    requirements = [details["prefix"] + f"{index:02d}" for index in range(1, 7)]
    groups = trace["requirement_groups"]
    tasks = trace["tasks"]
    assert len(tasks) == len(groups) == len(packet["tasks"]) == 6
    assert [g["id"] for g in groups] == requirements
    assert [g["task"] for g in groups] == [f"T{index:02d}" for index in range(1, 7)]
    assert [t["id"] for t in tasks] == [f"T{index:02d}" for index in range(1, 7)]
    assert len(set(t["id"] for t in tasks)) == 6

    assessor = (source_root / "assessor/checks.py").read_text(encoding="utf-8")
    decorated = [(int(stage), tag, name) for stage, tag, name in DECORATED.findall(assessor)]
    assert len(decorated) == details["named"]
    assert len({name for _, _, name in decorated}) == len(decorated)
    all_recorded = []

    for stage, (definition, task, group) in enumerate(zip(packet["tasks"], tasks, groups), start=1):
        assert task["id"] == definition["id"] == group["task"]
        assert task["title"] == definition["title"]
        assert task["introduced_requirement"] == group["id"] == requirements[stage - 1]
        assert task["cumulative_requirements"] == requirements[:stage]
        assert task["writable_paths"] == definition["writable_paths"]
        assert task["predecessor_task_ids"] == (
            [f"T{stage-1:02d}"] if stage > 1 else []
        )
        recorded = [(stage, entry["requirement_tag"], entry["name"])
                    for entry in task["assessor_named_methods"]]
        assert recorded == [item for item in decorated if item[0] == stage]
        all_recorded.extend(recorded)
        assert group["positive"] and group["negative"]

        expected_requirements = requirements[0] if stage == 1 else (
            requirements[0] + "–" + requirements[stage - 1]
        )
        assert definition["requirements"] == expected_requirements
    assert all_recorded == decorated

    references = ROOT / "project-benchmarks" / project / "qualification-v2"
    plan = (references / "REFERENCE_PLAN.md").read_text(encoding="utf-8")
    assert "OWNER_REVIEW_PENDING" in plan
    assert "assessor/owner only" in plan
    assert all(re.search(r"^### Task " + t["id"] + r"\b", plan, flags=re.M) for t in tasks)
    assert all(re.search(r"^\| " + r + r" \|", plan, flags=re.M) for r in requirements)
    assert "equivalent" in plan.lower()
    assert "not" in plan.lower()

    scenarios = trace["scenario_fixtures"]
    assert len(scenarios) == details["scenarios"]
    actual = sorted(p.name for p in (source_root / "starter/scenarios").glob("*.json"))
    assert sorted(s["file"] for s in scenarios) == actual
    for s in scenarios:
        assert s["reference_behavior"].strip()

    if project == "assistant-002":
        upstream = trace["supplied_dependency"]
        assert upstream["model_generated_journal"] is False
        assert upstream["journal_implementation_in_candidate_workspace"] is False
        assert upstream["provenance_file"].endswith("/v1/UPSTREAM.json")
        actual_upstream = json.loads((source_root / "UPSTREAM.json").read_text(encoding="utf-8"))
        supplied = source_root / actual_upstream["supplied_path"]
        assert hashlib.sha256(supplied.read_bytes()).hexdigest() == actual_upstream["supplied_sha256"]


class ReferencePlanTests(unittest.TestCase):
    def test_both_reference_plans_trace_frozen_source_and_all_requirements(self):
        for project in PROJECTS:
            with self.subTest(project=project):
                path = ROOT / "project-benchmarks" / project / "qualification-v2" / "TRACEABILITY.json"
                verify_trace(project, json.loads(path.read_text(encoding="utf-8")))

    def test_mutated_plan_source_trace_or_task_scope_is_detected(self):
        for project in PROJECTS:
            path = ROOT / "project-benchmarks" / project / "qualification-v2" / "TRACEABILITY.json"
            original = json.loads(path.read_text(encoding="utf-8"))
            def corrupt_source(data):
                name = next(iter(data["source_git_blobs_sha1"]))
                data["source_git_blobs_sha1"][name] = "0" * 40
            for change in (
                corrupt_source,
                lambda d: d["tasks"][2]["cumulative_requirements"].pop(),
                lambda d: d["tasks"][1]["writable_paths"].append("assessor/checks.py"),
                lambda d: d["tasks"][4]["assessor_named_methods"].clear(),
                lambda d: d["requirement_groups"][3].update({"id": "BROKEN"}),
                lambda d: d.update({"approval_status": "OWNER_APPROVED"}),
            ):
                with self.subTest(project=project, change=change.__name__):
                    candidate = copy.deepcopy(original)
                    change(candidate)
                    with self.assertRaises(AssertionError):
                        verify_trace(project, candidate)

    def test_frozen_v1_prepare_does_not_expose_new_reference_files(self):
        # This explicitly does NOT assert that the old scaffolded Planner is blind.
        # It sees TASKS.md today. T05 must fix that separately in a NEW mode.
        with tempfile.TemporaryDirectory(prefix="qualification-v2-") as temp:
            for project, data in PROJECTS.items():
                with self.subTest(project=project):
                    run = data["packet"].prepare(Path(temp) / project, repo=ROOT, label="source")
                    workspace = run / "workspace"
                    self.assertTrue((workspace / "PROJECT_INTENT.md").is_file())
                    self.assertTrue((workspace / "CONTRACT.md").is_file())
                    self.assertTrue((workspace / "TASKS.md").is_file())  # known old scaffold
                    self.assertFalse((workspace / "REFERENCE_PLAN.md").exists())
                    self.assertFalse((workspace / "TRACEABILITY.json").exists())
                    self.assertFalse((workspace / "assessor").exists())
                    self.assertFalse((workspace / "qualification-v2").exists())

    def test_reference_plans_are_additive_not_in_the_v1_manifest(self):
        for project in PROJECTS:
            with self.subTest(project=project):
                lock = json.loads((ROOT / "project-benchmarks" / project / "v1" / "manifest.json").read_text(encoding="utf-8"))
                self.assertFalse(any("qualification-v2" in p or "REFERENCE_PLAN" in p for p in lock["files"]))
                self.assertEqual(len(lock["files"]), len(set(lock["files"])))
                # The separate reference plan is outside the v1 packet snapshot.
                self.assertTrue((ROOT / "project-benchmarks" / project / "qualification-v2" / "REFERENCE_PLAN.md").is_file())


if __name__ == "__main__":
    unittest.main()
