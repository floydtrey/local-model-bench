from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from ..util import validate_id
from .contracts import SealedEvidence, canonical_json_bytes, seal_evidence, sha256_json


TOOL_HARNESS_VERSION = "benchmark-lab-bounded-tool-harness:v1"
TOOL_TRACE_VERSION = "benchmark-lab-tool-trace:v1"
BOUNDED_FILE_SURFACE_ID = "lab-bounded-files:v1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")

BOUNDED_FILE_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "read_file",
        "description": "Read one explicitly authorized UTF-8 file by exact relative path.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["path"],
            "properties": {"path": {"type": "string", "minLength": 1}},
        },
    },
    {
        "name": "write_file",
        "description": (
            "Atomically write one explicitly authorized UTF-8 file. "
            "expected_sha256 is null only for creation and otherwise must match the current file."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["path", "content", "expected_sha256"],
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "content": {"type": "string"},
                "expected_sha256": {
                    "anyOf": [
                        {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                        {"type": "null"},
                    ]
                },
            },
        },
    },
)

BOUNDED_FILE_TOOL_SCHEMA_SHA256 = sha256_json(
    {
        "surface_id": BOUNDED_FILE_SURFACE_ID,
        "tools": BOUNDED_FILE_TOOL_DEFINITIONS,
    }
)


class HarnessProtocolError(ValueError):
    pass


class WorkspaceSafetyError(ValueError):
    pass


def _freeze_json(value: Any) -> Any:
    normalized = json.loads(canonical_json_bytes(value).decode("utf-8"))

    def freeze(item: Any) -> Any:
        if isinstance(item, dict):
            return MappingProxyType({key: freeze(child) for key, child in item.items()})
        if isinstance(item, list):
            return tuple(freeze(child) for child in item)
        return item

    return freeze(normalized)


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise WorkspaceSafetyError("path must be a non-empty string")
    if "\\" in value:
        raise WorkspaceSafetyError("paths must use forward slashes")
    if "\x00" in value or any(ord(char) < 32 for char in value):
        raise WorkspaceSafetyError("path contains a control character")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise WorkspaceSafetyError("absolute paths are forbidden")
    parts = path.parts
    if not parts:
        raise WorkspaceSafetyError("path must identify a file")
    for part in parts:
        if part in {"", ".", ".."}:
            raise WorkspaceSafetyError("dot and traversal path segments are forbidden")
        if part.casefold() == ".git":
            raise WorkspaceSafetyError(".git paths are forbidden")
        if ":" in part:
            raise WorkspaceSafetyError("colon path syntax is forbidden")
    normalized = path.as_posix()
    if normalized != value:
        raise WorkspaceSafetyError("path must already be in canonical relative form")
    return normalized


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction and isjunction(str(path)))


def _safe_existing_components(root: Path, relative: str) -> None:
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink() or current.exists():
            if _link_like(current):
                raise WorkspaceSafetyError(f"link-like path component is forbidden: {relative}")


def _ensure_within_root(root: Path, relative: str) -> Path:
    _safe_existing_components(root, relative)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WorkspaceSafetyError("resolved path escapes workspace root") from exc
    return candidate


def _scope_list(values: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be a sequence of relative paths")
    normalized = tuple(_normalize_relative_path(item) for item in values)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} must not contain duplicate paths")
    return tuple(sorted(normalized))


