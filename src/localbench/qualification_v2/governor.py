"""Controlled Governor adapter over existing role sessions and review evidence writer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from localbench.assistant001.packet import repository_root, write_json
from localbench.assistant001.cli import review_package
from .planner_packet import read_regular, sha
from .governor_packet import PROJECTS, CASES, prepare, verify_run, external_directory
from .governor_assessment import assess, draft_review


def run_governor(run, sessions, *, repo=None, case_publisher=None):
    run = external_directory(run, repo)
    packet = verify_run(run, repo)
    if (run / "session.json").exists() or (run / "roles").exists():
        raise ValueError("Use a fresh Governor session")
    evidence = external_directory(run / "roles/governor", repo)
    if case_publisher is not None:
        case_publisher.started(key=("controlled-role", str(run.resolve()), 'governor', packet["case_id"], 1))
    try:
        result = sessions(role="governor", case_id=packet["case_id"], prompt=packet["prompt"],
                          workspace=None, writable=[], evidence=evidence)
    except Exception as exc:
        result = {"status": "error", "stop_reason": "session_infrastructure_error",
                  "final_response": "", "error": f"{type(exc).__name__}: {exc}", "metrics": {}}
    verify_run(run, repo)
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "final.txt").write_bytes(result.get("final_response", "").encode())
    write_json(run / "session.json", result)
    return result


def assess_run(run, *, candidate_file=None, review_file=None, repo=None, case_publisher=None):
    run = external_directory(run, repo)
    packet = verify_run(run, repo)
    if candidate_file is not None:
        text = read_regular(Path(candidate_file)).decode("utf-8-sig")
        session = {"status": "imported", "metrics": {}, "authority_violations": 0}
        origin = "external_text_no_model_run_claim"
    else:
        session = json.loads(read_regular(run / "session.json"))
        text = read_regular(run / "roles/governor/final.txt").decode()
        if text != session.get("final_response"):
            raise ValueError("Captured output differs from session")
        origin = "captured_session"
    review = json.loads(read_regular(Path(review_file))) if review_file else None
    identity = None
    inputs = None
    captured = None
    provenance_note = "Imported text has no captured runtime evidence."
    if candidate_file is None:
        from .governor_evidence import captured_protocol
        try:
            captured = captured_protocol(run, packet, session, Path(repo or repository_root()))
            identity, inputs = captured["identity"], captured["inputs"]
            provenance_note = "Verified sealed foundation, effective settings, fresh-session transcript and output binding."
        except (OSError, ValueError, KeyError, TypeError) as exc:
            provenance_note = "Runtime comparison blocked: " + str(exc)
    assessment = assess(packet, text, execution_status=session["status"],
                        authority_violations=session.get("authority_violations", 0), review=review, repo=repo)
    target = external_directory(run / "assessments" / uuid4().hex, repo)
    target.mkdir(parents=True, exist_ok=False)
    (target / "candidate.txt").write_bytes(text.encode())
    write_json(target / "assessment.json", assessment)
    write_json(target / "review-template.json", draft_review(packet, text, repo))
    spec = assessment["rubric"]
    protocol = captured["protocol"] if captured else None
    row = {**session, "final_response": text, "case_id": packet["case_id"], "role": "governor", "ordinal": 1,
           "track": "controlled_role_qualification", "governor_mode": "independent_frozen_simulation",
           "input_sha256": packet["input_sha256"], "governance_sha256": packet["governance_sha256"],
           "candidate_sha256": sha(text.encode()), "rubric_version": spec["schema_version"],
           "rubric_sha256": spec["rubric_sha256"], "assessment_file": str(target / "assessment.json"),
           "evidence_directory": str(target), "session_evidence_directory": str(run / "roles/governor") if candidate_file is None else None,
           "configuration_evidence_directory": str(run / "evidence") if identity else None,
           "runtime_identity": identity, "model_identity": identity.get("model") if identity else None,
           "comparison_protocol": protocol, "output_origin": origin, "execution_status": session["status"],
           "trial_id": run.name, "expected_decision": spec["expected_decision"],
           "effective_timeout_observations": captured["effective_timeout_observations"] if captured else None,
           "provenance_note": provenance_note,
           "assessed_outcome": assessment["assessed_outcome"], "human_review_status": assessment["human_review_status"],
           "reference_review_status": "HUMAN_REVIEW_PENDING", "human_review_required": review is None,
           "candidate_decision": review["decision"] if review else None,
           "failure_classifications": assessment["failure_classifications"],
           "critical_unsafe_approval": assessment["critical_unsafe_approval"],
           "deterministic_passed": None, "first_pass_passed": None,
           "correctness": "pending-human-adjudication" if review is None else "human-" + review["verdict"].lower(),
           "qualification_status": "human-review-pending-reference-not-signed-off",
           "comparison_eligible": (origin == "captured_session" and session["status"] == "success"
                                   and protocol is not None
                                   and bool(identity.get("model")) and not session.get("authority_violations", 0)),
           "comparison_note": "Require matching frozen inputs/rubric and verified effective runtime/configuration. Host facts must match. Imports and missing evidence are ineligible; human reference review remains pending."}
    from localbench.v2.report_adapter import bind_current_assessment
    bind_current_assessment(row, run, "qualification-v2-governor")
    if case_publisher is not None:
        case_publisher.completed(key=("controlled-role", str(run.resolve()), 'governor', packet["case_id"], 1), row=row, native_root=run)
    summary = {"campaign": "qualification-v2-governor", "roles": ["governor"],
               "track": "controlled_role_qualification", "results": [row], "planned_cases": 1,
               "completed_cases": int(session["status"] == "success"),
               "qualification_status": row["qualification_status"], "project_execution_authorized": False,
               "model_qualification_complete": False, "reference_review_status": "HUMAN_REVIEW_PENDING"}
    write_json(target / "summary.json", summary)
    review_package(target, summary, inputs["model"] if inputs else "unknown-import", "independent-governor",
                   inputs["context_tokens"] if inputs else None)
    return target, assessment


def verified_comparison_row(summary_file, repo=None):
    """Recheck the report against current raw evidence; summary flags are not proof."""
    from .governor_evidence import captured_protocol
    path = Path(summary_file)
    target = path.parent
    if path.name != "summary.json" or target.parent.name != "assessments":
        raise ValueError("Compare requires an original Governor assessment summary")
    run = target.parent.parent
    packet = verify_run(run, repo)
    summary = json.loads(read_regular(path))
    if len(summary.get("results", [])) != 1:
        raise ValueError("Expected one original case assessment")
    row = summary["results"][0]
    if row.get("output_origin") != "captured_session":
        raise ValueError("Imported text is not a runtime comparison trial")
    text = read_regular(target / "candidate.txt").decode()
    session = json.loads(read_regular(run / "session.json"))
    if text != session.get("final_response") or read_regular(run / "roles/governor/final.txt").decode() != text:
        raise ValueError("Comparison candidate differs from captured output")
    stored = json.loads(read_regular(target / "assessment.json"))
    current = assess(packet, text, execution_status=session["status"],
                     authority_violations=session.get("authority_violations", 0),
                     review=stored.get("human_adjudication"), repo=repo)
    if stored != current:
        raise ValueError("Assessment differs from raw evidence/current frozen rubric")
    captured = captured_protocol(run, packet, session, Path(repo or repository_root()))
    expected = {"case_id": packet["case_id"], "input_sha256": packet["input_sha256"],
                "candidate_sha256": sha(text.encode()), "governance_sha256": packet["governance_sha256"],
                "rubric_sha256": current["rubric"]["rubric_sha256"],
                "expected_decision": current["rubric"]["expected_decision"],
                "comparison_protocol": captured["protocol"], "model_identity": captured["model_identity"],
                "trial_id": run.name, "execution_status": session["status"],
                "human_review_status": current["human_review_status"], "assessed_outcome": current["assessed_outcome"],
                "failure_classifications": current["failure_classifications"],
                "critical_unsafe_approval": current["critical_unsafe_approval"],
                "candidate_decision": current["human_adjudication"]["decision"] if current["human_adjudication"] else None,
                "comparison_eligible": session["status"] == "success" and session.get("authority_violations", 0) == 0}
    if any(row.get(k) != v for k, v in expected.items()):
        raise ValueError("Comparison summary differs from verified source evidence")
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "assess", "calibrate", "compare"))
    parser.add_argument("--repo-root", type=Path, default=repository_root())
    parser.add_argument("--project", choices=PROJECTS)
    parser.add_argument("--case", choices=CASES, default="01")
    parser.add_argument("--governor-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--candidate-file", type=Path)
    parser.add_argument("--review-file", type=Path)
    parser.add_argument("--summaries", type=Path, nargs="+")
    parser.add_argument("--model")
    parser.add_argument("--allow-model-inference", action="store_true")
    parser.add_argument("--context-tokens", type=int, default=32768)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--timeout-seconds", type=float, default=600)
    args = parser.parse_args(argv)
    try:
        if args.action == "calibrate":
            from .governor_calibration import calibrate
            print(json.dumps(calibrate(args.repo_root), indent=2))
            return 0
        if args.action == "compare":
            from .governor_assessment import compare
            if not args.summaries:
                raise ValueError("compare requires --summaries")
            records = []
            for path in args.summaries:
                records.append(verified_comparison_row(path, args.repo_root))
            result = compare(records)
            print(json.dumps(result, indent=2))
            return 0 if result["comparable"] else 1
        if args.action == "prepare":
            if not args.project or not args.output_root or not args.governor_root:
                raise ValueError("prepare requires project, private output-root and canonical governor-root")
            run = prepare(args.project, args.output_root, case=args.case, governor_root=args.governor_root, repo=args.repo_root)
            print(f"PRIVATE_RUN_DIR={run}")
            return 0
        if not args.run_dir:
            raise ValueError("run/assess requires --run-dir")
        verify_run(args.run_dir, args.repo_root)
        if args.action == "run":
            if not args.allow_model_inference or not args.model:
                raise ValueError("run requires explicit --allow-model-inference and --model")
            if args.candidate_file or args.review_file or args.governor_root:
                raise ValueError("Candidate runs cannot receive review files or replacement input")
            if (args.run_dir / "session.json").exists() or (args.run_dir / "roles").exists():
                raise ValueError("Use a fresh prepared run")
            from localbench.assistant001.runtime import OllamaSessions
            sessions = OllamaSessions(args.repo_root, args.run_dir, args.model,
                                      context_tokens=args.context_tokens, max_output_tokens=args.max_output_tokens,
                                      timeout_seconds=args.timeout_seconds)
            write_json(args.run_dir / "runtime-identity.json", {k: v.reference.to_dict() for k, v in sessions.foundation.items()})
            write_json(args.run_dir / "runner-inputs.json", {
                "model": args.model, "context_tokens": args.context_tokens, "max_output_tokens": args.max_output_tokens,
                "timeout_seconds": args.timeout_seconds, "transport": "direct_ollama", "host_execution_authorized": False,
                "session_policy": "fresh no-tools RoleConversation", "governor_mode": "independent_frozen_simulation"})
            result = run_governor(args.run_dir, sessions, repo=args.repo_root)
            target, _ = assess_run(args.run_dir, repo=args.repo_root)
            print(f"ASSESSMENT_DIR={target}")
            return 0 if result["status"] == "success" else 1
        target, result = assess_run(args.run_dir, candidate_file=args.candidate_file, review_file=args.review_file, repo=args.repo_root)
        print(f"ASSESSMENT_DIR={target}\nOUTCOME={result['assessed_outcome']}")
        return 0
    except (ValueError, OSError, UnicodeError, KeyError) as exc:
        print(f"Governor qualification blocked: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
