"""Authored response/annotation controls. No semantic auto-grading or inference."""
from __future__ import annotations

import json

from localbench.assistant001.packet import scope_diff
from .planner_packet import read_regular, sha
from .verification_packet import build_packet, case_spec, fixture_root, load_cases, WRITABLE
from .verification_assessment import assess, draft_review


def control_material(case_id, kind="good", repo=None):
    """Explicit fake session with captured trusted-fixture test observations.

    These responses were authored, not produced by a qualified model or reviewed
    by a human. Their annotation consistency is the only calibration claim.
    """
    packet = build_packet(case_id, repo)
    spec = case_spec(case_id, repo)
    root = fixture_root(repo)
    controls = json.loads(read_regular(root / "controls.json"))["controls"]
    control = next(c for c in controls if c["case_id"] == case_id)
    response = control[kind + "_response"]
    files = dict(packet["files"])
    artifacts = {"input/evidence.json": json.dumps(packet["evidence"], sort_keys=True),
                 "input/prompt.txt": packet["prompt"]}
    if packet["role"] == "tester":
        if kind == "good":
            files["tests/test_candidate.py"] = read_regular(root / spec["project"] / "adequate.py.txt").decode()
        focused = json.loads(read_regular(root / spec["project"] / (spec["variant"] + "-focused.json")))
        if spec["condition"] == "infrastructure":
            focused = {"origin": "synthetic_calibration_infrastructure", "exit_code": 1,
                       "stdout": "", "stderr": "ModuleNotFoundError: unavailable_fixture_test_dependency\n"}
            focused.update(stdout_sha256=sha(focused["stdout"].encode()), stderr_sha256=sha(focused["stderr"].encode()),
                           artifact_before_sha256=packet["artifact_sha256"], artifact_after_sha256=packet["artifact_sha256"])
        artifacts["execution/tool-tests/test-001.json"] = json.dumps(focused, sort_keys=True)
    after = {k: sha(v.encode()) for k, v in files.items()}
    artifacts.update({"workspace/" + k: v for k, v in files.items()})
    capture = {"status": "success", "final_response": response, "authority_violations": 0,
               "test_tool_calls": int(packet["role"] == "tester"),
               "artifact_after_sha256": after,
               "scope": scope_diff(packet["artifact_sha256"], after, WRITABLE if packet["role"] == "tester" else []),
               "identity": {"origin": "calibration_fixture", "model": "authored-no-model",
                            "runtime": "none", "configuration": {"inference": False}}}
    review = draft_review(packet, capture, artifacts, repo)
    review.update(review_origin="calibration_fixture", reviewer="authored-control-not-human",
                  reviewed_at="2026-10-09T00:00:00Z", candidate_decision=control.get(kind + "_decision", control["good_decision"]),
                  rationale=spec["rationale"], decision_evidence=[{"start": 0, "end": len(response), "quote": response}])
    key = "execution/tool-tests/test-001.json" if packet["role"] == "tester" else "input/evidence.json"
    for row in review["dimensions"]:
        row.update(status="covered" if kind == "good" else "missing", rationale=spec["rationale"],
                   response_evidence=review["decision_evidence"] if kind == "good" else [],
                   artifact_evidence=[{"path": key, "sha256": sha(artifacts[key].encode()), "quote": artifacts[key]}]
                   if kind == "good" else [])
    return packet, capture, artifacts, review


def calibrate(repo=None):
    rows = []
    for spec in load_cases(repo):
        for kind in ("good", "wrong", "shallow"):
            packet, capture, artifacts, review = control_material(spec["case_id"], kind, repo)
            result = assess(packet, capture, artifacts, review, repo, calibration=True)
            expected = "PASS" if kind == "good" else "FAIL"
            rows.append({"case_id": spec["case_id"], "control": kind, "expected": expected,
                         "observed": result["assessed_outcome"], "passed": result["assessed_outcome"] == expected})
    return {"passed": all(r["passed"] for r in rows), "controls": rows, "count": len(rows),
            "human_substantive_calibration": "PENDING", "model_qualification_complete": False,
            "limitation": "Checks authored annotation consistency, not the truth of semantic annotations.", "model_runs": 0}