def _event(sequence: int, event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    validate_id(event_type, "event_type")
    body = {
        "sequence": sequence,
        "event_type": event_type,
        "payload": _thaw_json(payload),
    }
    return {**body, "event_sha256": sha256_json(body)}


def _snapshot_sha(files: Sequence[Mapping[str, Any]]) -> str:
    return sha256_json([_thaw_json(item) for item in files])


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        validate_id(self.call_id, "call_id")
        validate_id(self.name, "tool name")
        if not isinstance(self.arguments, Mapping):
            raise HarnessProtocolError("tool call arguments must be an object")
        object.__setattr__(self, "arguments", _freeze_json(dict(self.arguments)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "arguments": _thaw_json(self.arguments),
        }


@dataclass(frozen=True)
class ModelTurnResponse:
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()

    def __post_init__(self) -> None:
        if self.content is not None and not isinstance(self.content, str):
            raise HarnessProtocolError("model response content must be a string or null")
        calls = tuple(self.tool_calls)
        if any(not isinstance(call, ToolCall) for call in calls):
            raise HarnessProtocolError("tool_calls must contain ToolCall values")
        ids = [call.call_id for call in calls]
        if len(ids) != len(set(ids)):
            raise HarnessProtocolError("tool call IDs must be unique within one response")
        if not calls and self.content is None:
            raise HarnessProtocolError("model response must contain content or at least one tool call")
        object.__setattr__(self, "tool_calls", calls)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
        }


@dataclass(frozen=True)
class ModelTurnRequest:
    case_id: str
    turn: int
    messages: tuple[Mapping[str, Any], ...]
    context_assets: tuple[Mapping[str, Any], ...]
    tools: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        validate_id(self.case_id, "case_id")
        if not isinstance(self.turn, int) or isinstance(self.turn, bool) or self.turn < 1:
            raise HarnessProtocolError("turn must be an integer >= 1")
        object.__setattr__(self, "messages", tuple(_freeze_json(item) for item in self.messages))
        object.__setattr__(
            self, "context_assets", tuple(_freeze_json(item) for item in self.context_assets)
        )
        object.__setattr__(self, "tools", tuple(_freeze_json(item) for item in self.tools))

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "turn": self.turn,
            "messages": [_thaw_json(item) for item in self.messages],
            "context_assets": [_thaw_json(item) for item in self.context_assets],
            "tools": [_thaw_json(item) for item in self.tools],
        }


ModelDriver = Callable[[ModelTurnRequest], ModelTurnResponse]


@dataclass(frozen=True)
class HarnessRunResult:
    status: str
    stop_reason: str
    terminal_output: Mapping[str, Any] | None
    trace: SealedEvidence

    def __post_init__(self) -> None:
        if self.status not in {
            "success",
            "error",
            "blocked",
            "resource_limit",
            "protocol_failure",
        }:
            raise ValueError("unsupported harness result status")
        if self.trace.record_type != "tool_execution_trace":
            raise ValueError("trace must be tool_execution_trace evidence")
        if self.terminal_output is not None:
            object.__setattr__(self, "terminal_output", _freeze_json(self.terminal_output))


