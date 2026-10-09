"""Offline consistency checks for authored Governor controls, not a semantic grader."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from localbench.assistant001.packet import repository_root
from .governor_packet import load_freeze, fixture_root, FREEZE_SHA256, PROJECTS
from .governor_assessment import classifications, rubric, validate_review
from .planner_packet import read_regular, sha

MANIFEST_SHA256 = "2ed45bf6733f7ba1b8f08fc223cf8289afdb14c00c65c1a0f7c5b0be78bf2a3e"
NAMES = ("correct-approval", "alternate-approval", "correct-denial", "correct-escalation",
         "unsafe-approval", "blanket-denial", "erroneous-escalation", "omitted-constraints")


def calibrate(repo=None):
    root = Path(repo or repository_root())
    freeze = load_freeze(root)
    base = root / "docs/qualification-v2/governor-calibration"
    raw = read_regular(base / "manifest.json")
    if sha(raw) != MANIFEST_SHA256:
        raise ValueError("Governor calibration manifest changed; review/version required")
    manifest = json.loads(raw)
    if manifest["freeze_sha256"] != FREEZE_SHA256:
        raise ValueError("Calibration belongs to a different freeze")
    expected = {(p, n) for p in PROJECTS for n in NAMES}
    if {(f["project"], f["name"]) for f in manifest["fixtures"]} != expected or len(manifest["fixtures"]) != len(expected):
        raise ValueError("Incomplete calibration inventory")
    provenance = json.loads(read_regular(fixture_root(root) / "canonical-provenance.json"))
    records = []
    for fixture in manifest["fixtures"]:
        folder = base / fixture["project"]
        text_raw = read_regular(folder / (fixture["name"] + ".txt"))
        review_raw = read_regular(folder / (fixture["name"] + ".json"))
        if sha(text_raw) != fixture["candidate_sha256"] or sha(review_raw) != fixture["review_sha256"]:
            raise ValueError("Calibration fixture integrity mismatch")
        packet = fixture["packet_binding"]
        cases = json.loads(read_regular(fixture_root(root) / fixture["project"] / "inputs.json"))["cases"]
        selected = next(c for c in cases if c["case_id"] == packet["case_id"])
        if (packet["freeze_sha256"] != FREEZE_SHA256
                or packet["project_source_sha256"] != freeze["project_sources"][fixture["project"]]
                or packet["plan_sha256"] != sha(selected["plan"].encode())
                or packet["simulation_sha256"] != sha(json.dumps(selected["simulation_conditions"], sort_keys=True).encode())
                or packet["governance_sha256"] != sha(json.dumps(provenance, sort_keys=True).encode())):
            raise ValueError("Calibration material provenance mismatch")
        text, review = text_raw.decode(), json.loads(review_raw)
        validate_review(review, packet, text, execution_status="imported", repo=root, calibration=True)
        failures = classifications(review, rubric(packet, root)["expected_decision"])
        if review["verdict"] != fixture["expected_verdict"] or failures != fixture["expected_classifications"]:
            raise ValueError("Calibration expected annotation mismatch")
        if review["verdict"] == "FAIL":
            promoted = copy.deepcopy(review)
            promoted["verdict"] = "PASS"
            try:
                validate_review(promoted, packet, text, execution_status="imported", repo=root, calibration=True)
            except ValueError:
                pass
            else:
                raise ValueError("Defective control was incorrectly promoted")
        records.append({"case_id": packet["case_id"], "control": fixture["name"],
                        "expected_verdict": review["verdict"], "classifications": failures})
    return {"record_checks_passed": True, "fixtures": records,
            "semantic_calibration_status": "HUMAN_REVIEW_PENDING", "independent_review_status": "PENDING",
            "model_calls": 0, "candidate_code_executed": False, "qualification_complete": False,
            "limitation": "Checks validate authored annotations and bindings. Humans must independently judge the cases, prose and labels; no substantive calibration is claimed."}
