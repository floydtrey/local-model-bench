from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from ..util import validate_id
from .contracts import SealedEvidence, canonical_json_bytes, seal_evidence, sha256_json


CONTAINMENT_POLICY_VERSION = "benchmark-lab-containment-policy:v1"
CONTAINMENT_EXECUTION_VERSION = "benchmark-lab-containment-execution:v1"
NETWORK_POLICIES = frozenset({"disabled", "provider_only", "task_allowed"})
PROCESS_CUSTODY_LEVELS = frozenset({"best_effort", "strict"})


class ContainmentBlocked(RuntimeError):
    """Raised when a requested qualification policy cannot be proven/enforced."""


class ContainmentProtocolError(ValueError):
    pass


def _freeze_json(value: Any) -> Any:
    import json

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


def _relative_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("write-scope paths must be non-empty strings")
    if "\\" in value or "\x00" in value or any(ord(ch) < 32 for ch in value):
        raise ValueError("write-scope paths must use canonical forward-slash syntax")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts:
        raise ValueError("write-scope paths must be relative")
    for part in path.parts:
        if part in {"", ".", ".."} or part.casefold() == ".git" or ":" in part:
            raise ValueError("write-scope paths contain a forbidden segment")
    normalized = path.as_posix()
    if normalized != value:
        raise ValueError("write-scope paths must already be canonical")
    return normalized


def _positive_number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or float(value) <= 0:
        raise ValueError(f"{label} must be > 0")
    return float(value)


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be an integer >= 1")
    return value


@dataclass(frozen=True)
class ContainmentPolicy:
    wall_seconds: float
    max_attempts: int
    network_policy: str
    process_custody: str = "strict"
    require_workspace_isolation: bool = True
    require_assessor_isolation: bool = True
    writable_paths: tuple[str, ...] | None = None
    max_output_bytes: int | None = None
    max_memory_bytes: int | None = None
    schema_version: str = CONTAINMENT_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CONTAINMENT_POLICY_VERSION:
            raise ValueError(f"schema_version must equal {CONTAINMENT_POLICY_VERSION!r}")
        object.__setattr__(self, "wall_seconds", _positive_number(self.wall_seconds, "wall_seconds"))
        object.__setattr__(self, "max_attempts", _positive_int(self.max_attempts, "max_attempts"))
        if self.network_policy not in NETWORK_POLICIES:
            raise ValueError(f"network_policy must be one of {sorted(NETWORK_POLICIES)}")
        if self.process_custody not in PROCESS_CUSTODY_LEVELS:
            raise ValueError(f"process_custody must be one of {sorted(PROCESS_CUSTODY_LEVELS)}")
        if not isinstance(self.require_workspace_isolation, bool):
            raise ValueError("require_workspace_isolation must be boolean")
        if not isinstance(self.require_assessor_isolation, bool):
            raise ValueError("require_assessor_isolation must be boolean")
        if self.writable_paths is not None:
            normalized = tuple(sorted(_relative_path(item) for item in self.writable_paths))
            if len(normalized) != len(set(normalized)):
                raise ValueError("writable_paths must not contain duplicates")
            object.__setattr__(self, "writable_paths", normalized)
        for field_name in ("max_output_bytes", "max_memory_bytes"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _positive_int(value, field_name))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "wall_seconds": self.wall_seconds,
            "max_attempts": self.max_attempts,
            "network_policy": self.network_policy,
            "process_custody": self.process_custody,
            "require_workspace_isolation": self.require_workspace_isolation,
            "require_assessor_isolation": self.require_assessor_isolation,
            "writable_paths": None if self.writable_paths is None else list(self.writable_paths),
            "max_output_bytes": self.max_output_bytes,
            "max_memory_bytes": self.max_memory_bytes,
        }

    @property
    def sha256(self) -> str:
        return sha256_json(self.to_dict())


@dataclass(frozen=True)
class ContainmentCapabilities:
    backend_id: str
    backend_version: str
    wall_clock_timeout: bool
    process_custody: str
    network_policies: tuple[str, ...]
    workspace_isolation: bool
    workspace_write_scope: bool
    assessor_isolation: bool
    output_limit: bool
    memory_limit: bool

    def __post_init__(self) -> None:
        validate_id(self.backend_id, "backend_id")
        if not isinstance(self.backend_version, str) or not self.backend_version:
            raise ValueError("backend_version must be a non-empty string")
        if self.process_custody not in {"none", "best_effort", "strict"}:
            raise ValueError("unsupported process custody level")
        policies = tuple(sorted(set(self.network_policies)))
        if any(item not in NETWORK_POLICIES for item in policies):
            raise ValueError("backend advertises an unknown network policy")
        object.__setattr__(self, "network_policies", policies)
        for name in (
            "wall_clock_timeout",
            "workspace_isolation",
            "workspace_write_scope",
            "assessor_isolation",
            "output_limit",
            "memory_limit",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "wall_clock_timeout": self.wall_clock_timeout,
            "process_custody": self.process_custody,
            "network_policies": list(self.network_policies),
            "workspace_isolation": self.workspace_isolation,
            "workspace_write_scope": self.workspace_write_scope,
            "assessor_isolation": self.assessor_isolation,
            "output_limit": self.output_limit,
            "memory_limit": self.memory_limit,
        }


