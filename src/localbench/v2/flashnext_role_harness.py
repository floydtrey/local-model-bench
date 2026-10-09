"""Campaign-only role conversation and controlled fixture-test interface.

The accepted shared batteries are deliberately not imported or changed here.
File access uses the same BoundedWorkspace authority checks as BL-6. The test
tool chooses one fixed command; model-supplied process arguments are impossible.
Executing generated Python is NOT operating-system or network isolation.
"""
from __future__ import annotations

import hashlib
import ast
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .contracts import canonical_json_bytes, sha256_json
from .tool_harness import (
    BOUNDED_FILE_TOOL_DEFINITIONS,
    BoundedWorkspace,
    ModelTurnRequest,
    ModelTurnResponse,
    ToolCall,
)

ROLE_SURFACE_ID = "flashnext-role-files-tests:v1"
RUN_TESTS_TOOL = {
    "name": "run_tests",
    "description": (
        "Run the fixture's existing deterministic Python unittest suite in the "
        "current disposable workspace. This tool accepts no commands or arguments."
    ),
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}
ROLE_TOOL_DEFINITIONS = (*BOUNDED_FILE_TOOL_DEFINITIONS, RUN_TESTS_TOOL)
ROLE_TOOL_SCHEMA_SHA256 = sha256_json(
    {"surface_id": ROLE_SURFACE_ID, "tools": ROLE_TOOL_DEFINITIONS}
)
MAX_ROLE_VALIDATION_RETRIES = 2


def _schema_matches(value: Any, schema: Mapping[str, Any]) -> bool:
    if "anyOf" in schema:
        return any(_schema_matches(value, item) for item in schema["anyOf"])
    if "oneOf" in schema:
        return sum(_schema_matches(value, item) for item in schema["oneOf"]) == 1
    kind = schema.get("type")
    if kind == "null" and value is not None:
        return False
    if kind == "string" and not isinstance(value, str):
        return False
    if kind == "boolean" and not isinstance(value, bool):
        return False
    if kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return False
    if kind == "object" and not isinstance(value, Mapping):
        return False
    if "pattern" in schema and (not isinstance(value, str) or re.fullmatch(schema["pattern"], value) is None):
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if "const" in schema and value != schema["const"]:
        return False
    return True


def _canonical_json_literal(value: Any, schema: Mapping[str, Any]) -> tuple[Any, dict[str, Any] | None]:
    """Normalize only lossless JSON literal strings when the declared schema proves one meaning."""
    if not isinstance(value, str) or _schema_matches(value, schema):
        return value, None
    literal = value.strip().lower()
    candidates: list[tuple[Any, str]] = []
    if literal == "null":
        candidates.append((None, "null"))
    elif literal == "true":
        candidates.append((True, "boolean"))
    elif literal == "false":
        candidates.append((False, "boolean"))
    matching = [(candidate, kind) for candidate, kind in candidates if _schema_matches(candidate, schema)]
    if len(matching) != 1:
        return value, None
    candidate, kind = matching[0]
    return candidate, {"from_type": "string", "to_type": kind, "from_value": value, "to_value": candidate}


def normalize_role_tool_call(call: ToolCall) -> tuple[ToolCall, list[dict[str, Any]]]:
    definition = next((tool for tool in ROLE_TOOL_DEFINITIONS if tool["name"] == call.name), None)
    if definition is None:
        return call, []
    arguments = dict(call.arguments)
    properties = definition["input_schema"].get("properties", {})
    changes = []
    for key, schema in properties.items():
        if key not in arguments or not isinstance(schema, Mapping):
            continue
        normalized, change = _canonical_json_literal(arguments[key], schema)
        if change is not None:
            arguments[key] = normalized
            changes.append({"field": key, **change})
    if not changes:
        return call, []
    return ToolCall(call.call_id, call.name, arguments), changes


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def file_snapshot(root: Path) -> dict[str, str]:
    """Record the whole fixture, including paths outside the exposed surface."""
    files = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            files[relative] = "symlink:" + os.readlink(path)
        elif path.is_file():
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def snapshot_diff(before: Mapping[str, str], after: Mapping[str, str]) -> dict[str, list[str]]:
    return {
        "changed": sorted(p for p in before.keys() & after.keys() if before[p] != after[p]),
        "created": sorted(after.keys() - before.keys()),
        "deleted": sorted(before.keys() - after.keys()),
    }


