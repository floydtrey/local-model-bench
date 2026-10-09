"""Thin controlled-role adapter over existing sessions and review writer."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from localbench.assistant001.packet import write_json
from localbench.v2.flashnext_review import write_review_package
from .planner_packet import read_regular
from .verification_packet import WRITABLE, safe_snapshot, verify_run
from .verification_assessment import assess, draft_review


def run_trial(run, sessions, *, identity, repo=None, allow_model_inference=False, allow_host_execution=False):
    """Trusted session injection is the existing testing seam, not a new runner.

    Identity comes from the operator's provider records, never candidate output.
    Public CLI intentionally offers no execution command in this batch.
    """
    run = Path(run)
    packet, _ = verify_run(run, repo, pristine=True)
    if not allow_model_inference or (packet["role"] == "tester" and not allow_host_execution):
        raise ValueError("Separate inference and Tester host-execution authorization required")
    if "flash" in json.dumps(identity).lower():
        raise ValueError("Flash-Next remains suspended")
    if not isinstance(identity, dict) or not all(identity.get(k) for k in ("model", "runtime", "configuration", "origin")):
        raise ValueError("Model/runtime/configuration identity and origin required")
    if (run / "capture.json").exists() or (run / "roles").exists():
        raise ValueError("Fresh verification trial required")
    evidence = run / "roles" / packet["role"]
    try:
        result = sessions(role=packet["role"], case_id=packet["case_id"], prompt=packet["prompt"],
                          workspace=run / "workspace" if packet["role"] == "tester" else None,
                          writable=WRITABLE if packet["role"] == "tester" else [], evidence=evidence)
    except Exception as exc:
        result = {"status": "error", "stop_reason": "session_infrastructure_error", "final_response": "",
                  "error": f"{type(exc).__name__}: {exc}", "metrics": {}}
    _, scope = verify_run(run, repo)
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "final.txt").write_bytes(result.get("final_response", "").encode())
    captured = {**result, "identity": identity, "scope": scope,
                "artifact_before_sha256": packet["artifact_sha256"],
                "artifact_after_sha256": safe_snapshot(run / "workspace"),
                "evidence_file_sha256": safe_snapshot(evidence),
                "authority_violations": result.get("authority_violations", 0)}
    write_json(run / "capture.json", captured)
    return captured


def read_trial(run, repo=None):
    run = Path(run)
    packet, scope = verify_run(run, repo)
    capture = json.loads(read_regular(run / "capture.json"))
    evidence = run / "roles" / packet["role"]
    if (capture["artifact_before_sha256"] != packet["artifact_sha256"]
            or capture["artifact_after_sha256"] != safe_snapshot(run / "workspace")
            or capture["scope"] != scope or capture["evidence_file_sha256"] != safe_snapshot(evidence)
            or read_regular(evidence / "final.txt").decode() != capture["final_response"]):
        raise ValueError("Trial evidence or artifacts changed after capture")
    artifacts = {"input/evidence.json": json.dumps(packet["evidence"], sort_keys=True),
                 "input/prompt.txt": packet["prompt"]}
    for name in capture["artifact_after_sha256"]:
        artifacts["workspace/" + name] = read_regular(run / "workspace" / name).decode()
    for name in capture["evidence_file_sha256"]:
        artifacts["execution/" + name] = read_regular(evidence / name).decode()
    return packet, capture, artifacts


def assess_run(run, *, review_file=None, repo=None):
    run = Path(run)
    packet, capture, artifacts = read_trial(run, repo)
    review = json.loads(read_regular(Path(review_file))) if review_file else None
    result = assess(packet, capture, artifacts, review, repo)
    target = run / "assessments" / uuid4().hex
    target.mkdir(parents=True, exist_ok=False)
    write_json(target / "assessment.json", result)
    write_json(target / "review-template.json", draft_review(packet, capture, artifacts, repo))
    row = {**capture, **result, "ordinal": 1, "track": "controlled_role_qualification",
           "verification_mode": "independent_frozen", "status": capture["status"],
           "execution_status": capture["status"], "deterministic_passed": None, "first_pass_passed": None,
           "human_review_required": True, "qualification_status": "human-review-pending",
           "correctness": result["assessed_outcome"], "rubric_version": result["schema_version"],
           "model_identity": capture["identity"]["model"], "runtime_identity": capture["identity"]["runtime"],
           "comparison_protocol": capture["identity"]["configuration"], "comparison_eligible": False,
           "output_origin": capture["identity"]["origin"], "assessment_file": str(target / "assessment.json"),
           "evidence_directory": str(target), "session_evidence_directory": str(run / "roles" / packet["role"])}
    from localbench.v2.report_adapter import bind_current_assessment
    bind_current_assessment(row, run, "qualification-v2-verification")
    summary = {"campaign": "qualification-v2-verification", "roles": [packet["role"]], "results": [row],
               "planned_cases": 1, "completed_cases": int(capture["status"] == "success"),
               "qualification_status": "human-review-pending", "project_execution_authorized": False}
    write_json(target / "summary.json", summary)
    profile = {"candidate_id": str(capture["identity"]["model"]), "candidate_name": str(capture["identity"]["model"]),
               "model_entry": str(capture["identity"]["model"]), "server_executable": str(capture["identity"]["runtime"])}
    write_review_package(output_dir=target, summary=summary, profile=profile, shared_run=None, phase="controlled-verification")
    return target, result