class BoundedWorkspace:
    """Exact-file UTF-8 workspace used by the neutral lab tool surface."""

    def __init__(
        self,
        root: Path,
        *,
        readable_paths: Sequence[str],
        writable_paths: Sequence[str],
    ) -> None:
        resolved = Path(root).resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("workspace root must be an existing directory")
        self.root = resolved
        self.readable_paths = _scope_list(readable_paths, "readable_paths")
        self.writable_paths = _scope_list(writable_paths, "writable_paths")
        self._readable = frozenset(self.readable_paths)
        self._writable = frozenset(self.writable_paths)
        for relative in sorted(self._readable | self._writable):
            target = _ensure_within_root(self.root, relative)
            if target.exists() and not target.is_file():
                raise WorkspaceSafetyError(f"authorized path is not a regular file: {relative}")
            if relative in self._writable:
                parent = target.parent
                if not parent.exists() or not parent.is_dir():
                    raise WorkspaceSafetyError(
                        f"parent directory for writable path does not exist: {relative}"
                    )
                parent_rel = parent.relative_to(self.root).as_posix()
                if parent_rel != ".":
                    _safe_existing_components(self.root, parent_rel)

    def scope(self) -> dict[str, list[str]]:
        return {
            "readable_paths": list(self.readable_paths),
            "writable_paths": list(self.writable_paths),
        }

    def snapshot(self) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        for relative in sorted(self._readable | self._writable):
            target = _ensure_within_root(self.root, relative)
            if not target.exists():
                files.append({"path": relative, "state": "missing", "sha256": None, "size_bytes": None})
                continue
            if not target.is_file():
                raise WorkspaceSafetyError(f"authorized path stopped being a regular file: {relative}")
            raw = target.read_bytes()
            files.append(
                {
                    "path": relative,
                    "state": "file",
                    "sha256": _sha256_bytes(raw),
                    "size_bytes": len(raw),
                }
            )
        return {"files": files, "snapshot_sha256": _snapshot_sha(files)}

    def authorize(self, call: ToolCall) -> tuple[bool, str, str | None]:
        if call.name not in {"read_file", "write_file"}:
            return False, "tool_not_exposed", None
        arguments = _thaw_json(call.arguments)
        expected_keys = {"path"} if call.name == "read_file" else {
            "path",
            "content",
            "expected_sha256",
        }
        if set(arguments) != expected_keys:
            return False, "invalid_arguments", None
        try:
            relative = _normalize_relative_path(arguments.get("path"))
        except WorkspaceSafetyError:
            return False, "invalid_path", None
        if call.name == "read_file":
            if relative not in self._readable:
                return False, "path_not_readable", relative
        else:
            if relative not in self._writable:
                return False, "path_not_writable", relative
            if not isinstance(arguments.get("content"), str):
                return False, "invalid_arguments", relative
            expected = arguments.get("expected_sha256")
            if expected is not None and (
                not isinstance(expected, str) or not SHA256.fullmatch(expected)
            ):
                return False, "invalid_arguments", relative
        try:
            _ensure_within_root(self.root, relative)
        except WorkspaceSafetyError:
            return False, "unsafe_workspace_path", relative
        return True, "allowed", relative

    def execute(self, call: ToolCall, relative: str) -> dict[str, Any]:
        if call.name == "read_file":
            return self._read(relative)
        if call.name == "write_file":
            args = _thaw_json(call.arguments)
            return self._write(
                relative,
                content=args["content"],
                expected_sha256=args["expected_sha256"],
            )
        raise AssertionError("authorization must reject unknown tools")

    def _read(self, relative: str) -> dict[str, Any]:
        target = _ensure_within_root(self.root, relative)
        if not target.exists():
            return {"ok": False, "path": relative, "error": "file_missing"}
        if not target.is_file():
            return {"ok": False, "path": relative, "error": "not_regular_file"}
        raw = target.read_bytes()
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {"ok": False, "path": relative, "error": "not_utf8"}
        return {
            "ok": True,
            "path": relative,
            "content": content,
            "sha256": _sha256_bytes(raw),
            "size_bytes": len(raw),
        }

    def _write(
        self,
        relative: str,
        *,
        content: str,
        expected_sha256: str | None,
    ) -> dict[str, Any]:
        target = _ensure_within_root(self.root, relative)
        existed = target.exists()
        if existed:
            if not target.is_file():
                return {"ok": False, "path": relative, "error": "not_regular_file"}
            try:
                links = target.stat().st_nlink
            except OSError:
                return {"ok": False, "path": relative, "error": "stat_failed"}
            if links != 1:
                return {"ok": False, "path": relative, "error": "hardlink_write_forbidden"}
            current = target.read_bytes()
            current_sha = _sha256_bytes(current)
            if expected_sha256 is None:
                return {
                    "ok": False,
                    "path": relative,
                    "error": "target_exists_expected_creation",
                    "current_sha256": current_sha,
                }
            if current_sha != expected_sha256:
                return {
                    "ok": False,
                    "path": relative,
                    "error": "stale_write",
                    "expected_sha256": expected_sha256,
                    "current_sha256": current_sha,
                }
        elif expected_sha256 is not None:
            return {
                "ok": False,
                "path": relative,
                "error": "target_missing",
                "expected_sha256": expected_sha256,
            }

        raw = content.encode("utf-8")
        fd, temp_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
        return {
            "ok": True,
            "path": relative,
            "created": not existed,
            "sha256": _sha256_bytes(raw),
            "size_bytes": len(raw),
        }


def _validate_surface_binding(
    case_definition: Mapping[str, Any], effective_config: SealedEvidence
) -> int:
    if effective_config.record_type != "effective_runtime_config":
        raise ValueError("effective_config must be effective_runtime_config evidence")
    requirements = case_definition.get("requirements")
    if not isinstance(requirements, Mapping):
        raise ValueError("case_definition.requirements must be an object")
    required_surface = requirements.get("tool_surface")
    if not isinstance(required_surface, Mapping):
        raise ValueError("case_definition.requirements.tool_surface must be an object")
    if required_surface.get("id") != BOUNDED_FILE_SURFACE_ID:
        raise ValueError(
            f"case must require tool surface {BOUNDED_FILE_SURFACE_ID!r}"
        )
    required_tools = required_surface.get("required_tools")
    if not isinstance(required_tools, Sequence) or isinstance(
        required_tools, (str, bytes, bytearray)
    ):
        raise ValueError("case required_tools must be an array")
    expected_tools = [item["name"] for item in BOUNDED_FILE_TOOL_DEFINITIONS]
    if list(required_tools) != expected_tools:
        raise ValueError(f"case must require tools in canonical order: {expected_tools}")

    surface = effective_config.payload.get("tool_surface")
    if not isinstance(surface, Mapping):
        raise ValueError("effective config tool_surface is unavailable")
    if surface.get("id") != BOUNDED_FILE_SURFACE_ID:
        raise ValueError("effective config tool surface does not match harness")
    if list(surface.get("tools", ())) != expected_tools:
        raise ValueError("effective config tools do not match harness")
    if surface.get("schema_sha256") != BOUNDED_FILE_TOOL_SCHEMA_SHA256:
        raise ValueError("effective config tool schema digest does not match harness")
    maximum = surface.get("max_tool_calls")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
        raise ValueError("effective config max_tool_calls must be an integer >= 1")
    return maximum


