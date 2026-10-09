"""Additive Planner adapter over OllamaSessions and the existing review writer."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from localbench.assistant001.packet import write_json
from localbench.assistant001.cli import review_package
from .planner_packet import verify_run, read_regular, sha
from .planner_assessment import assess, draft_review


def run_planner(run, sessions, *, repo=None):
    """Trusted session injection supports deterministic tests; public CLI owns consent.

    A fresh RoleConversation is created by OllamaSessions for every invocation.
    workspace=None is essential: even read-only BoundedWorkspace would expose the
    historical run_tests tool. The entire audited source view is already inline.
    """
    run = Path(run).resolve()
    packet = verify_run(run, repo)
    if (run / "session.json").exists() or (run / "roles").exists():
        raise ValueError("Refusing to resume/reuse a Planner session")
    evidence = run / "roles/planner"
    try:
        result = sessions(role="planner", case_id=packet["case_id"], prompt=packet["prompt"],
                          workspace=None, writable=[], evidence=evidence)
    except Exception as exc:
        result = {"status": "error", "stop_reason": "session_infrastructure_error",
                  "final_response": "", "error": f"{type(exc).__name__}: {exc}", "metrics": {}}
    verify_run(run, repo)
    # Keep an exact text artifact even for fake sessions and failures.
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "final.txt").write_bytes(result.get("final_response", "").encode())
    write_json(run / "session.json", result)
    return result


def assess_run(run, *, plan_file=None, review_file=None, repo=None, model="unknown", context_tokens=None):
    run = Path(run).resolve()
    packet = verify_run(run, repo)
    if plan_file is not None:
        text = read_regular(Path(plan_file)).decode("utf-8")
        session = {"status": "imported", "metrics": {}, "authority_violations": 0}
        origin = "external_text_no_model_run_claim"
    else:
        session = json.loads(read_regular(run / "session.json"))
        text = read_regular(run / "roles/planner/final.txt").decode("utf-8")
        if text != session.get("final_response"):
            raise ValueError("Session output differs from captured final text")
        origin = "captured_session"
    review = json.loads(read_regular(Path(review_file))) if review_file else None
    identity_path = run / "runtime-identity.json"
    identity = json.loads(read_regular(identity_path)) if identity_path.exists() and plan_file is None else None
    assessment = assess(packet, text, execution_status=session["status"],
                        authority_violations=session.get("authority_violations", 0), review=review, repo=repo)
    target = run / "assessments" / uuid4().hex
    target.mkdir(parents=True, exist_ok=False)
    (target / "candidate.txt").write_bytes(text.encode())
    write_json(target / "assessment.json", assessment)
    write_json(target / "review-template.json", draft_review(packet, text, repo))
    row = {**session, "final_response": text, "case_id": packet["case_id"], "role": "planner", "ordinal": 1,
           "track": "controlled_role_qualification", "planner_mode": "independent_blind",
           "input_sha256": packet["input_sha256"], "candidate_sha256": sha(text.encode()),
           "rubric_version": assessment["schema_version"], "rubric_sha256": assessment["rubric"]["rubric_sha256"],
           "assessment_file": str(target / "assessment.json"), "evidence_directory": str(target),
           "session_evidence_directory": str(run / "roles/planner") if plan_file is None else None,
           "runtime_identity": identity, "configuration_evidence_directory": str(run / "evidence") if identity else None,
           "execution_status": session["status"], "assessed_outcome": assessment["assessed_outcome"],
           "human_review_status": assessment["human_review_status"],
           "human_review_required": review is None, "deterministic_passed": None, "first_pass_passed": None,
           "qualification_status": "human-review-pending" if review is None else "human-adjudication-recorded-no-role-assignment",
           "correctness": "pending-human-adjudication" if review is None else "human-" + review["verdict"].lower(),
           "comparison_eligible": origin == "captured_session" and session["status"] == "success" and identity is not None,
           "comparison_note": "Require matching case/input/rubric, runtime, model identity and configuration; imports are ineligible.",
           "output_origin": origin}
    summary = {"campaign": "qualification-v2-planner", "roles": ["planner"],
               "track": "controlled_role_qualification", "results": [row], "planned_cases": 1,
               "completed_cases": int(session["status"] == "success"), "qualification_status": row["qualification_status"],
               "project_execution_authorized": False}
    write_json(target / "summary.json", summary)
    review_package(target, summary, model, "independent-planner", context_tokens)
    return target, assessment
