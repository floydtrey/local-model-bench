"""Offline record calibration controls; never a semantic auto-grader."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from localbench.assistant001.packet import repository_root
from localbench.v2.flashnext_roles import build_role_cases
from .planner_packet import build_packet, read_regular, sha
from .planner_assessment import validate_review


def calibrate(repo=None):
    repo = Path(repo or repository_root())
    base = repo / "docs/qualification-v2/planner-calibration"
    manifest = json.loads(read_regular(base / "manifest.json"))
    expected = {(p, name) for p in ("assistant-001", "assistant-002") for name in (
        "alternate-three", "alternate-eight", "critical-omission", "scope-expansion", "correct-blocked")}
    if ({(f["project"], f["name"]) for f in manifest["fixtures"]} != expected
            or len(manifest["fixtures"]) != len(expected)):
        raise ValueError("Incomplete calibration inventory")
    records = []
    for fixture in manifest["fixtures"]:
        folder = base / fixture["project"]
        raw = read_regular(folder / (fixture["name"] + ".txt"))
        review_raw = read_regular(folder / (fixture["name"] + ".json"))
        if sha(raw) != fixture["candidate_sha256"] or sha(review_raw) != fixture["review_sha256"]:
            raise ValueError("Calibration fixture integrity mismatch")
        text = raw.decode("utf-8")
        review = json.loads(review_raw)
        packet = build_packet(fixture["project"], fixture["case"], repo)
        validate_review(review, packet, text, execution_status="imported", repo=repo, calibration=True)
        if review["verdict"] != fixture["expected_verdict"]:
            raise ValueError("Calibration verdict mismatch")
        if review["verdict"] != "PASS":
            forged = copy.deepcopy(review)
            forged["verdict"] = "PASS"
            try:
                validate_review(forged, packet, text, execution_status="imported", repo=repo, calibration=True)
            except ValueError:
                pass
            else:
                raise ValueError("Incorrect promotion of a defective/blocked control")
        records.append({"case_id": packet["case_id"], "fixture": fixture["name"],
                        "expected_human_outcome": review["verdict"], "record_checks_passed": True})
    historical = build_role_cases(repo / "campaigns/flashnext-all-roles-v1", "planner")
    return {"record_checks_passed": True, "fixtures": records,
            "historical_planner_case_ids": [c["case_id"] for c in historical],
            "historical_cases_rescored": False, "model_calls": 0, "candidate_code_executed": False,
            "semantic_calibration_status": "HUMAN_REVIEW_PENDING",
            "meaning": "Expected human judgments are authored controls, not machine-proven equivalence."}
