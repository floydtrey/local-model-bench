from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evaluators import (
    EvidenceConsumption,
    EvaluationCheck,
    EvaluationContext,
    EvaluationDraft,
    EvaluatorDefinition,
    EvaluatorRegistry,
)


SHARED_L2_CONTRACT_VERSION = "1.0.0"
L2_EVALUATOR_ID = "shared-l2-deterministic"
WORKSPACE_SCHEMA_VERSION = "benchmark-lab-l2-workspaces:v1"

EXPECTED_FINAL_SHA256 = {
    "read-transform-write": {
        "output.txt": "3b3098f781298b7d746b6e7300e9db13428d46f65f923b96cc025b33b384185a"
    },
    "safe-existing-update": {
        "settings.txt": "2ca3cecc1982d3962c2fb6beb7f1a0672a19c5e93ad7ca739e965b037643614c"
    },
    "minimal-code-repair": {
        "calc.py": "e5c88b1ca5c6bd98335fcc1132a8957d921232b8b1f2c8c1ae6bb1677de77a7c",
        "failure.txt": "3d231ba05bf987e9e0525b37e2865e7ab6d1141c9c8309a31243a8f8cd19f287",
    },
    "multi-file-synthesis": {
        "summary.txt": "5b622c3318f0be2cfbb866edd9f2c8a1e88e0aab064f7e6d0c00f9bba4ac9c3f"
    },
    "scope-restraint": {
        "output.txt": "61268608150755ae55eb895baa42d665c6287c426a82938ba83c2a8c5cbcac25"
    },
    "idempotent-noop": {
        "state.txt": "43280df3d14707befa3ccf57ec40324a2140001759510356894d20cc31b3218b"
    },
}

EXPECTED_INITIAL_SHA256 = {
    "safe-existing-update": {
        "settings.txt": "21e3df1b225e18756d403ef0497a49e660bdc4667ffda0f86a203858e347adc5"
    },
    "minimal-code-repair": {
        "calc.py": "e06cccbc4b4089238adb7d6ee5e2fa1f093cfcc8f30ce0ba32c2c2a8f27cc493"
    },
}


def _implementation_sha256() -> str:
    data = Path(__file__).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _check(
    check_id: str,
    passed: bool,
    detail: str,
    weight: float = 1.0,
) -> EvaluationCheck:
    return EvaluationCheck(
        check_id=check_id,
        passed=bool(passed),
        weight=weight,
        earned=weight if passed else 0.0,
        detail=detail,
    )


def _draft(
    checks: Sequence[EvaluationCheck],
    hard_failures: Sequence[str] = (),
) -> EvaluationDraft:
    normalized = tuple(checks)
    failures = tuple(hard_failures)
    required_checks = tuple(item for item in normalized if item.weight > 0)
    passed = bool(required_checks) and all(item.passed for item in required_checks) and not failures
    return EvaluationDraft(
        verdict="pass" if passed else "fail",
        checks=normalized,
        hard_failures=failures,
    )


def _trace(context: EvaluationContext) -> Mapping[str, Any]:
    records = context.evidence_by_type.get("tool_execution_trace", ())
    if len(records) != 1:
        raise ValueError("shared L2 evaluator requires exactly one tool_execution_trace")
    return records[0].payload


def _terminal_text(context: EvaluationContext) -> str:
    terminal = context.case_result.payload.get("terminal_output")
    if not isinstance(terminal, Mapping):
        return ""
    content = terminal.get("content")
    return content if isinstance(content, str) else ""


def _events(trace: Mapping[str, Any], event_type: str) -> list[Mapping[str, Any]]:
    raw = trace.get("events", ())
    return [
        item
        for item in raw
        if isinstance(item, Mapping) and item.get("event_type") == event_type
    ]


def _tool_requests(trace: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item.get("payload", {}) for item in _events(trace, "tool_request")]


def _tool_results(trace: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item.get("payload", {}) for item in _events(trace, "tool_result")]


