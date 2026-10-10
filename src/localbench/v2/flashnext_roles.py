"""Additive Flash-Next role campaign on V2 immutable evidence primitives.

The caller owns runtime identity verification, the shared-screen gate, telemetry,
and runtime custody. This module never starts a runtime or substitutes a model.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .compatibility import CompatibilityDimension, compatibility_observation, seal_compatibility_observation
from .contracts import SealedEvidence, canonical_json_bytes, seal_evidence, sha256_json
from .evaluators import EvaluationCheck
from .flashnext_role_harness import (
    ROLE_SURFACE_ID, ROLE_TOOL_DEFINITIONS, ROLE_TOOL_SCHEMA_SHA256,
    RoleConversation, file_snapshot, snapshot_diff, run_python_check,
    test_infrastructure_ok, write_json,
)
from .orchestrator import EvidenceStore
from .flashnext_role_trace import ROLE_TRACE_VERSION, validate_role_execution_trace
from .records import (
    benchmark_input, case_result, evaluation_result, evaluator_identity,
    execution_binding, run_manifest, trial_identity,
)
from .tool_harness import BoundedWorkspace

ROLE_NAMES = ("planner", "governor", "worker", "tester", "reviewer")
SOURCE_COMMIT = "fce91a7fa409aecd824a3fa1229724b0aab56812"
ROLE_CAMPAIGN_VERSION = "flashnext-all-roles:v1"
WORKER_READY_SUFFIX = (
    "\n\nThis turn establishes your Worker role only. Do not inspect the workspace, "
    "call tools, or begin project work yet. The bounded dispatch will arrive in the "
    "next user message. Reply exactly: WORKER_READY\n"
)
TESTER_READY_SUFFIX = (
    "\n\nThis turn establishes your Tester role only. Do not inspect the workspace, "
    "call tools, or begin testing yet. The completed Worker task will arrive in the "
    "next user message. Reply exactly: TESTER_READY\n"
)
GOVERNOR_GUIDANCE = (
    "ALL: Preserve existing public interfaces and existing behavior unless the supplied "
    "project intent explicitly requires a change. Prefer the smallest change that fully "
    "satisfies the supplied project intent. Reuse the project's existing structure and "
    "conventions. Do not add unrelated refactors, dependencies, documentation, infrastructure, "
    "abstractions, or features."
)
# Exact benchmark-owned acceptance script from the historical Test 01 runner.
CONFIG_BEHAVIOR_SCRIPT = '''from reporting.config import ReportConfig

assert ReportConfig().title == "Report", "default title missing or incorrect"
assert ReportConfig(title="Custom").title == "Custom", "custom title construction failed"
print("CONFIG_BEHAVIOR_PASS")
'''


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def verify_source_manifest(root: Path) -> list[dict[str, Any]]:
    manifest = json.loads(_text(root / "SOURCE_MANIFEST.json"))
    if manifest.get("source_commit") != SOURCE_COMMIT:
        raise ValueError("historical role source revision mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("historical source manifest is empty")
    for item in files:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("source manifest path escapes source root")
        path = root / relative
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError(f"historical source changed: {relative}")
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != item["source_git_blob"]:
            raise ValueError(f"historical source Git blob changed: {relative}")
    return files


def build_role_cases(campaign_root: Path, role: str, *, governor_root: Path | None = None) -> list[dict[str, Any]]:
    """Build established fixtures without contacting a model or modifying sources."""
    if role not in ROLE_NAMES:
        raise ValueError(f"unknown role: {role}")
    if role in {"planner", "governor", "reviewer"}:
        from .flashnext_role_packets import build_role_cases as text_cases
        return text_cases(campaign_root, role, governor_root=governor_root)
    root = Path(campaign_root) / "sources" / "local-model-bench"
    entries = verify_source_manifest(root)
    source = root / "benchmark"

    def refs(paths: Sequence[str]) -> list[dict[str, Any]]:
        return [{**item, "local_path": str(root / item["path"])} for item in entries if any(item["path"] == p or item["path"].startswith(p + "/") for p in paths)]

    if role == "worker":
        setup = _text(source / "worker/ROLE_PROMPT.md") + WORKER_READY_SUFFIX
        common = {"role": role, "setup_prompt": setup, "setup_expected_marker": "WORKER_READY", "qualification_status": "unqualified", "correctness": "pending", "tools": [x["name"] for x in ROLE_TOOL_DEFINITIONS]}
        title = {
            **common, "case_id": "worker-title-task-01", "evaluator": "worker-title",
            "fixture_path": str(source / "worker/fixture-01"),
            "task_prompt": _text(source / "worker/fixture-01/DISPATCH_TASK_01.md"),
            "write_paths": ["reporting/config.py"], "max_repairs": 0,
            "source_refs": refs(["benchmark/worker/ROLE_PROMPT.md", "benchmark/worker/fixture-01"]),
            "expected_observations": {"only_changed_path": "reporting/config.py", "default_title": "Report", "custom_title": "Custom", "later_tasks_untouched": True},
        }
        intent = _text(source / "planner/intent-04-batch-export.md")
        plan = _text(source / "governor/plans/plan-b-medium.md")
        cases = [title]
        for stage in (1, 2, 3):
            task = _text(source / f"worker/intent04/TASK_0{stage}.md")
            prompt = (
                f"# Worker Dispatch - Intent 04 / Task {stage}\n\n## Original project intent\n\n{intent}\n"
                f"## Full approved plan\n\n{plan}\n## Assigned bounded task\n\n{task}\n"
                f"## Governor intent guidance\n\n{GOVERNOR_GUIDANCE}\n\n"
                "## Prerequisite handoff\n\n{prerequisite_handoff}\n\n"
                f"## Authority boundary\n\nYou are authorized to execute Task {stage} only. The complete approved plan is context, "
                "not authority to perform later tasks. Modify only the file explicitly authorized by the assigned task. "
                "Do not create helper files or other artifacts unless the assigned task explicitly authorizes them.\n"
            )
            cases.append({
                **common, "case_id": f"worker-intent04-task-0{stage}", "evaluator": "worker-intent04",
                "scenario": "intent04", "stage": stage, "task_prompt": prompt,
                "fixture_path": str(source / "worker/fixture-02"), "write_paths": ["inventory/cli.py"],
                "fixture_additions": {"PROJECT_INTENT.md": intent, "APPROVED_PLAN.md": plan},
                "max_repairs": 1,
                "verifier_path": str(source / "worker/intent04/verify_stage.py"),
                "criteria_path": str(source / "worker/intent04/ASSESSOR_CRITERIA.json"),
                "source_refs": refs(["benchmark/worker/ROLE_PROMPT.md", "benchmark/worker/fixture-02", "benchmark/worker/intent04", "benchmark/planner/intent-04-batch-export.md", "benchmark/governor/plans/plan-b-medium.md"]),
                "expected_observations": {"assigned_stage_only": stage, "only_changed_path": "inventory/cli.py", "existing_tests_unchanged": True, "handoff_required": True},
            })
        return cases

    cases = []
    for letter, initial, final, decision, change in (("a", 0, 0, "PASS", False), ("c", 0, 1, "FAIL", True), ("d", 1, 0, "PASS", True)):
        fixture = source / f"tester/fixtures/case-{letter}"
        prompt = (
            f"# Tester Dispatch — Case {letter.upper()}\n\n## Original project intent\n\n{_text(fixture / 'PROJECT_INTENT.md')}\n"
            f"## Full approved plan\n\n{_text(fixture / 'APPROVED_PLAN.md')}\n"
            f"## Completed Worker task\n\n{_text(fixture / 'ASSIGNED_TASK.md')}\n"
            f"## Worker handoff\n\n{_text(fixture / 'WORKER_HANDOFF.md')}\n"
            "## Tester authority\n\nEvaluate the completed Worker task only.\n"
            "You may read any project file and run focused tests.\n"
            "You may modify tests/test_discount.py or create tests/test_qualification.py when needed to establish valid coverage.\n"
            "Do not modify production code or project requirements.\nUse actual deterministic test execution as evidence.\n"
            "Return a clear PASS, FAIL, or BLOCKED routing decision, then write the rest of the response naturally as the handoff to the next role. "
            "Do not fit the findings into a fixed form or exact set of labels.\n"
        )
        cases.append({
            "case_id": f"tester-case-{letter}", "role": role, "evaluator": f"tester-{letter}",
            "setup_prompt": _text(source / "tester/ROLE_PROMPT.md") + TESTER_READY_SUFFIX,
            "setup_expected_marker": "TESTER_READY", "task_prompt": prompt,
            "fixture_path": str(fixture), "write_paths": ["tests/test_discount.py", "tests/test_qualification.py"],
            "max_repairs": 0, "qualification_status": "partial-corpus-unqualified", "correctness": "pending",
            "expected_preflight_exit": initial, "expected_final_exit": final,
            "expected_decision": decision, "require_test_change": change,
            "correct_implementation_path": str(source / "tester/fixtures/case-a/pricing/discount.py"),
            "defective_implementation_path": str(source / "tester/fixtures/case-c/pricing/discount.py"),
            "source_refs": refs(["benchmark/tester/ROLE_PROMPT.md", "benchmark/tester/QUALIFICATION_PLAN.md", f"benchmark/tester/fixtures/case-{letter}", "benchmark/tester/fixtures/case-a/pricing/discount.py", "benchmark/tester/fixtures/case-c/pricing/discount.py"]),
            "fixture_transformations": [{"kind": "bounded_tool_interface", "detail": "Historic tests-directory authority mapped to two exact test paths; fixed no-argument unittest runner; pricing test-source inspection; original role prompt unchanged."}],
            "expected_observations": {"decision": decision, "test_change_required": change, "production_changes_forbidden": True},
        })
    return cases


def _check(check_id: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"check_id": check_id, "passed": bool(passed), "detail": detail}


def _worker_handoff(text: str) -> str | None:
    match = re.search(r"(?ims)^\s*(?:\*\*)?Handoff note:(?:\*\*)?\s*(.*)$", text)
    if match is None or not match.group(1).strip():
        return None
    return "Handoff note: " + match.group(1).strip()


def _workspace_for(spec: Mapping[str, Any], root: Path, *, reuse: bool) -> tuple[BoundedWorkspace | None, dict[str, str]]:
    fixture = spec.get("fixture_path")
    if fixture is None:
        return None, {}
    if not reuse:
        if root.exists():
            raise ValueError(f"refusing to overwrite workspace: {root}")
        shutil.copytree(Path(fixture), root)
        for relative, value in spec.get("fixture_additions", {}).items():
            (root / relative).write_text(value, encoding="utf-8")
    elif not root.is_dir():
        raise ValueError("required predecessor workspace is missing")
    paths = sorted(file_snapshot(root))
    for p in spec.get("write_paths", []):
        if p not in paths:
            paths.append(p)
    workspace = BoundedWorkspace(root, readable_paths=paths, writable_paths=spec.get("write_paths", []))
    return workspace, file_snapshot(root)


def _assessment(spec: Mapping[str, Any], session: RoleConversation, before: Mapping[str, str], folder: Path, label: str) -> dict[str, Any]:
    if session.workspace is None:
        return {"deterministic_passed": None, "checks": [], "human_review_required": True, "expected_observations": spec.get("expected_observations", {})}
    root = session.workspace.root
    diff = snapshot_diff(before, file_snapshot(root))
    changed = diff["changed"] + diff["created"] + diff["deleted"]
    allowed = set(spec["write_paths"])
    checks = [
        _check("runtime-completed", session.status == "success", session.stop_reason),
        _check("no-denied-tool-requests", session.denied_calls == 0, "All exposed file/test requests respected assigned authority."),
        _check("file-scope", all(p in allowed for p in changed), json.dumps(diff)),
    ]
    tester = spec["role"] == "tester"
    def run_check(workspace: Path, name: str, **kwargs: Any) -> dict[str, Any]:
        remaining = max(0.01, min(120, session.deadline - time.monotonic()))
        return run_python_check(workspace, folder, name, timeout_seconds=remaining, **kwargs)

    regressions = run_check(root, f"{label}-regressions", inspect_tester_tests=tester)
    infrastructure_ok = test_infrastructure_ok(regressions)
    result: dict[str, Any] = {"diff": diff, "regressions": regressions, "infrastructure_ok": infrastructure_ok, "checks": checks, "human_review_required": True}
    if spec["role"] == "worker":
        checks += [
            _check("existing-regressions", infrastructure_ok and regressions["exit_code"] == 0, "Unchanged existing test suite must succeed."),
            _check("required-change", diff["changed"] == spec["write_paths"] and not diff["created"] and not diff["deleted"], "Exactly the assigned implementation file changes."),
            _check("handoff-present", _worker_handoff(session.final) is not None, "Established Worker handoff marker and nonempty note are present; usefulness still needs review."),
        ]
        if spec["evaluator"] == "worker-title":
            script = folder / "verify-config.py"
            script.write_text(CONFIG_BEHAVIOR_SCRIPT, encoding="utf-8")
            behavior = run_check(root, f"{label}-behavior", script=script)
            checks.append(_check("config-behavior", test_infrastructure_ok(behavior) and behavior["exit_code"] == 0, "Historical default/custom title constructor checks."))
            result["behavior"] = behavior
            result["infrastructure_ok"] &= test_infrastructure_ok(behavior)
        else:
            behavior = run_check(root, f"{label}-behavior", script=Path(spec["verifier_path"]), stage=spec["stage"])
            try:
                parsed = json.loads(behavior["stdout"])
                parse_ok = isinstance(parsed, dict) and isinstance(parsed.get("passed"), bool)
            except (json.JSONDecodeError, TypeError):
                parsed, parse_ok = None, False
            checks.append(_check("historical-stage-checks", test_infrastructure_ok(behavior) and parse_ok and parsed["passed"] and behavior["exit_code"] == 0, "Unchanged historical verifier outside the Worker workspace."))
            result.update({"behavior": behavior, "historical_verifier": parsed})
            result["infrastructure_ok"] &= test_infrastructure_ok(behavior) and parse_ok
    else:
        # Preserve free prose: routing extraction is diagnostic, never the sole verdict.
        # Routing can be embedded in an ordinary sentence. Ambiguous status
        # mentions are reviewed by a human; no heading or sentence form is a gate.
        decisions = re.findall(r"\b(PASS|FAIL|BLOCKED)\b", session.final)
        decision = decisions[0] if len(set(decisions)) == 1 else None
        result["observed_decision"] = decision
        result["routing_requires_human_review"] = True
        checks += [
            _check("expected-routing-diagnostic", decision == spec["expected_decision"], "Routing agrees with known fixture ground truth; substantive handoff review remains required."),
            _check("model-ran-deterministic-tests", any(test_infrastructure_ok(r) for r in session.test_calls), "Tester itself invoked the fixed deterministic test tool."),
            _check("test-change-decision", bool(changed) == spec["require_test_change"], "A reuses adequate tests; C/D require a focused coverage or bad-test repair."),
            _check("expected-test-result", infrastructure_ok and regressions["exit_code"] == spec["expected_final_exit"], "Independent rerun matches fixture expectation."),
        ]
        oracle_results = {}
        for kind, expected_exit in (("correct", 0), ("defective", 1)):
            oracle = folder / f"{label}-oracle-{kind}"
            shutil.copytree(root, oracle)
            (oracle / "pricing/discount.py").write_bytes(Path(spec[f"{kind}_implementation_path"]).read_bytes())
            run = run_check(oracle, f"{label}-oracle-{kind}-tests", inspect_tester_tests=True)
            oracle_results[kind] = run
            checks.append(_check(f"tests-on-known-{kind}-implementation", test_infrastructure_ok(run) and run["exit_code"] == expected_exit, "The test suite must accept the known-correct historical implementation and expose the known VIP defect."))
            result["infrastructure_ok"] &= test_infrastructure_ok(run)
        result["oracle_validation"] = oracle_results
    final_diff = snapshot_diff(before, file_snapshot(root))
    final_changed = final_diff["changed"] + final_diff["created"] + final_diff["deleted"]
    result["diff_after_independent_checks"] = final_diff
    checks.append(_check("final-file-scope", all(p in allowed for p in final_changed), "Whole workspace hashed again after independent tests: " + json.dumps(final_diff)))
    if spec["role"] == "worker":
        checks.append(_check("final-required-change", final_diff["changed"] == spec["write_paths"] and not final_diff["created"] and not final_diff["deleted"], "Assigned change is still the entire final artifact diff after verification."))
    required_checks = [check for check in checks if check["check_id"] != "expected-routing-diagnostic"]
    result["deterministic_passed"] = result["infrastructure_ok"] and all(x["passed"] for x in required_checks)
    write_json(folder / f"{label}-assessment.json", result)
    return result


def _repair_packet(spec: Mapping[str, Any], assessment: Mapping[str, Any]) -> str | None:
    criteria = json.loads(_text(Path(spec["criteria_path"]))) ["checks"]
    failures = list((assessment.get("historical_verifier") or {}).get("failures", []))
    mapping = {"file-scope": "WORKER-SCOPE-CHANGED", "final-file-scope": "WORKER-SCOPE-CHANGED", "required-change": "WORKER-REQUIRED-CHANGE-MISSING", "final-required-change": "WORKER-REQUIRED-CHANGE-MISSING", "existing-regressions": "WORKER-EXISTING-REGRESSION", "handoff-present": "WORKER-HANDOFF-MISSING"}
    for check in assessment["checks"]:
        if not check["passed"] and check["check_id"] in mapping:
            failures.append({"check_id": mapping[check["check_id"]], "observed": check["detail"]})
    diff = assessment.get("diff", {})
    for key, check_id in (("created", "WORKER-SCOPE-CREATED"), ("deleted", "WORKER-SCOPE-DELETED")):
        if diff.get(key):
            failures.append({"check_id": check_id, "observed": ", ".join(diff[key])})
    if not failures:
        # A denied tool attempt cannot be undone by an implementation repair.
        # Never invent repair wording outside the fixed historical criteria.
        return None
    lines = ["# Task repair", "", f"The deterministic test step found the following problem(s) in Intent 04 / Task {spec['stage']}.", "Repair the current task only. Use the current workspace and preserve behavior that already passes.", ""]
    for failure in failures:
        check_id = failure["check_id"]
        if check_id not in criteria:
            raise ValueError(f"No historical repair criterion exists for {check_id}")
        lines += [f"## {check_id}", f"Observed: {failure.get('observed', '')}", f"Required repair: {criteria[check_id]['repair_criterion']}", ""]
    lines += ["Authorized implementation file: inventory/cli.py", "Do not modify tests. Do not begin the next plan task. Do not create helper files.", "When finished, stop. Your final response must end with Handoff note: followed by the concise information needed by the next dependent Worker."]
    return "\n".join(lines)


def portable_role_input(value: Any) -> Any:
    """Project source identity without host-specific locator spelling.

    The full local locators remain in input.json and the execution manifest.
    Runtime-dispatched bytes receive a separate pre-run manifest hash.
    """
    locators = {"fixture_path", "verifier_path", "criteria_path", "correct_implementation_path", "defective_implementation_path"}
    if isinstance(value, Mapping):
        projected = {}
        for key, item in value.items():
            if key == "local_path":
                continue
            if key in locators and isinstance(item, str):
                path = item.replace("\\", "/")
                projected[key] = "sources/" + path.split("/sources/", 1)[1] if "/sources/" in path else path.rsplit("/", 1)[-1]
            else:
                projected[key] = portable_role_input(item)
        return projected
    if isinstance(value, (list, tuple)):
        return [portable_role_input(item) for item in value]
    return value


def _dispatch_prompt(spec: Mapping[str, Any], workspace: BoundedWorkspace | None, prerequisite_handoff: str | None) -> str:
    prompt = spec["task_prompt"].replace("{prerequisite_handoff}", prerequisite_handoff or "No prerequisite handoff; this is the first task.")
    if workspace is not None:
        prompt += (
            "\n\n## V2 runtime and tool interface\n\n"
            f"The disposable project root is {workspace.root}. Use exact project-relative paths.\n"
            "Tools are read_file, write_file, and run_tests. run_tests takes {} and runs the existing Python unittest suite. "
            "There is no shell tool; do not issue shell commands. write_file requires the current read_file SHA256, or null when creating an authorized new file.\n"
            "Readable paths: " + ", ".join(workspace.readable_paths) + "\n"
            "Writable paths: " + ", ".join(workspace.writable_paths) + "\n"
        )
        if spec["role"] == "tester":
            prompt += "The controlled pricing-test tool supports unittest, pricing.discount.apply_discount, ordinary unittest.TestCase test_*(self) methods/assertions, local numeric data, and numeric builtins. It inspects tests before execution. It exposes no host/process/network imports, attribute traversal, assertion overrides, or arbitrary Python calls.\n"
    return prompt


def run_role_case(
    spec: Mapping[str, Any], *, foundation: Mapping[str, SealedEvidence],
    base_config_spec: Mapping[str, Any], driver_factory: Callable,
    evidence_store: EvidenceStore, output_dir: Path, ordinal: int,
    workspace_root: Path | None = None, reuse_workspace: bool = False,
    prerequisite_handoff: str | None = None, dependency_blocked: bool = False,
    case_context_factory: Callable | None = None,
    driver_binding: Mapping[str, Any] | None = None,
    case_publisher=None,
) -> dict[str, Any]:
    """Seal a single two-turn case before its first model call, then preserve all evidence."""
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=False)
    workspace, before = _workspace_for(spec, workspace_root or folder / "workspace", reuse=reuse_workspace) if not dependency_blocked else (None, {})
    tool_case = spec.get("fixture_path") is not None
    maximum_calls = 40
    configs, drivers = {}, {}
    for phase in ("setup", "dispatch"):
        config = json.loads(canonical_json_bytes(base_config_spec))
        config["generation"]["response_format"] = {"mode": "text", "schema": None}
        enabled = phase == "dispatch" and tool_case
        config["tool_surface"] = {
            "id": ROLE_SURFACE_ID if enabled else "none",
            "tools": [x["name"] for x in ROLE_TOOL_DEFINITIONS] if enabled else [],
            "max_tool_calls": maximum_calls if enabled else 0,
            "schema_sha256": ROLE_TOOL_SCHEMA_SHA256 if enabled else None,
        }
        driver = driver_factory(config, folder / "runtime" / phase)
        if not isinstance(getattr(driver, "effective_config", None), SealedEvidence):
            raise TypeError("driver_factory must return a driver exposing sealed effective_config")
        drivers[phase], configs[phase] = driver, driver.effective_config
    identity = f"{spec['case_id']}-r{ordinal}"
    timeout = configs["dispatch"].payload["limits"]["timeout_seconds"]
    bound_spec = dict(spec)
    bound_spec["prerequisite_handoff"] = prerequisite_handoff
    prompt = _dispatch_prompt(spec, workspace, prerequisite_handoff)
    benchmark = benchmark_input(
        identity + "-input", suite_id=ROLE_CAMPAIGN_VERSION,
        source_sha256=sha256_json(portable_role_input(bound_spec)), level="L3", case_ids=[spec["case_id"]],
        source_format="frozen-role-packet:v1", source_locator="campaigns/flashnext-all-roles-v1/role-suite.json",
    )
    implementation = sha256_json({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), Path(__file__).with_name("flashnext_role_harness.py"), Path(__file__).with_name("flashnext_role_packets.py"), Path(__file__).with_name("flashnext_role_trace.py"))})
    evaluator = evaluator_identity(
        identity + "-evaluator", evaluator_id="flashnext-role-observations:v1", version="1.0.0",
        implementation_sha256=implementation, result_contract="deterministic-observations-plus-human-review:v1", requires_human_review=True,
    )
    trial = trial_identity(identity + "-trial", layer="role", ordinal=ordinal, repeat_group=spec["case_id"], benchmark=benchmark.reference, case_id=spec["case_id"], effective_config=configs["dispatch"].reference)
    scope = workspace.scope() if workspace else None
    role_protocol = {
        "protocol": "established-user-role-then-user-dispatch:v1",
        "setup_effective_config": configs["setup"].reference.to_dict(),
        "dispatch_effective_config": configs["dispatch"].reference.to_dict(),
        "setup_prompt_sha256": hashlib.sha256(spec["setup_prompt"].encode("utf-8")).hexdigest(),
        "dispatch_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "max_model_turns": 48, "max_tool_calls": maximum_calls if tool_case else 0,
        "max_validation_retries": 2,
        "structured_recovery_policy": "schema-derived-lossless-json-literal:v1",
        "repetition_guard": "stop-after-initial-plus-two-identical-or-invalid-failures:v1",
        "max_repairs": spec.get("max_repairs", 0), "source_refs": spec.get("source_refs", []),
        "controls": {"scope": "exact-file-neutral-tools", "shell_access": False, "model_selects_process_arguments": False, "test_command": "python -B -m unittest discover -s tests -v", "test_source_inspection": "pricing-unittest-static-v1" if spec["role"] == "tester" else None, "os_isolation": False, "network_isolation": False, "case_watchdog": case_context_factory is not None},
    }
    bound_driver = dict(driver_binding or {
        "driver_id": "flashnext-role-conversation-v1",
        "implementation_sha256": implementation,
        "execution_kind": "in_process",
    })
    binding = execution_binding(
        identity + "-binding", trial=trial.reference, execution_mode="lab_tool" if tool_case else "intrinsic",
        driver=bound_driver,
        workspace_scope=scope, context_assets=[], execution_interface=foundation["interface"].reference,
        containment=None,
    )
    manifest = run_manifest(
        identity + "-manifest", host=foundation["host"].reference, runtime=foundation["runtime"].reference,
        model=foundation["model"].reference, effective_configs=[x.reference for x in configs.values()],
        benchmarks=[benchmark.reference], evaluators=[evaluator.reference], trials=[trial.reference], execution_bindings=[binding.reference],
        harness_source={"campaign": ROLE_CAMPAIGN_VERSION, "implementation_sha256": implementation, "role_protocol": role_protocol},
    )
    evidence_store.persist_many([*foundation.values(), *configs.values(), benchmark, evaluator, trial, binding, manifest])
    write_json(folder / "input.json", bound_spec)
    write_json(folder / "portable-input.json", portable_role_input(bound_spec))
    (folder / "dispatch.txt").write_bytes(prompt.encode("utf-8"))
    write_json(folder / "manifest.json", manifest.to_dict())
    write_json(folder / "workspace-before.json", before)
    publication_key = ("native-role", str(folder.resolve()), spec["case_id"], ordinal)
    if case_publisher is not None: case_publisher.started(key=publication_key)
    session = RoleConversation(
        case_id=spec["case_id"], setup_driver=drivers["setup"], driver=drivers["dispatch"],
        evidence_dir=folder, workspace=workspace, timeout_seconds=timeout,
        max_tool_calls=maximum_calls, max_validation_retries=2,
        inspect_tester_tests=spec["role"] == "tester",
    )
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    assessments: list[dict[str, Any]] = []
    preflight = None
    scope_before_tests = before
    context = case_context_factory(folder, trial) if case_context_factory else nullcontext()
    try:
        with context:
            if dependency_blocked:
                session.status, session.stop_reason = "blocked", "predecessor_not_accepted"
            else:
                preflight_ok = True
                if workspace is not None:
                    preflight = run_python_check(workspace.root, folder / "tests", "preflight", inspect_tester_tests=spec["role"] == "tester")
                    expected_exit = spec.get("expected_preflight_exit", 0)
                    preflight_ok = test_infrastructure_ok(preflight) and preflight["exit_code"] == expected_exit
                if not preflight_ok:
                    session.status, session.stop_reason = "blocked", "fixture_preflight_failure"
                elif session.establish(spec["setup_prompt"], spec.get("setup_expected_marker")):
                    session.dispatch(prompt)
                    if session.status == "success":
                        assessment = _assessment(spec, session, scope_before_tests, folder / "assessment", "first-pass")
                        assessments.append(assessment)
                        if assessment.get("infrastructure_ok") is False:
                            session.status, session.stop_reason = "blocked", "deterministic_test_interface_or_infrastructure_failure"
                        elif spec.get("max_repairs", 0) and assessment.get("deterministic_passed") is False:
                            repair = _repair_packet(spec, assessment)
                            if repair is not None:
                                (folder / "repair-packet.txt").write_text(repair, encoding="utf-8")
                                session.dispatch(repair, phase="repair")
                                if session.status == "success":
                                    repaired = _assessment(spec, session, scope_before_tests, folder / "assessment", "repair")
                                    assessments.append(repaired)
                                    if repaired.get("infrastructure_ok") is False:
                                        session.status, session.stop_reason = "blocked", "deterministic_test_interface_or_infrastructure_failure"
    except Exception as exc:
        session.status, session.stop_reason = "error", "campaign_harness_or_watchdog_failure"
        session.event("harness_error", {"error_type": type(exc).__name__, "detail": str(exc), "correctness": "not_assessed"})
    finished_at = datetime.now(timezone.utc).isoformat()
    wall_seconds = time.monotonic() - started
    final_assessment = assessments[-1] if assessments else None
    deterministic = final_assessment.get("deterministic_passed") if final_assessment else None
    if session.status != "success":
        correctness = "not-assessed-incomplete-or-incompatible"
    elif deterministic is None:
        correctness = "human-review-pending"
    else:
        correctness = "deterministic-pass-review-pending" if deterministic else "deterministic-fail-review-pending"
    after = file_snapshot(workspace.root) if workspace else {}
    write_json(folder / "workspace-after.json", after)
    metrics = {**session.metrics(), "wall_seconds": wall_seconds, "ordinal": ordinal}
    metrics["overall_output_tokens_per_second"] = metrics["output_tokens"] / wall_seconds if metrics["output_tokens"] is not None and wall_seconds else None
    trace = seal_evidence("role_execution_trace", identity + "-trace", {
        "trace_version": ROLE_TRACE_VERSION, "campaign_only_surface": True,
        "case_id": spec["case_id"], "role": spec["role"], "trial": trial.reference.to_dict(),
        "execution_interface": foundation["interface"].reference.to_dict(),
        "source_refs": spec.get("source_refs", []), "events": session.events,
        "tool_surface": configs["dispatch"].payload["tool_surface"], "scope": scope,
        "initial_workspace": before, "final_workspace": after,
        "summary": {"status": session.status, "stop_reason": session.stop_reason, "compatibility": session.compatibility, "correctness": correctness, **metrics},
        "preflight": preflight, "assessments": assessments,
    })
    validate_role_execution_trace(trace)
    evidence_store.persist(trace)
    parsed_ok = session.compatibility == "compatible"
    unknown = CompatibilityDimension("unknown", "Raw runtime/tool evidence requires attribution; no intrinsic model-failure inference.", (trace.reference,))
    compatibility = seal_compatibility_observation(identity + "-compatibility", compatibility_observation(
        case_id=spec["case_id"], turn=max(1, session.model_turns), execution_interface=foundation["interface"].reference,
        semantic_tool_selection=CompatibilityDimension("fail" if session.denied_calls else "unknown", "Authority violations are observed separately from semantic tool-quality review.", (trace.reference,)) if tool_case else CompatibilityDimension("not_applicable"),
        argument_correctness=CompatibilityDimension("unknown" if not session.tool_calls else ("fail" if any(x["event_type"] == "tool_authorization" and x["payload"].get("reason") == "invalid_arguments" for x in session.events) else "pass"), evidence=(trace.reference,)) if tool_case else CompatibilityDimension("not_applicable"),
        protocol_parser_compatibility=CompatibilityDimension("pass", "Completed normalized responses were observed.", (trace.reference,)) if parsed_ok else unknown,
        end_to_end_success=CompatibilityDimension("unknown" if deterministic is None else ("pass" if deterministic and session.status == "success" else "fail"), "Deterministic completion and correctness are separate from human role qualification.", (trace.reference,)),
        diagnostic_metadata={"correctness": correctness, "stop_reason": session.stop_reason, "qualification_status": "provisional-unqualified" if spec["role"] == "reviewer" else "unqualified-pending-review"},
    ))
    evidence_store.persist(compatibility)
    terminal_bytes = session.final.encode("utf-8")
    record = case_result(
        identity + "-result", manifest=manifest.reference, benchmark=benchmark.reference, trial=trial.reference,
        case_id=spec["case_id"], status=session.status, started_at=started_at, finished_at=finished_at, metrics=metrics,
        execution_evidence={"trace": trace.reference.to_dict(), "compatibility_observation": compatibility.reference.to_dict(), "execution_binding": binding.reference.to_dict(), "correctness": correctness, "raw_runtime_directory": str(folder / "runtime"), "telemetry_directory": str(folder), "accepted_battery_modified": False},
        terminal_output={"kind": "assistant_text", "content": session.final, "sha256": hashlib.sha256(terminal_bytes).hexdigest(), "size_bytes": len(terminal_bytes)},
    )
    review = evaluation_result(identity + "-review", case=record.reference, evaluator=evaluator.reference,
        verdict="review" if session.status == "success" else "not_scored", score=None, maximum_score=None,
        hard_failures=[], checks=[EvaluationCheck(check_id=check["check_id"], passed=check["passed"], weight=1, earned=1 if check["passed"] else 0, detail=check["detail"], evidence=(trace.reference,)).to_dict() for check in final_assessment.get("checks", [])] if final_assessment else [])
    evidence_store.persist_many([record, review])
    result = {
        "case_id": spec["case_id"], "role": spec["role"], "ordinal": ordinal,
        "status": session.status, "stop_reason": session.stop_reason, "runtime_compatibility": session.compatibility,
        "correctness": correctness, "qualification_status": "provisional-unqualified" if spec["role"] == "reviewer" else "unqualified-pending-human-review",
        "deterministic_passed": deterministic, "first_pass_passed": assessments[0].get("deterministic_passed") if assessments else None,
        "repair_attempted": len(assessments) > 1 or any(x["phase"] == "repair" for x in session.events),
        "repair_passed": assessments[-1].get("deterministic_passed") if len(assessments) > 1 else None,
        "human_review_required": True, "final_response": session.final,
        "accepted_handoff": _worker_handoff(session.final) if session.status == "success" and deterministic is True and spec["role"] == "worker" else None,
        "metrics": metrics, "evidence_directory": str(folder), "workspace": str(workspace.root) if workspace else None,
        "records": {"case_result": record.reference.to_dict(), "evaluation": review.reference.to_dict(), "manifest": manifest.reference.to_dict(), "trial": trial.reference.to_dict(), "trace": trace.reference.to_dict(), "compatibility": compatibility.reference.to_dict()},
    }
    write_json(folder / "result.json", result)
    (folder / "response.md").write_text(session.final, encoding="utf-8")
    if case_publisher is not None:
        case_publisher.completed(key=publication_key, row=result, native_root=folder, artifact_paths=[folder])
    return result


def run_role_campaign(
    *, campaign_root: Path, roles: Sequence[str], repetitions: int,
    foundation: Mapping[str, SealedEvidence], base_config_spec: Mapping[str, Any],
    driver_factory: Callable, evidence_store: EvidenceStore, output_dir: Path,
    governor_root: Path | None = None, case_context_factory: Callable | None = None,
    progress: Callable[[Mapping[str, Any]], None] | None = None,
    driver_binding: Mapping[str, Any] | None = None,
    case_publisher=None,
) -> dict[str, Any]:
    """Run a one-pass screen or three-repeat qualification evidence collection.

    This does not grant a role assignment. Human reviews are deliberately pending,
    and the Reviewer role remains explicitly provisional regardless of repetition.
    """
    if repetitions not in {1, 3}:
        raise ValueError("role screen requires 1 repetition; qualification collection requires 3")
    if not roles or len(set(roles)) != len(roles) or any(r not in ROLE_NAMES for r in roles):
        raise ValueError("roles must be unique names from the five established roles")
    if set(foundation) != {"host", "runtime", "model", "interface"}:
        raise ValueError("foundation requires host/runtime/model/interface evidence")
    output = Path(output_dir)
    if output.exists():
        raise ValueError(f"refusing to overwrite role campaign output: {output}")
    # Resolve every source and all Governor docs before creating or running cases.
    specs = [spec for role in roles for spec in build_role_cases(campaign_root, role, governor_root=governor_root)]
    output.mkdir(parents=True)
    results = []
    stopped = None
    for ordinal in range(1, repetitions + 1):
        previous_handoff = None
        scenario_started = False
        scenario_failed = False
        for spec in specs:
            scenario = spec.get("scenario") == "intent04"
            workspace = output / f"repetition-{ordinal}" / "intent04-workspace" if scenario else None
            dependency_blocked = scenario and spec["stage"] > 1 and scenario_failed
            if progress:
                progress({"event": "case_start", "case_id": spec["case_id"], "ordinal": ordinal})
            result = run_role_case(
                spec, foundation=foundation, base_config_spec=base_config_spec, driver_factory=driver_factory,
                evidence_store=evidence_store, output_dir=output / f"repetition-{ordinal}" / spec["case_id"], ordinal=ordinal,
                workspace_root=workspace, reuse_workspace=scenario and scenario_started,
                prerequisite_handoff=previous_handoff if scenario else None, dependency_blocked=dependency_blocked,
                case_context_factory=case_context_factory, driver_binding=driver_binding, case_publisher=case_publisher,
            )
            if scenario:
                scenario_started = True
                previous_handoff = result["accepted_handoff"]
                scenario_failed = previous_handoff is None
            results.append(result)
            write_json(output / "progress.json", {"results": results, "planned_cases": len(specs) * repetitions})
            if progress:
                progress({"event": "case_complete", **result})
            if result["runtime_compatibility"] == "unresolved" or result["stop_reason"] == "campaign_harness_or_watchdog_failure":
                stopped = {"case_id": result["case_id"], "reason": result["stop_reason"], "resume_requires": "inspect runtime/interface evidence before a new campaign"}
                break
        if stopped is not None:
            break
    summary = {
        "campaign": ROLE_CAMPAIGN_VERSION, "roles": list(roles), "repetitions": repetitions,
        "results": results, "qualification_status": "human-review-pending",
        "planned_cases": len(specs) * repetitions, "completed_cases": len(results), "stopped": stopped,
        "reviewer_status": "provisional-unqualified",
        "tester_coverage": {"reused_cases": ["A", "C", "D"], "planned_but_not_implemented_historically": ["B", "E", "F"]},
        "performance_policy": "Compare generation throughput, tokens/verbosity, cold/warm overhead, and telemetry separately from total wall time.",
        "accepted_batteries_modified": False,
    }
    write_json(output / "summary.json", summary)
    return summary