@dataclass(frozen=True)
class ContainmentPreflight:
    policy_sha256: str
    backend: ContainmentCapabilities
    issues: tuple[str, ...]

    @property
    def allowed(self) -> bool:
        return not self.issues

    def require_allowed(self) -> None:
        if self.issues:
            raise ContainmentBlocked("containment policy cannot be proven: " + "; ".join(self.issues))


def preflight(policy: ContainmentPolicy, capabilities: ContainmentCapabilities) -> ContainmentPreflight:
    issues: list[str] = []
    if not capabilities.wall_clock_timeout:
        issues.append("wall_clock_timeout_not_enforced")
    custody_rank = {"none": 0, "best_effort": 1, "strict": 2}
    if custody_rank[capabilities.process_custody] < custody_rank[policy.process_custody]:
        issues.append("process_custody_too_weak")
    if policy.network_policy not in capabilities.network_policies:
        issues.append(f"network_policy_not_enforced:{policy.network_policy}")
    if policy.require_workspace_isolation and not capabilities.workspace_isolation:
        issues.append("workspace_isolation_not_enforced")
    if policy.writable_paths is None:
        issues.append("workspace_write_scope_unresolved")
    elif not capabilities.workspace_write_scope:
        issues.append("workspace_write_scope_not_enforced")
    if policy.require_assessor_isolation and not capabilities.assessor_isolation:
        issues.append("assessor_isolation_not_enforced")
    if policy.max_output_bytes is not None and not capabilities.output_limit:
        issues.append("output_limit_not_enforced")
    if policy.max_memory_bytes is not None and not capabilities.memory_limit:
        issues.append("memory_limit_not_enforced")
    return ContainmentPreflight(policy.sha256, capabilities, tuple(issues))


@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    argv: tuple[str, ...]
    cwd: Path
    cwd_role: str = "candidate_workspace"
    environment: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        validate_id(self.command_id, "command_id")
        argv = tuple(self.argv)
        if not argv or any(not isinstance(item, str) or not item for item in argv):
            raise ValueError("argv must contain at least one non-empty string")
        object.__setattr__(self, "argv", argv)
        cwd = Path(self.cwd).resolve(strict=True)
        if not cwd.is_dir():
            raise ValueError("cwd must be an existing directory")
        object.__setattr__(self, "cwd", cwd)
        validate_id(self.cwd_role, "cwd_role")
        if self.environment is not None:
            env = dict(self.environment)
            if any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
                raise ValueError("environment must map strings to strings")
            object.__setattr__(self, "environment", MappingProxyType(env))

    @property
    def command_sha256(self) -> str:
        return sha256_json({"command_id": self.command_id, "argv": list(self.argv), "cwd_role": self.cwd_role})


@dataclass(frozen=True)
class BackendExecution:
    status: str
    stop_reason: str
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    duration_seconds: float
    cleanup_performed: bool

    def __post_init__(self) -> None:
        if self.status not in {"completed", "timeout", "error", "resource_limit"}:
            raise ValueError("unsupported backend execution status")
        if not isinstance(self.stdout, bytes) or not isinstance(self.stderr, bytes):
            raise ValueError("stdout/stderr must be bytes")
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds cannot be negative")


class ContainmentBackend(Protocol):
    @property
    def capabilities(self) -> ContainmentCapabilities: ...

    def execute(self, command: CommandSpec, policy: ContainmentPolicy) -> BackendExecution: ...


def _kill_native_tree(process: subprocess.Popen[bytes]) -> bool:
    if process.poll() is not None:
        return False
    try:
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if completed.returncode != 0 and process.poll() is None:
                process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        return True
    except Exception:
        try:
            process.kill()
            return True
        except Exception:
            return False


