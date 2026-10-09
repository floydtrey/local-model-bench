"""Canonical Worker inputs; thin adapters over the existing project engine.

No inference, execution authority, or seed approval is inferred from role prose.
"""
from __future__ import annotations

from functools import partial
import json
from pathlib import Path
import shutil

from localbench.assistant001 import packet as a001
from localbench.assistant002 import packet as a002
from localbench.assistant001.assessment import assess
from localbench.assistant001.campaign import run_worker_chain
from localbench.assistant001.packet import digest, snapshot, scope_diff, write_json
from localbench.v2.contracts import sha256_json
from .planner_packet import read_regular

APIS = {"assistant-001": a001, "assistant-002": a002}
MODES = ("ISOLATED_TASK", "CUMULATIVE_PROJECT")
VERSION = "qualification-v2/worker-handoff-v1"


def read_json(path):
    return json.loads(read_regular(Path(path)))


def canonical(project, repo):
    """Assemble only reviewed-source candidates, never a Governor response."""
    api = APIS[project]
    packet, packet_hash = api.validate_packet(repo)
    root = api.packet_root(repo)
    reference = root.parent / "qualification-v2"
    governor = Path(repo) / "docs/qualification-v2/governor-v1" / project
    oracle = json.loads((governor / "oracle.json").read_text(encoding="utf-8"))["cases"][0]
    inputs = json.loads((governor / "inputs.json").read_text(encoding="utf-8"))["cases"][0]
    sources = [root / n for n in api.DOCS] + [reference / "REFERENCE_PLAN.md",
        reference / "TRACEABILITY.json", governor / "inputs.json", governor / "oracle.json",
        Path(repo) / "docs/qualification-v2/governor-v1/canonical-provenance.json"]
    tasks_text = (root / "TASKS.md").read_text(encoding="utf-8")
    return {"schema_version": VERSION, "project": project,
        "packet_sha256": packet_hash,
        "source_hashes": {p.relative_to(repo).as_posix(): digest(p) for p in sources},
        "reference_plan": (reference / "REFERENCE_PLAN.md").read_text(encoding="utf-8"),
        "project_intent": (root / "PROJECT_INTENT.md").read_text(encoding="utf-8"),
        "acceptance_contract": (root / "CONTRACT.md").read_text(encoding="utf-8"),
        "governor_constraints": oracle["restrictions"],
        "governor_case_id": oracle["case_id"],
        "simulation_conditions": inputs["simulation_conditions"],
        "governor_origin": oracle["oracle_origin"],
        "reference_review_status": "HUMAN_REVIEW_PENDING",
        "authorization": {"origin": "user_request_batch4_implementation_only",
            "scope": "construct benchmark reference bundles and deterministic tests",
            "model_inference": False, "host_execution": False,
            "exceptions": [], "execution_authority": False},
        "tools": ["list_files", "read_file", "write_file", "run_tests"],
        "session_policy": "fresh RoleConversation per task; actual predecessor prose only",
        "tasks": [{**t, "acceptance_requirements": t["requirements"],
            "assigned_task": "## " + t["id"] + ":" + tasks_text.split("## " + t["id"] + ":", 1)[1].split("\n## T", 1)[0],
            "previous_handoff_slot": None if t["id"] == "T01" else "actual accepted candidate predecessor only"}
            for t in packet["tasks"]]}


def load_canonical(project, repo):
    path = APIS[project].packet_root(repo).parent / "qualification-v2/WORKER_HANDOFF_V1.json"
    value = read_json(path)
    if value != canonical(project, repo):
        raise ValueError("Canonical Worker bundle differs from versioned source")
    return value