def run_python_check(
    workspace: Path,
    evidence_dir: Path,
    label: str,
    *,
    script: Path | None = None,
    stage: int | None = None,
    timeout_seconds: float = 120,
    inspect_tester_tests: bool = False,
) -> dict[str, Any]:
    """Only controller-owned arguments reach this function, never tool arguments."""
    from localbench.assistant001.packet import snapshot
    before_sha256 = snapshot(workspace)
    if timeout_seconds <= 0:
        raise ValueError("test timeout must be positive")
    if stage is not None and (script is None or stage not in {1, 2, 3}):
        raise ValueError("historical verification stage must be 1, 2, or 3")
    args = [sys.executable, "-B"]
    if script is None:
        args += ["-m", "unittest", "discover", "-s", "tests", "-v"]
    else:
        args += [str(script.resolve())]
        if stage is not None:
            args += [str(stage), "--json"]
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stdout_path, stderr_path = evidence_dir / f"{label}.stdout.txt", evidence_dir / f"{label}.stderr.txt"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(workspace.resolve())
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    started = time.monotonic()
    timed_out = False
    error = None
    exit_code = None
    inspection = inspect_pricing_tests(workspace) if inspect_tester_tests else None
    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
        try:
            if inspection is not None and not inspection["allowed"]:
                raise ValueError("controlled_test_source_policy: " + "; ".join(inspection["reasons"]))
            process = subprocess.Popen(
                args, cwd=workspace, env=env, stdin=subprocess.DEVNULL,
                stdout=out, stderr=err, shell=False,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            try:
                exit_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, check=False, timeout=10,
                    )
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                process.kill()
                process.wait(timeout=10)
        except Exception as exc:
            error = {"type": type(exc).__name__, "detail": str(exc)}
    stdout, stderr = stdout_path.read_bytes(), stderr_path.read_bytes()
    result = {
        "artifact_before_sha256": before_sha256,
        "artifact_after_sha256": snapshot(workspace),
        "command": args, "cwd": str(workspace.resolve()), "exit_code": exit_code,
        "timed_out": timed_out, "infrastructure_error": error,
        "wall_seconds": time.monotonic() - started,
        "source_inspection": inspection,
        "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stdout_bytes": len(stdout), "stderr_bytes": len(stderr),
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
    }
    write_json(evidence_dir / f"{label}.json", result)
    return result