class NativeSubprocessBackend:
    """Portable command runner with deliberately limited containment claims.

    It enforces a wall timeout and attempts process-tree cleanup, but it does not
    claim strict custody, network isolation, filesystem write confinement, or
    assessor isolation. Qualification policies requiring those properties fail
    preflight rather than being silently downgraded.
    """

    @property
    def capabilities(self) -> ContainmentCapabilities:
        return ContainmentCapabilities(
            backend_id="native-subprocess",
            backend_version="1",
            wall_clock_timeout=True,
            process_custody="best_effort",
            network_policies=("task_allowed",),
            workspace_isolation=False,
            workspace_write_scope=False,
            assessor_isolation=False,
            output_limit=False,
            memory_limit=False,
        )

    def execute(self, command: CommandSpec, policy: ContainmentPolicy) -> BackendExecution:
        preflight(policy, self.capabilities).require_allowed()
        env = os.environ.copy()
        if command.environment is not None:
            env.update(dict(command.environment))
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                list(command.argv),
                cwd=str(command.cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                **kwargs,
            )
        except Exception as exc:
            duration = max(0.0, time.monotonic() - started)
            return BackendExecution(
                status="error",
                stop_reason=f"spawn_error:{type(exc).__name__}",
                exit_code=None,
                stdout=b"",
                stderr=str(exc).encode("utf-8", errors="replace"),
                duration_seconds=duration,
                cleanup_performed=False,
            )
        try:
            stdout, stderr = process.communicate(timeout=policy.wall_seconds)
            duration = max(0.0, time.monotonic() - started)
            return BackendExecution(
                status="completed",
                stop_reason="process_exit",
                exit_code=process.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                cleanup_performed=False,
            )
        except subprocess.TimeoutExpired:
            cleaned = _kill_native_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                cleaned = True
            duration = max(0.0, time.monotonic() - started)
            return BackendExecution(
                status="timeout",
                stop_reason="wall_clock_limit",
                exit_code=process.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                cleanup_performed=cleaned,
            )


@dataclass(frozen=True)
class ContainedAttemptResult:
    status: str
    stop_reason: str
    attempt: int
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    evidence: SealedEvidence

    def __post_init__(self) -> None:
        if self.evidence.record_type != "containment_execution":
            raise ValueError("evidence must be containment_execution")


class ContainmentExecutor:
    def __init__(self, backend: ContainmentBackend, policy: ContainmentPolicy) -> None:
        self._backend = backend
        self._policy = policy
        self._attempts_used = 0
        self._preflight = preflight(policy, backend.capabilities)

    @property
    def preflight(self) -> ContainmentPreflight:
        return self._preflight

    @property
    def attempts_used(self) -> int:
        return self._attempts_used

    def execute(self, command: CommandSpec) -> ContainedAttemptResult:
        self._preflight.require_allowed()
        if self._attempts_used >= self._policy.max_attempts:
            raise ContainmentBlocked("maximum attempt count has already been consumed")
        self._attempts_used += 1
        attempt = self._attempts_used
        started_utc = time.time()
        result = self._backend.execute(command, self._policy)
        finished_utc = time.time()
        stdout_sha = hashlib.sha256(result.stdout).hexdigest()
        stderr_sha = hashlib.sha256(result.stderr).hexdigest()
        payload = {
            "execution_version": CONTAINMENT_EXECUTION_VERSION,
            "policy": self._policy.to_dict(),
            "policy_sha256": self._policy.sha256,
            "backend": self._backend.capabilities.to_dict(),
            "command_id": command.command_id,
            "command_sha256": command.command_sha256,
            "cwd_role": command.cwd_role,
            "attempt": attempt,
            "status": result.status,
            "stop_reason": result.stop_reason,
            "exit_code": result.exit_code,
            "started_unix_seconds": started_utc,
            "finished_unix_seconds": finished_utc,
            "duration_seconds": result.duration_seconds,
            "cleanup_performed": result.cleanup_performed,
            "stdout": {
                "sha256": stdout_sha,
                "size_bytes": len(result.stdout),
                "utf8": result.stdout.decode("utf-8", errors="replace"),
            },
            "stderr": {
                "sha256": stderr_sha,
                "size_bytes": len(result.stderr),
                "utf8": result.stderr.decode("utf-8", errors="replace"),
            },
        }
        evidence = seal_evidence(
            "containment_execution",
            f"containment-{attempt}-{command.command_id}",
            payload,
        )
        return ContainedAttemptResult(
            status=result.status,
            stop_reason=result.stop_reason,
            attempt=attempt,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            evidence=evidence,
        )


def validate_assessor_staging(
    workspace_record: Mapping[str, Any], *, candidate_terminal: bool
) -> None:
    """Fail closed unless assessor material remained out of candidate staging."""

    if not isinstance(workspace_record, Mapping):
        raise ContainmentProtocolError("workspace record must be an object")
    if workspace_record.get("assessment_included") is not False:
        raise ContainmentBlocked("assessor material was included in the candidate workspace")
    if not candidate_terminal:
        raise ContainmentBlocked("assessor stage cannot begin before candidate execution is terminal")
