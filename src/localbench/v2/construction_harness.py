from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import sha256_json
from .tool_harness import BoundedWorkspace, ToolCall, WorkspaceSafetyError


CONSTRUCTION_HARNESS_VERSION = "benchmark-lab-construction-harness:v1"
CONSTRUCTION_TOOL_SURFACE_ID = "lab-construction-tools:v1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


CONSTRUCTION_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
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
            "Atomically create or update one explicitly authorized UTF-8 file. "
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
    {
        "name": "delete_file",
        "description": (
            "Delete one explicitly authorized regular file. expected_sha256 must match "
            "the current file so stale or guessed deletions fail closed."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["path", "expected_sha256"],
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "expected_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
            },
        },
    },
    {
        "name": "run_command",
        "description": (
            "Run one task-preauthorized command by opaque command_id inside the disposable project workspace. "
            "Arbitrary shell text is never accepted."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["command_id"],
            "properties": {
                "command_id": {"type": "string", "minLength": 1},
            },
        },
    },
)

CONSTRUCTION_TOOL_SCHEMA_SHA256 = sha256_json(
    {
        "surface_id": CONSTRUCTION_TOOL_SURFACE_ID,
        "tools": CONSTRUCTION_TOOL_DEFINITIONS,
    }
)


def _canonical_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkspaceSafetyError("path must be a non-empty string")
    if "\\" in value or "\x00" in value or any(ord(char) < 32 for char in value):
        raise WorkspaceSafetyError("path must use canonical forward-slash syntax")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts:
        raise WorkspaceSafetyError("path must be relative")
    for part in path.parts:
        if part in {"", ".", ".."} or part.casefold() == ".git" or ":" in part:
            raise WorkspaceSafetyError("path contains a forbidden segment")
    normalized = path.as_posix()
    if normalized != value:
        raise WorkspaceSafetyError("path must already be canonical")
    return normalized


def _inside(root: Path, relative: str) -> Path:
    target = root.joinpath(*PurePosixPath(relative).parts)
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WorkspaceSafetyError("resolved path escapes workspace root") from exc
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.exists() and (
            current.is_symlink()
            or getattr(os.path, "isjunction", lambda _: False)(str(current))
        ):
            raise WorkspaceSafetyError("link-like path components are forbidden")
    return target


@dataclass(frozen=True)
class AuthorizedCommand:
    command_id: str
    argv: tuple[str, ...]
    timeout_seconds: int = 120
    max_output_bytes: int = 262_144

    def __post_init__(self) -> None:
        if not isinstance(self.command_id, str) or not self.command_id:
            raise ValueError("command_id must be a non-empty string")
        if not self.argv or any(not isinstance(item, str) or not item for item in self.argv):
            raise ValueError("argv must contain non-empty strings")
        if not isinstance(self.timeout_seconds, int) or self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be a positive integer")
        if not isinstance(self.max_output_bytes, int) or self.max_output_bytes < 1:
            raise ValueError("max_output_bytes must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "argv": list(self.argv),
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
        }


@dataclass(frozen=True)
class ConstructionScope:
    readable_paths: tuple[str, ...]
    writable_paths: tuple[str, ...]
    deletable_paths: tuple[str, ...]
    commands: tuple[AuthorizedCommand, ...]

    def __post_init__(self) -> None:
        for field_name in ("readable_paths", "writable_paths", "deletable_paths"):
            values = tuple(
                _canonical_relative_path(item) for item in getattr(self, field_name)
            )
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must not contain duplicates")
            object.__setattr__(self, field_name, tuple(sorted(values)))
        commands = tuple(self.commands)
        if any(not isinstance(item, AuthorizedCommand) for item in commands):
            raise ValueError("commands must contain AuthorizedCommand values")
        ids = [item.command_id for item in commands]
        if len(ids) != len(set(ids)):
            raise ValueError("command IDs must be unique")
        object.__setattr__(self, "commands", commands)

    def tool_context(self) -> dict[str, Any]:
        return {
            "surface_id": CONSTRUCTION_TOOL_SURFACE_ID,
            "readable_paths": list(self.readable_paths),
            "writable_paths": list(self.writable_paths),
            "deletable_paths": list(self.deletable_paths),
            "commands": [
                {
                    "command_id": item.command_id,
                    "description": "task-authorized deterministic command",
                }
                for item in self.commands
            ],
        }