def inspect_pricing_tests(workspace: Path) -> dict[str, Any]:
    """Inspect a deliberately narrow, documented test-execution capability.

    This pricing fixture needs unittest assertions and apply_discount only. It
    does not need imports of host, process, filesystem, or networking APIs. An
    unsupported test is an interface restriction, not a model-quality judgment.
    This check is additional restraint and is not advertised as a Python sandbox.
    """
    reasons: list[str] = []
    inspected = []
    simple_calls = {"apply_discount", "round", "abs", "len", "range", "float", "int"}
    assertion_calls = {"assertEqual", "assertAlmostEqual", "assertTrue", "assertFalse", "assertNotEqual", "assertIs", "assertIsNot", "assertIsNone", "assertIsNotNone"}
    reserved = simple_calls | {"self", "unittest"}

    class Unsupported(ValueError):
        pass

    def reject(node: ast.AST, detail: str) -> None:
        raise Unsupported(f"line {getattr(node, 'lineno', '?')}: {detail}")

    def expression(node: ast.AST, local_names: set[str], *, assertions: bool = False) -> None:
        if isinstance(node, ast.Constant):
            if node.value is not None and not isinstance(node.value, (bool, int, float, str)):
                reject(node, "only ordinary scalar constants are exposed")
        elif isinstance(node, ast.Name):
            if node.id not in local_names:
                reject(node, "only previously assigned test-local values are exposed")
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for item in node.elts:
                expression(item, local_names)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if key is None:
                    reject(node, "dictionary unpacking is not exposed")
                expression(key, local_names)
                expression(value, local_names)
        elif isinstance(node, ast.BinOp):
            expression(node.left, local_names)
            expression(node.right, local_names)
        elif isinstance(node, ast.UnaryOp):
            expression(node.operand, local_names)
        elif isinstance(node, ast.BoolOp):
            for item in node.values:
                expression(item, local_names)
        elif isinstance(node, ast.Compare):
            expression(node.left, local_names)
            for item in node.comparators:
                expression(item, local_names)
        elif isinstance(node, ast.IfExp):
            for item in (node.test, node.body, node.orelse):
                expression(item, local_names)
        elif isinstance(node, ast.Subscript):
            expression(node.value, local_names)
            expression(node.slice, local_names)
        elif isinstance(node, ast.Slice):
            for item in (node.lower, node.upper, node.step):
                if item is not None:
                    expression(item, local_names)
        elif isinstance(node, ast.JoinedStr):
            for item in node.values:
                expression(item, local_names)
        elif isinstance(node, ast.FormattedValue):
            expression(node.value, local_names)
            if node.format_spec is not None:
                expression(node.format_spec, local_names)
        elif isinstance(node, ast.Call):
            target = node.func
            allowed = isinstance(target, ast.Name) and target.id in simple_calls
            allowed |= assertions and isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self" and target.attr in assertion_calls
            if not allowed:
                reject(node, "only direct numeric/apply_discount calls and ordinary self assertions are exposed")
            for item in node.args:
                expression(item, local_names)
            for item in node.keywords:
                if item.arg is None:
                    reject(node, "keyword unpacking is not exposed")
                expression(item.value, local_names)
        else:
            reject(node, "attribute traversal, callable references, and dynamic expressions are not exposed")

    def local_target(node: ast.AST, local_names: set[str]) -> None:
        if isinstance(node, (ast.Tuple, ast.List)):
            for item in node.elts:
                local_target(item, local_names)
        elif isinstance(node, ast.Name) and node.id not in reserved and not node.id.startswith("_"):
            local_names.add(node.id)
        else:
            reject(node, "only ordinary test-local names may be assigned; assertion/module/function rebinding is forbidden")

    def statements(nodes: list[ast.stmt], local_names: set[str]) -> None:
        for node in nodes:
            if isinstance(node, ast.Expr):
                expression(node.value, local_names, assertions=True)
            elif isinstance(node, ast.Assign):
                expression(node.value, local_names)
                for target in node.targets:
                    local_target(target, local_names)
            elif isinstance(node, ast.AugAssign):
                if not isinstance(node.target, ast.Name) or node.target.id not in local_names:
                    reject(node, "augmented assignment requires a test-local name")
                expression(node.value, local_names)
            elif isinstance(node, ast.For):
                expression(node.iter, local_names)
                local_target(node.target, local_names)
                statements(node.body, local_names)
                statements(node.orelse, local_names)
            elif isinstance(node, ast.If):
                expression(node.test, local_names)
                statements(node.body, local_names)
                statements(node.orelse, local_names)
            elif isinstance(node, ast.With):
                for item in node.items:
                    call = item.context_expr
                    if item.optional_vars is not None or not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id == "self" and call.func.attr == "subTest"):
                        reject(node, "only with self.subTest(...) without an alias is exposed")
                    for value in call.args:
                        expression(value, local_names)
                    for value in call.keywords:
                        if value.arg is None:
                            reject(node, "subTest keyword unpacking is not exposed")
                        expression(value.value, local_names)
                statements(node.body, local_names)
            elif isinstance(node, ast.Assert):
                expression(node.test, local_names)
                if node.msg is not None:
                    expression(node.msg, local_names)
            elif isinstance(node, (ast.Pass, ast.Break, ast.Continue)):
                pass
            else:
                reject(node, "only ordinary assertions, local data, finite for loops, if, and subTest statements are exposed")

    def module(tree: ast.Module) -> None:
        class_names = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                if any(x.name != "unittest" or x.asname is not None for x in node.names):
                    reject(node, "only import unittest is exposed")
            elif isinstance(node, ast.ImportFrom):
                if node.level or node.module != "pricing.discount" or any(x.name != "apply_discount" or x.asname is not None for x in node.names):
                    reject(node, "only pricing.discount.apply_discount is exposed")
            elif isinstance(node, ast.ClassDef):
                base_ok = len(node.bases) == 1 and isinstance(node.bases[0], ast.Attribute) and isinstance(node.bases[0].value, ast.Name) and node.bases[0].value.id == "unittest" and node.bases[0].attr == "TestCase"
                if not base_ok or node.keywords or node.decorator_list or getattr(node, "type_params", ()) or node.name in reserved or node.name in class_names or node.name.startswith("_"):
                    reject(node, "only distinct ordinary unittest.TestCase classes are exposed")
                class_names.add(node.name)
                method_names = set()
                for method in node.body:
                    if isinstance(method, ast.Pass) or (isinstance(method, ast.Expr) and isinstance(method.value, ast.Constant) and isinstance(method.value.value, str)):
                        continue
                    if not isinstance(method, ast.FunctionDef) or not method.name.startswith("test_") or method.name in method_names:
                        reject(method, "only distinct test_* methods are exposed; assertion overrides are forbidden")
                    args = method.args
                    if method.decorator_list or method.returns or getattr(method, "type_params", ()) or args.posonlyargs or len(args.args) != 1 or args.args[0].arg != "self" or args.args[0].annotation or args.defaults or args.vararg or args.kwarg or args.kwonlyargs:
                        reject(method, "test methods must have exactly the plain (self) signature")
                    method_names.add(method.name)
                    statements(method.body, set())
            elif isinstance(node, ast.If):
                expected = ast.parse('if __name__ == "__main__":\n    unittest.main()\n').body[0]
                if ast.dump(node, include_attributes=False) != ast.dump(expected, include_attributes=False):
                    reject(node, "only the conventional guarded unittest.main() module entry point is exposed")
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                pass
            else:
                reject(node, "module-level execution, assignments, and helpers are not exposed")

    for path in sorted((workspace / "tests").rglob("*.py")):
        raw = path.read_bytes()
        relative = path.relative_to(workspace).as_posix()
        inspected.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest()})
        try:
            tree = ast.parse(raw, filename=relative)
        except SyntaxError as exc:
            reasons.append(f"{relative}: syntax error at line {exc.lineno}")
            continue
        try:
            module(tree)
        except Unsupported as exc:
            reasons.append(f"{relative}: {exc}")
    return {"policy": "pricing-unittest-static-v1", "allowed": not reasons, "files": inspected, "reasons": sorted(set(reasons)), "os_sandbox": False}


