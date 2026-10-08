"""Fixed-plan project execution; role verdicts remain advisory and human-reviewed."""
from __future__ import annotations
from pathlib import Path
import json
import time
from .assessment import assess
from .packet import DOCS, digest, packet_root, read_run, snapshot, task_prompt, write_json


def run_worker_chain(run, sessions, *, through="T06", repo=None, ordinal=1,
                     allow_host_execution=False, assessor=assess, packet_api=None):
    from . import packet as default_packet
    api = packet_api or default_packet
    if not allow_host_execution:
        raise ValueError("Explicit host-execution acknowledgement required")
    record, packet = api.read_run(run, repo); run = Path(run)
    if (run / "summary.json").exists():
        raise ValueError("Refusing to overwrite a prior campaign; start a fresh run")
    tasks = [item for item in packet["tasks"] if item["id"] <= through]
    if through not in [item["id"] for item in tasks]:
        raise ValueError("Unknown through task")
    results = []; handoff = ""; predecessor_accepted = True
    summary = {"campaign": record["packet_id"], "track": "fixed-plan-worker-chain",
               "results": results, "planned_cases": len(tasks), "completed_cases": 0,
               "qualification_status": "human-review-pending", "guided_repairs": 0,
               "stopped": None, "os_sandbox": False}
    for task in tasks:
        case_id = record["packet_id"].rsplit("-v", 1)[0].replace("-", "") + "-" + task["id"].lower()
        evidence = run / "roles/worker" / task["id"]
        row = {"case_id": case_id, "role": "worker", "ordinal": ordinal,
               "human_review_required": True, "qualification_status": "human-review-pending",
               "repair_attempted": False, "repair_passed": None,
               "deterministic_passed": None, "first_pass_passed": None,
               "evidence_directory": str(evidence), "metrics": {}}
        if not predecessor_accepted:
            row.update(status="blocked", stop_reason="predecessor_not_accepted",
                       correctness="not-assessed-predecessor-blocked")
            results.append(row); continue
        before = snapshot(run / "workspace")
        prompt = api.task_prompt(run, task["id"], handoff, repo)
        print(f"Starting {task['id']}: {task['title']}", flush=True)
        started = time.monotonic()
        try:
            result = sessions(role="worker", case_id=case_id, prompt=prompt,
                              workspace=run / "workspace", writable=task["writable_paths"], evidence=evidence)
            row.update(result)
            handoff = result.get("final_response", "")
            # Retain even failed implementations as candidate evidence, never fill
            # missing stages with the calibration reference or a different model.
            acceptance, path = assessor(run, task["id"], repo=repo,
                allow_host_execution=True, before=before, writable=task["writable_paths"])
            accepted = (acceptance["passed"] and result["status"] == "success"
                        and bool(handoff.strip()) and not result.get("authority_violations", 0))
            row.update(deterministic_passed=accepted, first_pass_passed=accepted,
                       assessment_file=str(path / "assessment.json"),
                       correctness="deterministic-pass-review-pending" if accepted else "not-accepted-review-pending",
                       assessment_status=acceptance["status"], handoff_present=bool(handoff.strip()))
            # Same workspace; hash-link each actual predecessor to its successor.
            write_json(evidence / "handoff-link.json", {"before_sha256": before,
                "after_sha256": snapshot(run / "workspace"), "accepted": accepted,
                "assessment_sha256": digest(path / "assessment.json"),
                "predecessor_final": str(run / "roles/worker" / f"T0{int(task['id'][-1])-1}" / "final.txt") if task["id"] != "T01" else None})
            predecessor_accepted = accepted
        except Exception as exc:
            row.update(status="error", stop_reason="project_runner_or_infrastructure_failure",
                       correctness="not-assessed", deterministic_passed=False, first_pass_passed=False,
                       error=f"{type(exc).__name__}: {exc}")
            predecessor_accepted = False
        row["metrics"] = {**row.get("metrics", {}), "wall_seconds": time.monotonic() - started}
        results.append(row); summary["completed_cases"] += 1
        if not predecessor_accepted:
            summary["stopped"] = {"task": task["id"], "reason": row.get("stop_reason"),
                                  "assessment_status": row.get("assessment_status")}
        write_json(run / "summary.json", summary)
        print(f"{task['id']}: {'accepted pending human review' if predecessor_accepted else 'not accepted; successors blocked'}", flush=True)
    summary["passed"] = all(row.get("deterministic_passed") is True for row in results)
    write_json(run / "summary.json", summary)
    return summary