class ConstructionWorkspace:
    """Bounded mutation and command authority for a disposable project copy."""

    def __init__(self, root: Path, scope: ConstructionScope) -> None:
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("construction workspace root must be an existing directory")
        self.scope = scope
        self.files = BoundedWorkspace(
            self.root,
            readable_paths=scope.readable_paths,
            writable_paths=scope.writable_paths,
        )
        self._deletable = frozenset(scope.deletable_paths)
        self._commands = {item.command_id: item for item in scope.commands}
        for relative in self._deletable:
            target = _inside(self.root, relative)
            if target.exists() and not target.is_file():
                raise WorkspaceSafetyError(
                    f"deletable path is not a regular file: {relative}"
                )

    def snapshot(self) -> dict[str, Any]:
        base = self.files.snapshot()
        known = {item["path"]: item for item in base["files"]}
        for relative in sorted(self._deletable):
            if relative in known:
                continue
            target = _inside(self.root, relative)
            if not target.exists():
                known[relative] = {
                    "path": relative,
                    "state": "missing",
                    "sha256": None,
                    "size_bytes": None,
                }
            else:
                raw = target.read_bytes()
                known[relative] = {
                    "path": relative,
                    "state": "file",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size_bytes": len(raw),
                }
        files = [known[key] for key in sorted(known)]
        return {"files": files, "snapshot_sha256": sha256_json(files)}

    def execute(self, call: ToolCall) -> dict[str, Any]:
        if call.name in {"read_file", "write_file"}:
            allowed, reason, relative = self.files.authorize(call)
            if not allowed or relative is None:
                return {"ok": False, "error": reason}
            return self.files.execute(call, relative)
        if call.name == "delete_file":
            return self._delete(call)
        if call.name == "run_command":
            return self._run(call)
        return {"ok": False, "error": "tool_not_exposed"}

    def _delete(self, call: ToolCall) -> dict[str, Any]:
        args = dict(call.arguments)
        if set(args) != {"path", "expected_sha256"}:
            return {"ok": False, "error": "invalid_arguments"}
        try:
            relative = _canonical_relative_path(args["path"])
        except (KeyError, WorkspaceSafetyError):
            return {"ok": False, "error": "invalid_path"}
        if relative not in self._deletable:
            return {"ok": False, "path": relative, "error": "path_not_deletable"}
        expected = args.get("expected_sha256")
        if not isinstance(expected, str) or not SHA256.fullmatch(expected):
            return {"ok": False, "path": relative, "error": "invalid_arguments"}
        target = _inside(self.root, relative)
        if not target.exists():
            return {"ok": False, "path": relative, "error": "file_missing"}
        if not target.is_file():
            return {"ok": False, "path": relative, "error": "not_regular_file"}
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected:
            return {
                "ok": False,
                "path": relative,
                "error": "sha256_mismatch",
                "actual_sha256": actual,
            }
        target.unlink()
        return {"ok": True, "path": relative, "deleted_sha256": actual}

    def _run(self, call: ToolCall) -> dict[str, Any]:
        args = dict(call.arguments)
        if set(args) != {"command_id"} or not isinstance(
            args.get("command_id"), str
        ):
            return {"ok": False, "error": "invalid_arguments"}
        command = self._commands.get(args["command_id"])
        if command is None:
            return {"ok": False, "error": "command_not_authorized"}
        try:
            completed = subprocess.run(
                list(command.argv),
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=command.timeout_seconds,
                shell=False,
                check=False,
                env={
                    **os.environ,
                    "PYTHONNOUSERSITE": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or b"")[: command.max_output_bytes]
            stderr = (exc.stderr or b"")[: command.max_output_bytes]
            return {
                "ok": False,
                "command_id": command.command_id,
                "error": "timeout",
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            }
        stdout = completed.stdout[: command.max_output_bytes]
        stderr = completed.stderr[: command.max_output_bytes]
        truncated = (
            len(completed.stdout) > command.max_output_bytes
            or len(completed.stderr) > command.max_output_bytes
        )
        return {
            "ok": completed.returncode == 0,
            "command_id": command.command_id,
            "exit_code": completed.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "output_truncated": truncated,
        }


def construction_scope_sha256(scope: ConstructionScope) -> str:
    return sha256_json(
        {
            "tool_surface_id": CONSTRUCTION_TOOL_SURFACE_ID,
            "tool_schema_sha256": CONSTRUCTION_TOOL_SCHEMA_SHA256,
            "scope": scope.tool_context(),
            "commands": [item.to_dict() for item in scope.commands],
        }
    )