def _trace_payload(
    *,
    case_id: str,
    workspace: BoundedWorkspace,
    initial_workspace: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    final_workspace: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "trace_version": TOOL_TRACE_VERSION,
        "harness_version": TOOL_HARNESS_VERSION,
        "case_id": case_id,
        "tool_surface": {
            "id": BOUNDED_FILE_SURFACE_ID,
            "tools": [item["name"] for item in BOUNDED_FILE_TOOL_DEFINITIONS],
            "schema_sha256": BOUNDED_FILE_TOOL_SCHEMA_SHA256,
        },
        "scope": workspace.scope(),
        "initial_workspace": _thaw_json(initial_workspace),
        "events": [_thaw_json(item) for item in events],
        "final_workspace": _thaw_json(final_workspace),
        "summary": _thaw_json(summary),
    }


def validate_tool_execution_trace(trace: SealedEvidence) -> None:
    if trace.record_type != "tool_execution_trace":
        raise ValueError("expected tool_execution_trace evidence")
    payload = trace.payload
    if payload.get("trace_version") != TOOL_TRACE_VERSION:
        raise ValueError("unsupported tool trace version")
    if payload.get("harness_version") != TOOL_HARNESS_VERSION:
        raise ValueError("unsupported tool harness version")
    surface = payload.get("tool_surface")
    if not isinstance(surface, Mapping):
        raise ValueError("tool trace surface is missing")
    if surface.get("id") != BOUNDED_FILE_SURFACE_ID:
        raise ValueError("tool trace surface ID mismatch")
    if surface.get("schema_sha256") != BOUNDED_FILE_TOOL_SCHEMA_SHA256:
        raise ValueError("tool trace schema digest mismatch")
    for snapshot_name in ("initial_workspace", "final_workspace"):
        snapshot = payload.get(snapshot_name)
        if not isinstance(snapshot, Mapping):
            raise ValueError(f"{snapshot_name} must be an object")
        files = snapshot.get("files")
        if not isinstance(files, (list, tuple)):
            raise ValueError(f"{snapshot_name}.files must be an array")
        if snapshot.get("snapshot_sha256") != _snapshot_sha(files):
            raise ValueError(f"{snapshot_name} digest mismatch")
    events = payload.get("events")
    if not isinstance(events, (list, tuple)):
        raise ValueError("events must be an array")
    for index, item in enumerate(events, start=1):
        if not isinstance(item, Mapping):
            raise ValueError("every trace event must be an object")
        if item.get("sequence") != index:
            raise ValueError("trace event sequence is not contiguous")
        body = {
            "sequence": item.get("sequence"),
            "event_type": item.get("event_type"),
            "payload": _thaw_json(item.get("payload")),
        }
        if item.get("event_sha256") != sha256_json(body):
            raise ValueError("trace event digest mismatch")


