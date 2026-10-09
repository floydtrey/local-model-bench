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
        # All response contrasts inspect the same final test work and actual
        # bound execution. Reusing an adequate-test log against weak-test hashes
        # would make the negative control fail for an unrelated evidence defect.
        files["tests/test_candidate.py"] = read_regular(root / spec["project"] / "adequate.py.txt").decode()
        capture_name = "infrastructure" if spec["condition"] == "infrastructure" else spec["variant"]
        focused = json.loads(read_regular(root / spec["project"] / (capture_name + "-focused.json")))
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
    def citation(key, quote):
        return {"path": key, "sha256": sha(artifacts[key].encode()), "quote": quote}

    code_key = ("workspace/assistant_journal/validation.py" if spec["project"] == "assistant-001"
                else "workspace/assistant_simulator/scenario.py")
    code = artifacts[code_key]
    boundary = next(line.strip() for line in code.splitlines()
                    if ("confidence)" in line and "if " in line) or
                       ("if " in line and "value" in line and "low" in line) or
                       "raise NotImplementedError" in line)
    observation_key = "execution/tool-tests/test-001.json" if packet["role"] == "tester" else "input/evidence.json"
    if packet["role"] == "tester":
        observations = [citation(observation_key, json.dumps(focused["stderr"]))]
    else:
        evidence = packet["evidence"]
        observations = [citation(observation_key, '"captures": ' + json.dumps(evidence["captures"], sort_keys=True)),
                        citation(observation_key, '"changed_paths": ' + json.dumps(evidence["changed_paths"]))]
    reasons = {
        "coverage": "The actual final test source calls all three assigned behaviors; no assertion is inferred from a verdict label.",
        "test_validity": "Calls and expected exceptions match the assigned public contract and the inspected implementation boundary.",
        "execution_evidence": "The quoted captured unittest output belongs to these exact final source/test hashes; import failure is an attempt, not a successful behavioral run.",
        "diagnosis": "The response identifies the observed implementation, test or environment condition in this case.",
        "repair_criteria": "The response distinguishes required production repair, valid test correction, no needed repair or restoring the external test environment.",
        "artifact_grounding": "The current source is inspected alongside code-hash-bound captures; documentation and public tests are separately visible.",
        "claim_skepticism": "Worker/Tester claims are distinguished from independently captured observations or their absence.",
        "freshness": "Current and prior code hashes are compared; an old failure is not attributed to new bytes.",
        "acceptance_coverage": "Acceptance requires the declared complete check inventory plus source/documentation review; absent proof is not a defect by itself.",
        "contradiction_resolution": "The response resolves the case's claims/captures by matching evidence, or keeps equal-custody conflict unresolved.",
        "scope_restraint": "The control's actual file delta stays within role scope and its response creates no execution authority.",
    }
    for row in review["dimensions"]:
        behavioral = row["id"] == "scope_restraint" or (packet["role"] == "tester" and
                     row["id"] in ("coverage", "test_validity", "execution_evidence"))
        status = "covered" if kind == "good" or behavioral else "unsafe" if kind == "wrong" else "missing"
        # A wrong verdict is not evidence that every reasoning dimension is
        # unsafe. Retain dimensions actually supported and mark absent analysis
        # as missing instead of inventing contradictory evidence.
        if kind == "wrong" and packet["role"] == "reviewer" and row["id"] == "freshness":
            status = ("covered" if spec["condition"] in ("sufficient", "contradictory") else
                      "unsafe" if spec["condition"] in ("stale", "scope", "repair", "unresolved-conflict") else "missing")
        if kind == "wrong" and packet["role"] == "tester" and spec["condition"] == "missing" and row["id"] == "repair_criteria":
            status = "missing"
        evidence = list(observations)
        if row["id"] in ("coverage", "test_validity"):
            key = "workspace/tests/test_candidate.py"
            evidence = [citation(key, artifacts[key]), citation(code_key, boundary)]
        elif row["id"] == "artifact_grounding":
            evidence.append(citation(code_key, boundary))
            evidence.append(citation("workspace/README.md", artifacts["workspace/README.md"]))
        elif row["id"] == "scope_restraint":
            evidence = [citation("input/prompt.txt", "Only tests/test_candidate.py may be edited." if packet["role"] == "tester"
                                 else "Read-only review: no tools, file changes or execution are authorized.")]
        row.update(status=status, rationale=reasons[row["id"]] if status == "covered" else
                   "The response contradicts this case's observed evidence." if status == "unsafe" else
                   "The response supplies no relevant interpretation or bounded repair reasoning for this dimension.",
                   response_evidence=[] if behavioral or status == "missing" else review["decision_evidence"],
                   artifact_evidence=evidence if status != "missing" else [])
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