def validate_seed(project, task, seed_run, *, repo, allow_host_execution=False, assessor=None):
    """Capture existing assessor observations before candidate trials.

    A human must separately attest that the target is unsolved: a failing test
    alone cannot establish absence of a partial or hidden target solution.
    """
    if not allow_host_execution:
        raise ValueError("Seed validation requires separate host-execution authorization")
    api = APIS[project]
    bundle = load_canonical(project, repo)
    if task not in [t["id"] for t in bundle["tasks"]]:
        raise ValueError("Unknown task")
    run = Path(seed_run)
    api.read_run(run, repo)
    if (run / "seed-validation.json").exists():
        raise ValueError("Seed validation is immutable; use a fresh seed run")
    before = snapshot(run / "workspace")
    check = assessor or partial(assess, packet_api=api)
    predecessor = None if task == "T01" else f"T0{int(task[-1])-1}"
    evidence = {}
    for stage in ([predecessor] if predecessor else []) + [task]:
        result, path = check(run, stage, repo=repo, allow_host_execution=True,
                             before=before, writable=[])
        evidence[stage] = {"assessment": result, "assessment_sha256": digest(path / "assessment.json")}
    unchanged = snapshot(run / "workspace") == before
    target = evidence[task]["assessment"]
    valid_target = (target.get("status") == "completed" and target.get("passed") is False and bool(target.get("checks"))
                    and target.get("executed") == target.get("planned") == len(target["checks"])
                    and any(r.get("passed") is False for r in target["checks"]))
    valid = unchanged and valid_target and (predecessor is None or (
        evidence[predecessor]["assessment"].get("passed") is True
        and evidence[predecessor]["assessment"].get("status") == "completed"))
    record = {"schema_version": "qualification-v2/worker-seed-v1", "project": project,
        "task": task, "predecessor": predecessor, "bundle_sha256": sha256_json(bundle),
        "workspace_sha256": before, "evidence": evidence, "prevalidated": valid,
        "target_unsolved_review": "HUMAN_REVIEW_PENDING", "os_sandbox": False}
    write_json(run / "seed-validation.json", record)
    return record