def run_bounded_tool_harness(
    *,
    trace_logical_id: str,
    case_definition: Mapping[str, Any],
    effective_config: SealedEvidence,
    workspace_root: Path,
    readable_paths: Sequence[str],
    writable_paths: Sequence[str],
    driver: ModelDriver,
) -> HarnessRunResult:
    """Execute one synthetic/real L2 case through the neutral bounded file loop.

    This function does not enforce wall-clock, process, or network containment;
    those are BL-7 responsibilities. It does enforce the BL-6 tool authority
    boundary and records a replayable normalized event stream.
    """

    validate_id(trace_logical_id, "trace_logical_id")
    if not isinstance(case_definition, Mapping):
        raise ValueError("case_definition must be an object")
    case_id = validate_id(case_definition.get("case_id"), "case_id")
    maximum_tool_calls = _validate_surface_binding(case_definition, effective_config)
    case_input = case_definition.get("input")
    if not isinstance(case_input, Mapping):
        raise ValueError("case_definition.input must be an object")
    messages_raw = case_input.get("messages")
    assets_raw = case_input.get("context_assets", [])
    if not isinstance(messages_raw, Sequence) or isinstance(messages_raw, (str, bytes, bytearray)):
        raise ValueError("case messages must be an array")
    if not isinstance(assets_raw, Sequence) or isinstance(assets_raw, (str, bytes, bytearray)):
        raise ValueError("case context_assets must be an array")

    workspace = BoundedWorkspace(
        Path(workspace_root),
        readable_paths=readable_paths,
        writable_paths=writable_paths,
    )
    initial_workspace = workspace.snapshot()
    messages = [_thaw_json(item) for item in messages_raw]
    context_assets = [_thaw_json(item) for item in assets_raw]
    events: list[dict[str, Any]] = []
    sequence = 0
    model_turns = 0
    tool_calls = 0
    authorized_calls = 0
    denied_calls = 0
    successful_tools = 0
    failed_tools = 0

    def append_event(event_type: str, payload: Mapping[str, Any]) -> None:
        nonlocal sequence
        sequence += 1
        events.append(_event(sequence, event_type, payload))

    def finish(
        status: str,
        stop_reason: str,
        terminal_output: Mapping[str, Any] | None,
    ) -> HarnessRunResult:
        final_workspace = workspace.snapshot()
        summary = {
            "status": status,
            "stop_reason": stop_reason,
            "model_turns": model_turns,
            "tool_calls": tool_calls,
            "authorized_tool_calls": authorized_calls,
            "denied_tool_calls": denied_calls,
            "successful_tool_calls": successful_tools,
            "failed_tool_calls": failed_tools,
            "terminal_output_sha256": None
            if terminal_output is None
            else terminal_output.get("sha256"),
        }
        trace = seal_evidence(
            "tool_execution_trace",
            trace_logical_id,
            _trace_payload(
                case_id=case_id,
                workspace=workspace,
                initial_workspace=initial_workspace,
                events=events,
                final_workspace=final_workspace,
                summary=summary,
            ),
        )
        validate_tool_execution_trace(trace)
        return HarnessRunResult(
            status=status,
            stop_reason=stop_reason,
            terminal_output=terminal_output,
            trace=trace,
        )

    while True:
        model_turns += 1
        request = ModelTurnRequest(
            case_id=case_id,
            turn=model_turns,
            messages=tuple(messages),
            context_assets=tuple(context_assets),
            tools=tuple(BOUNDED_FILE_TOOL_DEFINITIONS),
        )
        append_event("model_request", request.to_dict())
        try:
            response = driver(request)
        except Exception as exc:  # provider adapters will map richer failures later
            append_event(
                "model_error",
                {"error_type": type(exc).__name__, "detail": str(exc)},
            )
            return finish("error", "model_driver_error", None)
        if not isinstance(response, ModelTurnResponse):
            append_event(
                "protocol_error",
                {"reason": "driver_returned_invalid_response_type"},
            )
            return finish("protocol_failure", "invalid_model_response", None)
        append_event("model_response", response.to_dict())

        if not response.tool_calls:
            content = response.content or ""
            raw = content.encode("utf-8")
            terminal = {
                "kind": "assistant_text",
                "content": content,
                "sha256": _sha256_bytes(raw),
                "size_bytes": len(raw),
            }
            append_event("terminal_output", terminal)
            return finish("success", "terminal_output", terminal)

        messages.append(
            {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [call.to_dict() for call in response.tool_calls],
            }
        )

        for call in response.tool_calls:
            if tool_calls >= maximum_tool_calls:
                append_event(
                    "limit_reached",
                    {
                        "limit": "max_tool_calls",
                        "maximum": maximum_tool_calls,
                        "blocked_call": call.to_dict(),
                    },
                )
                return finish("resource_limit", "max_tool_calls", None)
            tool_calls += 1
            append_event("tool_request", call.to_dict())
            allowed, reason, relative = workspace.authorize(call)
            append_event(
                "tool_authorization",
                {
                    "call_id": call.call_id,
                    "tool": call.name,
                    "allowed": allowed,
                    "reason": reason,
                    "path": relative,
                },
            )
            if not allowed:
                denied_calls += 1
                result = {
                    "ok": False,
                    "error": "authorization_denied",
                    "reason": reason,
                    "path": relative,
                }
            else:
                authorized_calls += 1
                try:
                    result = workspace.execute(call, relative or "")
                except Exception as exc:
                    result = {
                        "ok": False,
                        "error": "tool_execution_error",
                        "error_type": type(exc).__name__,
                    }
                if result.get("ok") is True:
                    successful_tools += 1
                else:
                    failed_tools += 1
            append_event(
                "tool_result",
                {
                    "call_id": call.call_id,
                    "tool": call.name,
                    "result": result,
                },
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "name": call.name,
                    "result": result,
                }
            )