def role_prompt(role, source_run, *, repo=None, governor_root=None, packet_api=None):
    """Build an auditable probe packet from actual artifacts, not claimed success."""
    from . import packet as default_packet
    api = packet_api or default_packet
    root = api.packet_root(repo); source_run = Path(source_run)
    record, _ = api.read_run(source_run, repo)
    text = "\n\n".join((root / name).read_text(encoding="utf-8") for name in api.DOCS)
    files = snapshot(source_run / "workspace")
    text += "\n\n# Actual candidate file snapshot\n"
    for path, sha in files.items():
        value = (source_run / "workspace" / path).read_text(encoding="utf-8", errors="replace")
        text += f"\n## {path}\nSHA256: {sha}\n```\n{value}\n```\n"
    if role == "planner":
        text += ("\nEvaluate this real starter and produce a bounded project plan. Distinguish unfinished work "
                 "from existing code. Preserve the released interface and decisions. Explain dependencies, "
                 "testable acceptance, risks and remaining uncertainties. Do not write implementation code. "
                 "The fixed task sequence is a comparison reference, not a mandatory response format.\n")
    elif role == "governor":
        if governor_root is None:
            raise ValueError("Governor probe requires canonical --governor-root")
        text += "\n# Canonical governance supplied by the operator\n"
        for name in ("LAW.md", "STATE.md", "GENERAL_INTENT.md"):
            path = Path(governor_root) / "docs" / name
            value = path.read_text(encoding="utf-8-sig")
            if not value.strip():
                raise ValueError("Empty governance document")
            text += f"\n## {name}\nSHA256: {digest(path)}\n{value}\n"
        text += "\nReview the proposed plan below against these exact documents and released intent. Do not invent Owner authorization. Your decision is advisory; do not execute anything.\n"
    elif role == "tester":
        text += "\nEvaluate the actual implementation. You may edit tests/test_candidate.py only. Run actual focused tests through run_tests. Do not edit production code, benchmark checks or requirements. Return PASS, FAIL or BLOCKED with evidence in natural prose.\n"
    elif role == "reviewer":
        text += "\nReview the actual task artifacts and independent evidence below. Distinguish code defects, absent evidence, claims and infrastructure problems. Do not infer acceptance from an exit code alone. Return an advisory verdict with precise evidence and uncertainty. No tools or execution are authorized.\n"
    else:
        raise ValueError("Unknown probe role")
    if len(text.encode("utf-8")) > 512000:
        raise ValueError("Probe packet exceeds 512 KB; no silent truncation")
    return text


def run_probe(target_run, source_run, sessions, *, role, repo=None,
              governor_root=None, plan_file=None, allow_host_execution=False, packet_api=None):
    """One advisory role, never auto-authorize a subsequent role from its prose."""
    import shutil
    from .packet import scope_diff
    target_run, source_run = Path(target_run), Path(source_run)
    from . import packet as default_packet
    api = packet_api or default_packet
    record, _ = api.read_run(target_run, repo); api.read_run(source_run, repo)
    prefix = record["packet_id"].rsplit("-v", 1)[0].replace("-", "") + "-"
    if target_run.resolve() == source_run.resolve():
        raise ValueError("Probe must use a separate disposable target")
    if role == "tester" and not allow_host_execution:
        raise ValueError("Tester execution requires --allow-host-execution")
    if role == "governor" and plan_file is None:
        raise ValueError("Governor needs an actual --plan-file, not an inferred approval")
    source_before = snapshot(source_run / "workspace")
    shutil.rmtree(target_run / "workspace")
    shutil.copytree(source_run / "workspace", target_run / "workspace", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    prompt = role_prompt(role, target_run, repo=repo, governor_root=governor_root, packet_api=api)
    if plan_file is not None:
        plan_file = Path(plan_file)
        prompt += f"\n# Supplied plan\nSHA256: {digest(plan_file)}\n" + plan_file.read_text(encoding="utf-8")
    if role in ("tester", "reviewer"):
        if not list((source_run / "assessments").rglob("assessment.json")):
            prompt += "\nNo independently captured assessment was supplied. Candidate prose is a claim, not execution evidence.\n"
        for path in sorted((source_run / "roles").rglob("final.txt")):
            prompt += f"\n# Candidate claim: {path.relative_to(source_run)}\nSHA256: {digest(path)}\n" + path.read_text(encoding="utf-8")
        for path in sorted((source_run / "assessments").rglob("assessment.json")):
            assessment = json.loads(path.read_text(encoding="utf-8"))
            matches = assessment.get("candidate_sha256") == source_before
            # Don't disclose private assessor internals to a Tester. A Reviewer
            # receives reported observations, not the reference implementation.
            safe = {k: assessment.get(k) for k in ("task", "status", "passed", "exit_code", "planned", "executed")}
            if role == "reviewer":
                safe["checks"] = [{k: row.get(k) for k in ("case_id", "requirement", "passed", "diagnostics")} for row in assessment.get("checks", [])]
            prompt += f"\n# Independently captured result\nSHA256: {digest(path)}\nMatches current code: {matches}\n" + json.dumps(safe)
    if len(prompt.encode("utf-8")) > 512000:
        raise ValueError("Probe packet exceeds 512 KB; no silent truncation")
    (target_run / "probe-source.json").write_text(json.dumps({"source_run": str(source_run.resolve()), "files": source_before}, indent=2), encoding="utf-8")
    evidence = target_run / "roles" / role
    writable = ["tests/test_candidate.py"] if role == "tester" else []
    result = sessions(role=role, case_id=prefix + role, prompt=prompt,
                      workspace=target_run / "workspace" if role == "tester" else None,
                      writable=writable, evidence=evidence)
    scope = scope_diff(source_before, snapshot(target_run / "workspace"), writable)
    result.update(case_id=prefix + role, role=role, ordinal=1,
                  human_review_required=True, qualification_status="human-review-pending",
                  correctness="human-review-pending", deterministic_passed=None,
                  evidence_directory=str(evidence), scope=scope,
                  source_unchanged=snapshot(source_run / "workspace") == source_before)
    summary = {"campaign": record["packet_id"], "track": "advisory-role-probe", "results": [result],
               "planned_cases": 1, "completed_cases": 1, "qualification_status": "human-review-pending"}
    write_json(target_run / "summary.json", summary)
    return summary