def test_infrastructure_ok(result: Mapping[str, Any]) -> bool:
    return not result.get("timed_out") and result.get("infrastructure_error") is None and result.get("exit_code") is not None


class RoleConversation:
    """One fresh role session; a repair reuses this exact message history."""

    def __init__(
        self, *, case_id: str, setup_driver: Callable, driver: Callable,
        evidence_dir: Path, workspace: BoundedWorkspace | None,
        max_tool_calls: int = 40, max_model_turns: int = 48,
        max_validation_retries: int = MAX_ROLE_VALIDATION_RETRIES,
        timeout_seconds: float = 600, test_timeout_seconds: float = 120,
        inspect_tester_tests: bool = False,
    ) -> None:
        self.case_id, self.setup_driver, self.driver = case_id, setup_driver, driver
        self.evidence_dir, self.workspace = Path(evidence_dir), workspace
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.max_tool_calls, self.max_model_turns = max_tool_calls, max_model_turns
        if max_validation_retries < 0:
            raise ValueError("max_validation_retries must be >= 0")
        self.max_validation_retries = max_validation_retries
        self.deadline = time.monotonic() + timeout_seconds
        self.test_timeout_seconds = test_timeout_seconds
        self.inspect_tester_tests = inspect_tester_tests
        self.messages: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.model_turns = self.tool_calls = self.denied_calls = 0
        self.validation_failures = self.validation_retry_turns = 0
        self.schema_normalizations = self.repetition_detections = 0
        self._validation_chain_failures = 0
        self._retry_pending = False
        self._failed_tool_signatures: dict[str, int] = {}
        self.test_calls: list[dict[str, Any]] = []
        self.status = "success"
        self.stop_reason = "not_started"
        self.compatibility = "not_observed"
        self.final = ""
        self.phase = "setup"

    def event(self, kind: str, payload: Mapping[str, Any]) -> None:
        value = {"sequence": len(self.events) + 1, "event_type": kind, "phase": self.phase, "payload": dict(payload)}
        value["event_sha256"] = sha256_json(value)
        self.events.append(value)
        with (self.evidence_dir / "events.jsonl").open("ab") as handle:
            handle.write(canonical_json_bytes(value) + b"\n")
            handle.flush()

    def _response(self, *, setup: bool) -> ModelTurnResponse | None:
        if time.monotonic() >= self.deadline or self.model_turns >= self.max_model_turns:
            self.status, self.stop_reason = "resource_limit", "case_wall_or_turn_limit"
            return None
        self.model_turns += 1
        request = ModelTurnRequest(
            case_id=self.case_id, turn=self.model_turns, messages=tuple(self.messages),
            context_assets=(), tools=() if setup or self.workspace is None else ROLE_TOOL_DEFINITIONS,
        )
        self.event("model_request", request.to_dict())
        start = time.monotonic()
        try:
            response = (self.setup_driver if setup else self.driver)(request)
            if not isinstance(response, ModelTurnResponse):
                raise TypeError("driver did not return ModelTurnResponse")
        except Exception as exc:
            category = getattr(exc, "category", getattr(exc, "classification", getattr(exc, "kind", None)))
            bounded_model_limit = category in {"generation_truncated", "timeout"}
            self.status = "resource_limit" if bounded_model_limit else "protocol_failure"
            self.stop_reason = category or "runtime_or_interface_failure"
            self.compatibility = "compatible" if bounded_model_limit else "unresolved"
            self.event("model_error", {
                "error_type": type(exc).__name__, "detail": str(exc),
                "classification": category,
                "provider_metadata": getattr(exc, "provider_metadata", None),
                "wall_seconds": time.monotonic() - start,
                "correctness": "not_assessed_transport_failure",
            })
            return None
        self.compatibility = "compatible"
        value = response.to_dict()
        self.event("model_response", {**value, "wall_seconds": time.monotonic() - start})
        message = {"role": "assistant", "content": response.content or ""}
        if response.reasoning is not None:
            message["reasoning"] = response.reasoning
        if response.tool_calls:
            message["tool_calls"] = value["tool_calls"]
        self.messages.append(message)
        metadata = value.get("provider_metadata", {}) or {}
        reason = metadata.get("finish_reason", metadata.get("done_reason"))
        if reason in {"length", "max_tokens"}:
            self.status, self.stop_reason = "resource_limit", "output_token_limit"
            self.final = response.content or ""
            return None
        if time.monotonic() >= self.deadline:
            self.status, self.stop_reason = "resource_limit", "case_wall_limit"
            self.final = response.content or ""
            return None
        return response

    def establish(self, prompt: str, expected_marker: str | None) -> bool:
        self.phase = "setup"
        self.messages.append({"role": "user", "content": prompt})
        response = self._response(setup=True)
        if response is None:
            return False
        if response.tool_calls:
            self.status, self.stop_reason = "blocked", "unauthorized_role_setup_tool_call"
            self.denied_calls += len(response.tool_calls)
            return False
        if expected_marker is not None and (response.content or "").strip() != expected_marker:
            self.status, self.stop_reason = "blocked", "role_setup_marker_mismatch"
            return False
        return True

    def dispatch(self, prompt: str, *, phase: str = "dispatch") -> str:
        self.phase = phase
        self.messages.append({"role": "user", "content": prompt})
        while True:
            if self._retry_pending:
                self.validation_retry_turns += 1
                self._retry_pending = False
            response = self._response(setup=False)
            if response is None:
                return self.final
            if not response.tool_calls:
                self.final = response.content or ""
                self.status, self.stop_reason = "success", "terminal_output"
                self.event("terminal_output", {"content": self.final})
                return self.final
            for original_call in response.tool_calls:
                if self.tool_calls >= self.max_tool_calls:
                    self.status, self.stop_reason = "resource_limit", "max_tool_calls"
                    self.event("limit_reached", {"blocked_call": original_call.to_dict()})
                    return self.final
                self.tool_calls += 1
                self.event("tool_request", original_call.to_dict())
                call, changes = normalize_role_tool_call(original_call)
                if changes:
                    self.schema_normalizations += 1
                    self.event("tool_argument_normalization", {
                        "policy": "schema-derived-lossless-json-literal:v1",
                        "original_call": original_call.to_dict(),
                        "normalized_call": call.to_dict(),
                        "changes": changes,
                    })
                allowed, reason, relative = False, "tool_not_exposed", None
                if self.workspace is not None:
                    if call.name == "run_tests":
                        allowed = not call.arguments
                        reason = "allowed" if allowed else "invalid_arguments"
                    else:
                        allowed, reason, relative = self.workspace.authorize(call)
                self.event("tool_authorization", {
                    "call_id": call.call_id, "tool": call.name, "allowed": allowed,
                    "reason": reason, "path": relative,
                })
                if allowed:
                    self._validation_chain_failures = 0
                if not allowed:
                    self.denied_calls += 1
                    if reason == "invalid_arguments":
                        self.validation_failures += 1
                        self._validation_chain_failures += 1
                        retries_used = max(0, self._validation_chain_failures - 1)
                        retries_remaining = max(0, self.max_validation_retries - retries_used)
                        result = {
                            "ok": False, "error": "authorization_denied", "reason": reason, "path": relative,
                            "validation_feedback": "Tool arguments do not satisfy the declared schema. Re-emit only schema-valid arguments.",
                            "validation_retries_remaining": retries_remaining,
                        }
                    else:
                        self._validation_chain_failures = 0
                        result = {"ok": False, "error": "authorization_denied", "reason": reason, "path": relative}
                elif call.name == "run_tests":
                    remaining = self.deadline - time.monotonic()
                    if remaining <= 0:
                        self.status, self.stop_reason = "resource_limit", "case_wall_limit"
                        return self.final
                    result = run_python_check(
                        self.workspace.root, self.evidence_dir / "tool-tests",
                        f"test-{len(self.test_calls) + 1:03d}",
                        timeout_seconds=min(remaining, self.test_timeout_seconds),
                        inspect_tester_tests=self.inspect_tester_tests,
                    )
                    self.test_calls.append(result)
                    result = {
                        **result, "ok": test_infrastructure_ok(result),
                        "tests_passed": result["exit_code"] == 0 and test_infrastructure_ok(result),
                        "stdout": result["stdout"][:16000], "stderr": result["stderr"][:16000],
                    }
                else:
                    try:
                        result = self.workspace.execute(call, relative or "")
                    except Exception as exc:
                        result = {"ok": False, "error": "tool_execution_error", "error_type": type(exc).__name__, "detail": str(exc)}
                if result.get("ok") is False:
                    signature = sha256_json({
                        "tool": call.name,
                        "arguments": call.to_dict()["arguments"],
                        "error": result.get("error"),
                        "reason": result.get("reason"),
                    })
                    count = self._failed_tool_signatures.get(signature, 0) + 1
                    self._failed_tool_signatures[signature] = count
                    if count > 1:
                        self.repetition_detections += 1
                        self.event("repetition_detected", {
                            "signature": signature, "occurrence": count,
                            "tool": call.name, "reason": result.get("reason") or result.get("error"),
                        })
                else:
                    self._validation_chain_failures = 0
                    self._failed_tool_signatures.clear()
                self.event("tool_result", {"call_id": call.call_id, "tool": call.name, "result": result})
                self.messages.append({"role": "tool", "tool_call_id": call.call_id, "name": call.name, "result": result})
                if reason == "invalid_arguments":
                    if self._validation_chain_failures >= self.max_validation_retries + 1:
                        self.status, self.stop_reason = "resource_limit", "tool_validation_retry_limit"
                        self.event("limit_reached", {
                            "limit": "validation_retries",
                            "maximum_retries": self.max_validation_retries,
                            "failed_call": call.to_dict(),
                        })
                        return self.final
                    self._retry_pending = True
                elif result.get("ok") is False:
                    signature = sha256_json({
                        "tool": call.name,
                        "arguments": call.to_dict()["arguments"],
                        "error": result.get("error"),
                        "reason": result.get("reason"),
                    })
                    if self._failed_tool_signatures.get(signature, 0) >= self.max_validation_retries + 1:
                        self.status, self.stop_reason = "resource_limit", "repeated_tool_failure"
                        self.event("limit_reached", {
                            "limit": "repeated_tool_failure",
                            "maximum_retries": self.max_validation_retries,
                            "failed_call": call.to_dict(),
                        })
                        return self.final

    def metrics(self) -> dict[str, Any]:
        responses = [x["payload"] for x in self.events if x["event_type"] == "model_response"]
        attempts = [x["payload"] for x in self.events if x["event_type"] in {"model_response", "model_error"}]
        metadata = [x.get("provider_metadata") or {} for x in attempts]

        def total(*keys: str) -> int | float | None:
            values = []
            for item in metadata:
                found = next((item[k] for k in keys if isinstance(item.get(k), (int, float))), None)
                if found is not None:
                    values.append(found)
            return sum(values) if len(values) == len(metadata) and values else None

        prompt_tokens = total("prompt_tokens", "prompt_eval_count", "input_tokens")
        output_tokens = total("completion_tokens", "eval_count", "output_tokens")
        generation_ms = total("generation_ms", "predicted_ms")
        generation_seconds = total("generation_seconds")
        if generation_seconds is None and generation_ms is not None:
            generation_seconds = generation_ms / 1000
        if generation_seconds is None:
            eval_duration_ns = total("eval_duration")
            if eval_duration_ns is not None:
                generation_seconds = eval_duration_ns / 1_000_000_000
        predicted = [item.get("timings", {}).get("predicted_n") if isinstance(item.get("timings"), Mapping) else None for item in metadata]
        generation_tokens = sum(predicted) if predicted and all(isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0 for x in predicted) else None
        generation_rate = generation_tokens / generation_seconds if generation_tokens is not None and generation_seconds else None
        generation_rate_source = "sum(timings.predicted_n) / sum(generation_seconds)" if generation_rate is not None else None
        if generation_rate is None and len(metadata) == 1 and isinstance(metadata[0].get("generation_tokens_per_second"), (int, float)):
            generation_rate = metadata[0]["generation_tokens_per_second"]
            generation_rate_source = metadata[0].get("generation_throughput_source") or "provider_native_single_request"
        final_bytes = self.final.encode("utf-8")
        return {
            "prompt_tokens": prompt_tokens, "output_tokens": output_tokens,
            "generation_seconds": generation_seconds,
            "generation_tokens": generation_tokens,
            "generation_tokens_per_second": generation_rate,
            "generation_throughput_source": generation_rate_source,
            "prompt_processing_seconds": (
                total("prompt_processing_seconds")
                if total("prompt_processing_seconds") is not None
                else (total("prompt_eval_duration") / 1_000_000_000 if total("prompt_eval_duration") is not None else None)
            ),
            "model_turns": self.model_turns, "tool_calls": self.tool_calls,
            "denied_tool_calls": self.denied_calls, "test_tool_calls": len(self.test_calls),
            "max_validation_retries": self.max_validation_retries,
            "validation_failures": self.validation_failures,
            "validation_retry_turns": self.validation_retry_turns,
            "schema_normalizations": self.schema_normalizations,
            "repetition_detections": self.repetition_detections,
            "model_request_wall_seconds": sum(x["wall_seconds"] for x in responses),
            "final_output_characters": len(self.final), "final_output_bytes": len(final_bytes),
            "final_output_words": len(self.final.split()), "final_output_lines": len(self.final.splitlines()),
            "all_assistant_characters": sum(len(x.get("content") or "") for x in responses),
            "reasoning_characters": sum(len(x.get("reasoning") or "") for x in responses),
            "provider_metadata_per_turn": metadata,
            "residency_observation": metadata[0].get("residency_observation") if metadata else None,
            "residency_observations_per_turn": [x.get("residency_observation") for x in metadata],
            "os_file_cache_states_per_turn": [x.get("os_file_cache_state") for x in metadata],
            "successful_normalized_responses": len(responses),
            "failed_model_requests": sum(x["event_type"] == "model_error" for x in self.events),
        }