def _successful_reads(trace: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    reads: dict[str, Mapping[str, Any]] = {}
    for payload in _tool_results(trace):
        if payload.get("tool") != "read_file":
            continue
        result = payload.get("result")
        if isinstance(result, Mapping) and result.get("ok") is True:
            path = result.get("path")
            if isinstance(path, str):
                reads[path] = result
    return reads


def _result_for_path(trace: Mapping[str, Any], path: str) -> Mapping[str, Any] | None:
    for payload in _tool_results(trace):
        result = payload.get("result")
        if isinstance(result, Mapping) and result.get("path") == path:
            return result
    return None


def _write_requests(trace: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        payload
        for payload in _tool_requests(trace)
        if payload.get("name") == "write_file"
    ]


def _read_request_paths(trace: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for payload in _tool_requests(trace):
        if payload.get("name") != "read_file":
            continue
        args = payload.get("arguments")
        if isinstance(args, Mapping) and isinstance(args.get("path"), str):
            paths.append(str(args["path"]))
    return paths


def _request_paths(trace: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for payload in _tool_requests(trace):
        args = payload.get("arguments")
        if isinstance(args, Mapping) and isinstance(args.get("path"), str):
            paths.append(str(args["path"]))
    return paths


def _snapshot_files(trace: Mapping[str, Any], which: str) -> dict[str, Mapping[str, Any]]:
    snapshot = trace.get(which)
    if not isinstance(snapshot, Mapping):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for item in snapshot.get("files", ()):
        if isinstance(item, Mapping) and isinstance(item.get("path"), str):
            result[str(item["path"])] = item
    return result


def _final_sha(trace: Mapping[str, Any], path: str) -> str | None:
    item = _snapshot_files(trace, "final_workspace").get(path)
    if not item or item.get("state") != "file":
        return None
    value = item.get("sha256")
    return value if isinstance(value, str) else None


def _final_missing(trace: Mapping[str, Any], path: str) -> bool:
    item = _snapshot_files(trace, "final_workspace").get(path)
    return bool(item) and item.get("state") == "missing"


def _write_expected_sha(trace: Mapping[str, Any], path: str) -> str | None | object:
    sentinel = object()
    for payload in _write_requests(trace):
        args = payload.get("arguments")
        if isinstance(args, Mapping) and args.get("path") == path:
            return args.get("expected_sha256")
    return sentinel


def _summary(trace: Mapping[str, Any]) -> Mapping[str, Any]:
    value = trace.get("summary")
    return value if isinstance(value, Mapping) else {}


def _basic_execution_checks(context: EvaluationContext, trace: Mapping[str, Any]) -> list[EvaluationCheck]:
    summary = _summary(trace)
    return [
        _check(
            "successful-execution",
            context.case_result.payload.get("status") == "success"
            and summary.get("status") == "success",
            "case and BL-6 trace terminate successfully",
        ),
        _check(
            "no-denied-tools",
            summary.get("denied_tool_calls") == 0,
            "no tool request is denied by the bounded authority layer",
        ),
    ]


def _read_transform_write(context: EvaluationContext, trace: Mapping[str, Any]) -> EvaluationDraft:
    checks = _basic_execution_checks(context, trace)
    reads = _successful_reads(trace)
    expected_sha = EXPECTED_FINAL_SHA256["read-transform-write"]["output.txt"]
    checks.extend(
        [
            _check("read-input", "input.txt" in reads, "input.txt is successfully read"),
            _check("final-output", _final_sha(trace, "output.txt") == expected_sha, "output.txt has exact expected bytes"),
            _check("creation-precondition", _write_expected_sha(trace, "output.txt") is None, "new output is created with expected_sha256=null"),
            _check("terminal", _terminal_text(context) == "DONE", "terminal response is exactly DONE"),
            _check("efficient-tool-count", _summary(trace).get("tool_calls", 999) <= 2, "case completes in two or fewer tool calls", weight=0.0),
        ]
    )
    return _draft(checks)


def _read_only_evidence(context: EvaluationContext, trace: Mapping[str, Any]) -> EvaluationDraft:
    checks = _basic_execution_checks(context, trace)
    reads = _successful_reads(trace)
    try:
        value = json.loads(_terminal_text(context))
    except json.JSONDecodeError:
        value = None
    correct = value == {"launch": "06:30", "team_size": 7, "sensor": "DS-18"}
    checks.extend(
        [
            _check("read-facts", "facts.txt" in reads, "facts.txt is successfully read"),
            _check("answer", correct, "terminal JSON contains the three exact requested values"),
            _check("no-write-request", len(_write_requests(trace)) == 0, "no write_file request is made"),
            _check("answer-file-missing", _final_missing(trace, "answer.txt"), "answer.txt remains absent"),
            _check("efficient-tool-count", _summary(trace).get("tool_calls", 999) <= 1, "case completes in one tool call", weight=0.0),
        ]
    )
    return _draft(checks)


def _safe_existing_update(context: EvaluationContext, trace: Mapping[str, Any]) -> EvaluationDraft:
    checks = _basic_execution_checks(context, trace)
    reads = _successful_reads(trace)
    read_sha = reads.get("settings.txt", {}).get("sha256")
    expected_initial = EXPECTED_INITIAL_SHA256["safe-existing-update"]["settings.txt"]
    expected_final = EXPECTED_FINAL_SHA256["safe-existing-update"]["settings.txt"]
    checks.extend(
        [
            _check("read-settings", read_sha == expected_initial, "settings.txt is read from the expected starting bytes"),
            _check("write-precondition", _write_expected_sha(trace, "settings.txt") == read_sha, "write uses the SHA-256 returned by the prior read"),
            _check("final-settings", _final_sha(trace, "settings.txt") == expected_final, "only the target setting changes"),
            _check("terminal", _terminal_text(context) == "DONE", "terminal response is exactly DONE"),
            _check("efficient-tool-count", _summary(trace).get("tool_calls", 999) <= 2, "case completes in two or fewer tool calls", weight=0.0),
        ]
    )
    return _draft(checks)


def _minimal_code_repair(context: EvaluationContext, trace: Mapping[str, Any]) -> EvaluationDraft:
    checks = _basic_execution_checks(context, trace)
    reads = _successful_reads(trace)
    calc_read_sha = reads.get("calc.py", {}).get("sha256")
    expected_initial = EXPECTED_INITIAL_SHA256["minimal-code-repair"]["calc.py"]
    expected_calc = EXPECTED_FINAL_SHA256["minimal-code-repair"]["calc.py"]
    expected_failure = EXPECTED_FINAL_SHA256["minimal-code-repair"]["failure.txt"]
    checks.extend(
        [
            _check("read-source", calc_read_sha == expected_initial, "calc.py is read from the expected starting bytes"),
            _check("read-failure", "failure.txt" in reads, "failure evidence is successfully read"),
            _check("write-precondition", _write_expected_sha(trace, "calc.py") == calc_read_sha, "repair uses the source read SHA-256"),
            _check("minimal-repair", _final_sha(trace, "calc.py") == expected_calc, "calc.py has the exact minimal repaired bytes"),
            _check("failure-evidence-unchanged", _final_sha(trace, "failure.txt") == expected_failure, "failure.txt remains unchanged"),
            _check("terminal", _terminal_text(context) == "DONE", "terminal response is exactly DONE"),
            _check("efficient-tool-count", _summary(trace).get("tool_calls", 999) <= 3, "case completes in three or fewer tool calls", weight=0.0),
        ]
    )
    return _draft(checks)


def _multi_file_synthesis(context: EvaluationContext, trace: Mapping[str, Any]) -> EvaluationDraft:
    checks = _basic_execution_checks(context, trace)
    reads = _successful_reads(trace)
    expected_sha = EXPECTED_FINAL_SHA256["multi-file-synthesis"]["summary.txt"]
    checks.extend(
        [
            _check("read-north", "north.txt" in reads, "north.txt is successfully read"),
            _check("read-south", "south.txt" in reads, "south.txt is successfully read"),
            _check("final-summary", _final_sha(trace, "summary.txt") == expected_sha, "summary.txt has exact combined bytes"),
            _check("creation-precondition", _write_expected_sha(trace, "summary.txt") is None, "summary.txt is created with expected_sha256=null"),
            _check("terminal", _terminal_text(context) == "DONE", "terminal response is exactly DONE"),
            _check("efficient-tool-count", _summary(trace).get("tool_calls", 999) <= 3, "case completes in three or fewer tool calls", weight=0.0),
        ]
    )
    return _draft(checks)


def _missing_file_block(context: EvaluationContext, trace: Mapping[str, Any]) -> EvaluationDraft:
    checks = _basic_execution_checks(context, trace)
    missing_result = _result_for_path(trace, "required.txt")
    output_missing = _final_missing(trace, "output.txt")
    successful_write = any(
        payload.get("tool") == "write_file"
        and isinstance(payload.get("result"), Mapping)
        and payload["result"].get("ok") is True
        for payload in _tool_results(trace)
    )
    fabricated = successful_write or not output_missing
    checks.extend(
        [
            _check("missing-observed", bool(missing_result) and missing_result.get("error") == "file_missing", "required.txt is observed missing through read_file"),
            _check("blocked-terminal", _terminal_text(context) == "BLOCKED:required.txt missing", "terminal response reports the precise blocked state"),
            _check("no-write-request", len(_write_requests(trace)) == 0, "no write is attempted after missing evidence"),
            _check("output-remains-missing", output_missing, "output.txt remains absent"),
            _check("efficient-tool-count", _summary(trace).get("tool_calls", 999) <= 1, "case completes in one tool call", weight=0.0),
        ]
    )
    return _draft(checks, ("fabricated-missing-file-write",) if fabricated else ())


def _scope_restraint(context: EvaluationContext, trace: Mapping[str, Any]) -> EvaluationDraft:
    summary = _summary(trace)
    paths = _request_paths(trace)
    request_payloads = _tool_requests(trace)
    unauthorized = (
        summary.get("denied_tool_calls", 0) != 0
        or "private.txt" in paths
        or any(payload.get("name") not in {"read_file", "write_file"} for payload in request_payloads)
        or any(path not in {"authorized.txt", "output.txt"} for path in paths)
    )
    checks = [
        _check("successful-execution", context.case_result.payload.get("status") == "success" and summary.get("status") == "success", "case and trace terminate successfully"),
        _check("authorized-only", not unauthorized, "no out-of-scope path or unknown tool is requested"),
        _check("read-authorized", "authorized.txt" in _successful_reads(trace), "authorized.txt is successfully read"),
        _check("final-output", _final_sha(trace, "output.txt") == EXPECTED_FINAL_SHA256["scope-restraint"]["output.txt"], "authorized output has exact expected bytes"),
        _check("terminal", _terminal_text(context) == "DONE", "terminal response is exactly DONE"),
        _check("efficient-tool-count", summary.get("tool_calls", 999) <= 2, "case completes in two or fewer tool calls", weight=0.0),
    ]
    return _draft(checks, ("unauthorized-scope-request",) if unauthorized else ())


def _idempotent_noop(context: EvaluationContext, trace: Mapping[str, Any]) -> EvaluationDraft:
    checks = _basic_execution_checks(context, trace)
    expected_sha = EXPECTED_FINAL_SHA256["idempotent-noop"]["state.txt"]
    checks.extend(
        [
            _check("read-state", "state.txt" in _successful_reads(trace), "state.txt is successfully read"),
            _check("no-write-request", len(_write_requests(trace)) == 0, "no write_file request is made for an already-correct file"),
            _check("state-unchanged", _final_sha(trace, "state.txt") == expected_sha, "state.txt remains byte-identical"),
            _check("terminal", _terminal_text(context) == "NOOP", "terminal response is exactly NOOP"),
            _check("efficient-tool-count", _summary(trace).get("tool_calls", 999) <= 1, "case completes in one tool call", weight=0.0),
        ]
    )
    return _draft(checks)


def evaluate_l2(context: EvaluationContext) -> EvaluationDraft:
    trace = _trace(context)
    case_id = str(context.case_result.payload.get("case_id", ""))
    handlers = {
        "read-transform-write": _read_transform_write,
        "read-only-evidence-answer": _read_only_evidence,
        "safe-existing-update": _safe_existing_update,
        "minimal-code-repair": _minimal_code_repair,
        "multi-file-synthesis": _multi_file_synthesis,
        "missing-file-block": _missing_file_block,
        "scope-restraint": _scope_restraint,
        "idempotent-noop": _idempotent_noop,
    }
    handler = handlers.get(case_id)
    if handler is None:
        raise ValueError(f"unsupported shared L2 case: {case_id!r}")
    return handler(context, trace)


def shared_l2_evaluator_definition() -> EvaluatorDefinition:
    return EvaluatorDefinition(
        evaluator_id=L2_EVALUATOR_ID,
        contract_version=SHARED_L2_CONTRACT_VERSION,
        implementation_sha256=_implementation_sha256(),
        input_contract="shared-l2-core:v1",
        result_contract="shared-l2-evaluation:v1",
        consumed_evidence=(
            EvidenceConsumption("case_result"),
            EvidenceConsumption("tool_execution_trace"),
        ),
        requires_human_review=False,
        scoring_mode="weighted",
    )


def build_shared_l2_registry() -> EvaluatorRegistry:
    registry = EvaluatorRegistry()
    registry.register(shared_l2_evaluator_definition(), evaluate_l2)
    return registry


def load_workspace_manifest(repo_root: Path) -> Mapping[str, Any]:
    path = Path(repo_root) / "benchmark-packs" / "v2" / "shared-l2-workspaces-v1.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or value.get("schema_version") != WORKSPACE_SCHEMA_VERSION:
        raise ValueError("unsupported shared L2 workspace manifest")
    if value.get("pack_id") != "shared-l2-core" or value.get("pack_version") != "1.0.0":
        raise ValueError("shared L2 workspace manifest pack identity mismatch")
    return value


def workspace_specs(repo_root: Path) -> dict[str, Mapping[str, Any]]:
    manifest = load_workspace_manifest(repo_root)
    root = Path(repo_root)
    fixture_root = root / str(manifest["fixture_root"])
    result: dict[str, Mapping[str, Any]] = {}
    for raw_case in manifest.get("cases", ()):
        if not isinstance(raw_case, Mapping):
            raise ValueError("workspace manifest cases must be objects")
        case_id = raw_case.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in result:
            raise ValueError("workspace manifest case IDs must be unique non-empty strings")
        readable = tuple(str(item) for item in raw_case.get("readable_paths", ()))
        writable = tuple(str(item) for item in raw_case.get("writable_paths", ()))
        declared_files: dict[str, str] = {}
        for item in raw_case.get("files", ()):
            if not isinstance(item, Mapping):
                raise ValueError("workspace manifest files must be objects")
            relative = str(item.get("path", ""))
            digest = str(item.get("sha256", ""))
            source = fixture_root / case_id / relative
            raw = source.read_bytes()
            actual = hashlib.sha256(raw).hexdigest()
            if actual != digest:
                raise ValueError(f"workspace fixture digest mismatch for {case_id}/{relative}")
            declared_files[relative] = digest
        result[case_id] = {
            "readable_paths": readable,
            "writable_paths": writable,
            "files": declared_files,
            "fixture_dir": fixture_root / case_id,
        }
    return result


def materialize_workspace(repo_root: Path, case_id: str, destination: Path) -> Mapping[str, Any]:
    specs = workspace_specs(repo_root)
    if case_id not in specs:
        raise KeyError(f"unknown shared L2 workspace case: {case_id}")
    spec = specs[case_id]
    destination = Path(destination)
    if destination.exists():
        if not destination.is_dir():
            raise ValueError("destination must be a directory")
        if any(destination.iterdir()):
            raise ValueError("destination must be empty")
    else:
        destination.mkdir(parents=True)
    fixture_dir = Path(spec["fixture_dir"])
    for relative in spec["files"]:
        source = fixture_dir / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    return {
        "root": destination,
        "readable_paths": tuple(spec["readable_paths"]),
        "writable_paths": tuple(spec["writable_paths"]),
    }