def prepare_worker(project, mode, output_root, *, repo, task="T01", seed_run=None):
    if mode not in MODES:
        raise ValueError("Unknown Worker mode")
    if mode == "CUMULATIVE_PROJECT" and task != "T01":
        raise ValueError("Cumulative qualification starts at T01; select its end with through")
    protected = (Path(repo) / "project-benchmarks").resolve()
    output = Path(output_root).resolve()
    if output == protected or protected in output.parents:
        raise ValueError("Worker output must be outside protected benchmark inputs")
    bundle = load_canonical(project, repo)
    if task not in [t["id"] for t in bundle["tasks"]]:
        raise ValueError("Unknown task")
    seed = None
    if mode == "ISOLATED_TASK":
        if seed_run is None:
            raise ValueError("Isolated tasks require a separately prevalidated seed")
        seed_run = Path(seed_run)
        seed = read_json(seed_run / "seed-validation.json")
        for relative in snapshot(seed_run / "workspace"):
            read_regular(seed_run / "workspace" / relative)
        if (seed.get("schema_version") != "qualification-v2/worker-seed-v1"
                or seed.get("project") != project or seed.get("task") != task
                or seed.get("bundle_sha256") != sha256_json(bundle)
                or seed.get("prevalidated") is not True
                or seed.get("workspace_sha256") != snapshot(seed_run / "workspace")):
            raise ValueError("Seed prerequisites are absent, failed, stale or mismatched")
    elif seed_run is not None:
        raise ValueError("Cumulative projects cannot accept a reference seed")
    api = APIS[project]
    # Both modes use the original materializer and original run identity.
    run = api.prepare(output_root, repo=repo, label="worker-v2")
    if seed is not None:
        # Copy files only, once, before any candidate session; no replacement on failure.
        workspace = run / "workspace"
        for path in workspace.rglob("*"):
            if path.is_file():
                path.unlink()
        shutil.copytree(seed_run / "workspace", workspace, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    before = snapshot(run / "workspace")
    if seed is not None and (before != seed["workspace_sha256"] or snapshot(seed_run / "workspace") != before):
        raise ValueError("Seed changed during materialization")
    record, _ = api.read_run(run, repo)
    record["candidate_initial_sha256"] = before
    write_json(run / "run.json", record)
    control = {"schema_version": VERSION, "project": project, "worker_mode": mode,
        "task": task, "bundle": bundle, "bundle_sha256": sha256_json(bundle),
        "initial_workspace_sha256": before, "seed": seed,
        "input_sha256": sha256_json({"bundle": bundle, "mode": mode, "task": task,
                                     "workspace": before, "seed": seed}),
        "human_review_status": "HUMAN_REVIEW_PENDING", "execution_authority": False}
    write_json(run / "worker-input.json", control)
    return run


def verify_worker(run, repo):
    run = Path(run)
    control = read_json(run / "worker-input.json")
    bundle = load_canonical(control["project"], repo)
    if control["worker_mode"] not in MODES or control["bundle"] != bundle or control["bundle_sha256"] != sha256_json(bundle):
        raise ValueError("Worker input/source binding mismatch")
    expected = sha256_json({"bundle": bundle, "mode": control["worker_mode"], "task": control["task"],
                           "workspace": control["initial_workspace_sha256"], "seed": control["seed"]})
    record, _ = APIS[control["project"]].read_run(run, repo)
    if control["input_sha256"] != expected or record["candidate_initial_sha256"] != control["initial_workspace_sha256"]:
        raise ValueError("Worker input identity mismatch")
    if control["task"] not in [t["id"] for t in bundle["tasks"]]:
        raise ValueError("Unknown task")
    return control


def authorize(control, authorization_file, trusted_sha256):
    """Operator-selected private trust anchor, NOT a candidate-supplied permit.

    Selecting a digest is an explicit operator adoption of this bounded release;
    hashes bind bytes, they do not authenticate a person or Owner identity.
    """
    if not authorization_file or not trusted_sha256 or digest(authorization_file) != trusted_sha256:
        raise ValueError("Missing trusted operator authorization digest")
    grant = read_json(authorization_file)
    required = {"schema_version": "qualification-v2/worker-authorization-v1",
        "origin": "trusted_operator", "input_sha256": control["input_sha256"],
        "bundle_sha256": control["bundle_sha256"], "reference_review": "approved",
        "allow_model_inference": True, "allow_host_execution": True, "exceptions": []}
    if any(grant.get(k) != v for k, v in required.items()) or not grant.get("provenance_reference"):
        raise ValueError("Authorization is absent, unreviewed, simulated, model-origin or out of scope")
    if control["seed"] is not None and (grant.get("seed_validation_sha256") != sha256_json(control["seed"])
            or grant.get("target_unsolved_review") != "approved"):
        raise ValueError("Isolated seed lacks trusted prerequisite and unsolved-target review")
    return {"authorization_sha256": trusted_sha256, "origin": grant["origin"],
            "provenance_reference": grant["provenance_reference"]}


def authorize_run(run, control, authorization_file, trusted_sha256):
    """Apply the same placement boundary before provider construction and dispatch."""
    if authorization_file is not None:
        auth = Path(authorization_file).resolve()
        workspace = (Path(run) / "workspace").resolve()
        if auth == workspace or workspace in auth.parents:
            raise ValueError("Authorization must be outside the candidate workspace")
    return authorize(control, authorization_file, trusted_sha256)


class WorkerPacket:
    """Add canonical context to original task prompts; reuse original run loader."""
    def __init__(self, api, control):
        self.api, self.control = api, control

    def read_run(self, run, repo=None):
        record, packet = self.api.read_run(run, repo)
        if self.control["worker_mode"] == "ISOLATED_TASK":
            packet = {**packet, "tasks": [t for t in packet["tasks"] if t["id"] == self.control["task"]]}
        return record, packet

    def task_prompt(self, run, task, previous_handoff, repo=None):
        before = snapshot(Path(run) / "workspace")
        evidence = Path(run) / "canonical-handoffs" / task
        handoff = {"schema_version": VERSION, "input_sha256": self.control["input_sha256"],
            "bundle_sha256": self.control["bundle_sha256"], "worker_mode": self.control["worker_mode"],
            "starting_workspace_sha256": before, "previous_handoff": previous_handoff,
            "previous_handoff_origin": "actual_candidate" if previous_handoff else "none",
            "task": task, "authorization": self.control["release"]}
        write_json(evidence / "canonical-handoff.json", handoff)
        return self.api.task_prompt(run, task, previous_handoff, repo) + "\n# Canonical reference input\n" + json.dumps({
            "reference_plan": self.control["bundle"]["reference_plan"],
            "governor_constraints": self.control["bundle"]["governor_constraints"],
            "handoff": handoff}, sort_keys=True)


def run_worker(run, sessions, *, repo, authorization_file=None, trusted_sha256=None,
               allow_model_inference=False, allow_host_execution=False, through="T06", assessor=None):
    if not allow_model_inference or not allow_host_execution:
        raise ValueError("Separate model inference and host execution consent required")
    control = verify_worker(run, repo)
    run = Path(run)
    control["release"] = authorize_run(run, control, authorization_file, trusted_sha256)
    if (run / "summary.json").exists() or (run / "roles").exists():
        raise ValueError("Every Worker trial requires a fresh prepared run")
    if snapshot(run / "workspace") != control["initial_workspace_sha256"]:
        raise ValueError("Worker starting workspace changed before execution")
    api = APIS[control["project"]]
    underlying = assessor or partial(assess, packet_api=api)

    def scoped_assessor(run, task, **kwargs):
        scope = scope_diff(kwargs["before"], snapshot(Path(run) / "workspace"), kwargs["writable"])
        if not scope["passed"]:
            path = Path(run) / "assessments" / (task + "-scope")
            result = {"passed": False, "status": "scope_failure", "scope": scope}
            write_json(path / "assessment.json", result)
            return result, path
        return underlying(run, task, **kwargs)

    # Existing cumulative engine also handles the one-task view; no new controller.
    summary = run_worker_chain(run, sessions, repo=repo, allow_host_execution=True,
        through=control["task"] if control["worker_mode"] == "ISOLATED_TASK" else through,
        assessor=scoped_assessor, packet_api=WorkerPacket(api, control))
    summary.update(track="CONTROLLED_ROLE_QUALIFICATION", worker_mode=control["worker_mode"],
        canonical_input_sha256=control["input_sha256"], reference_bundle_sha256=control["bundle_sha256"],
        authorization=control["release"], seed_validation_sha256=sha256_json(control["seed"]) if control["seed"] else None)
    for row in summary["results"]:
        status = row.get("assessment_status")
        row["failure_attribution"] = ("predecessor" if row["status"] == "blocked" else
            "infrastructure" if row["status"] == "error" or status in (
                "assessor_result_missing_or_invalid", "assessor_timeout", "assessor_output_limit") else
            "scope" if status == "scope_failure" else
            "worker" if row.get("deterministic_passed") is not True else None)
        row["assessment_outcome"] = ("unknown" if row["failure_attribution"] in ("predecessor", "infrastructure")
                                     else "pass" if row.get("deterministic_passed") else "fail")
        row["worker_mode"] = control["worker_mode"]
        row["input_sha256"] = control["input_sha256"]
        row["track"] = summary["track"]
        row["reference_bundle_sha256"] = control["bundle_sha256"]
        row["authorization_sha256"] = control["release"]["authorization_sha256"]
        row["seed_validation_sha256"] = summary["seed_validation_sha256"]
        row["execution_status"] = "blocked" if row["status"] == "blocked" else "failed" if row["status"] == "error" else "completed"
        row["assessed_outcome"] = row["assessment_outcome"]
        row["human_review_status"] = "pending"
        row.update(suite_id=VERSION, suite_version="1", rubric_id="assistant-project-acceptance:v1",
                   rubric_version="assistant-project-acceptance:v1", run_id=run.name,
                   trial_id=run.name, attempt_id=run.name + "-" + row["case_id"], attempt_index=1,
                   reference_sha256=control["bundle_sha256"],
                   authority_assumptions={"scope": "bounded_worker_benchmark", "worker_mode": control["worker_mode"]},
                   assessor_version="assistant-project-acceptance:v1", evidence_version=VERSION)
        assessment_path = Path(row["assessment_file"]) if row.get("assessment_file") else None
        if assessment_path and assessment_path.is_file():
            from localbench.v2.report_adapter import file_reference
            assessment_record = json.loads(read_regular(assessment_path))
            row["evidence_refs"] = [file_reference(assessment_path, "assessment")]
            row["artifact_sha256"] = assessment_record.get("candidate_sha256")
            row["candidate_sha256"] = assessment_record.get("candidate_sha256")
            row["acceptance_check_count"] = assessment_record.get("executed")
        row["reference_review_status"] = "operator-reviewed-for-this-release"
        if row["failure_attribution"] == "infrastructure":
            row["deterministic_passed"] = row["first_pass_passed"] = None
    verify_worker(run, repo)
    write_json(run / "summary.json", summary)
    return summary
