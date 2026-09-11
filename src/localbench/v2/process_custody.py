from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from .containment import (
    BackendExecution,
    CommandSpec,
    ContainmentBlocked,
    ContainmentCapabilities,
    ContainmentPolicy,
    preflight,
    validate_assessor_staging,
)


STRICT_PROCESS_BACKEND_VERSION = "benchmark-lab-strict-process-backend:v1"


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction and isjunction(str(path)))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tree_state(root: Path) -> dict[str, tuple[str, int]]:
    root = Path(root).resolve(strict=True)
    state: dict[str, tuple[str, int]] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        kept: list[str] = []
        for name in sorted(directories):
            path = current_path / name
            if _link_like(path):
                raise ContainmentBlocked("workspace contains a symlink/junction directory")
            kept.append(name)
        directories[:] = kept
        for name in sorted(files):
            path = current_path / name
            if _link_like(path) or not path.is_file():
                raise ContainmentBlocked("workspace contains a link or non-regular file")
            raw = path.read_bytes()
            state[path.relative_to(root).as_posix()] = (_sha256_bytes(raw), len(raw))
    return state


def _copy_tree(source: Path, destination: Path) -> None:
    source = Path(source).resolve(strict=True)
    if destination.exists():
        raise ContainmentBlocked("sandbox destination already exists")
    destination.mkdir(parents=True)
    for current, directories, files in os.walk(source, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(source)
        target_dir = destination / relative
        target_dir.mkdir(parents=True, exist_ok=True)
        kept: list[str] = []
        for name in sorted(directories):
            path = current_path / name
            if _link_like(path):
                raise ContainmentBlocked("workspace contains a symlink/junction directory")
            kept.append(name)
            (target_dir / name).mkdir(exist_ok=True)
        directories[:] = kept
        for name in sorted(files):
            path = current_path / name
            if _link_like(path) or not path.is_file():
                raise ContainmentBlocked("workspace contains a link or non-regular file")
            shutil.copy2(path, target_dir / name)


def _changed_paths(before: Mapping[str, tuple[str, int]], after: Mapping[str, tuple[str, int]]) -> set[str]:
    return {
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    }


def _safe_target(root: Path, relative: str) -> Path:
    target = root.joinpath(*relative.split("/"))
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    current = root
    for part in relative.split("/")[:-1]:
        current = current / part
        if _link_like(current):
            raise ContainmentBlocked("authorized promotion path traverses a link/junction")
    return target


def _promote_authorized(
    *,
    sandbox: Path,
    original: Path,
    changed: set[str],
    writable: set[str],
) -> None:
    unauthorized = sorted(changed - writable)
    if unauthorized:
        raise ContainmentBlocked(
            "sandbox changed paths outside writable scope: " + ", ".join(unauthorized)
        )
    for relative in sorted(changed):
        source = sandbox.joinpath(*relative.split("/"))
        target = _safe_target(original, relative)
        if not source.exists():
            if target.exists():
                if _link_like(target) or not target.is_file():
                    raise ContainmentBlocked("authorized deletion target is not a regular file")
                target.unlink()
            continue
        if _link_like(source) or not source.is_file():
            raise ContainmentBlocked("authorized output became a link or non-regular file")
        if target.exists() and (_link_like(target) or not target.is_file()):
            raise ContainmentBlocked("authorized output target is not a regular file")
        raw = source.read_bytes()
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


class _CombinedCapture:
    def __init__(self, maximum: int | None) -> None:
        self.maximum = maximum
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.overflow = threading.Event()
        self._lock = threading.Lock()
        self._total = 0

    def reader(self, stream: Any, target: bytearray) -> None:
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                with self._lock:
                    if self.maximum is None:
                        target.extend(chunk)
                        self._total += len(chunk)
                        continue
                    remaining = self.maximum - self._total
                    if remaining > 0:
                        accepted = chunk[:remaining]
                        target.extend(accepted)
                        self._total += len(accepted)
                    if len(chunk) > max(remaining, 0):
                        self.overflow.set()
                        return
        finally:
            try:
                stream.close()
            except Exception:
                pass


class _WindowsJob:
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9
    PROCESS_TERMINATE = 0x0001
    PROCESS_SET_QUOTA = 0x0100

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows job object requested on non-Windows host")
        from ctypes import wintypes

        class LARGE_INTEGER(ctypes.Structure):
            _fields_ = [("QuadPart", ctypes.c_longlong)]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", LARGE_INTEGER),
                ("PerJobUserTimeLimit", LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel32.SetInformationJobObject(
            self.handle,
            self.JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = ctypes.get_last_error()
            self.close()
            raise OSError(error, "SetInformationJobObject failed")

    def assign(self, pid: int) -> None:
        handle = self.kernel32.OpenProcess(
            self.PROCESS_TERMINATE | self.PROCESS_SET_QUOTA,
            False,
            pid,
        )
        if not handle:
            raise OSError(ctypes.get_last_error(), "OpenProcess failed")
        try:
            if not self.kernel32.AssignProcessToJobObject(self.handle, handle):
                raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
        finally:
            self.kernel32.CloseHandle(handle)

    def close(self) -> None:
        handle = getattr(self, "handle", None)
        if handle:
            self.kernel32.CloseHandle(handle)
            self.handle = None


class StrictProcessBackend:
    """Strict process-tree/wall/output backend with disposable workspace promotion.

    Network access is intentionally supported only when the policy explicitly
    permits task network. Memory limits and assessor isolation are not claimed by
    this backend and therefore still fail containment preflight when requested.
    """

    @property
    def capabilities(self) -> ContainmentCapabilities:
        return ContainmentCapabilities(
            backend_id="strict-process",
            backend_version="1",
            wall_clock_timeout=True,
            process_custody="strict",
            network_policies=("task_allowed",),
            workspace_isolation=True,
            workspace_write_scope=True,
            assessor_isolation=False,
            output_limit=True,
            memory_limit=False,
        )

    def _rewrite_command(self, command: CommandSpec, sandbox: Path) -> tuple[list[str], dict[str, str]]:
        original = command.cwd
        argv: list[str] = []
        for index, item in enumerate(command.argv):
            if index == 0:
                argv.append(item)
                continue
            try:
                candidate = Path(item)
                if candidate.is_absolute():
                    relative = candidate.resolve(strict=False).relative_to(original)
                    argv.append(str(sandbox / relative))
                    continue
            except (OSError, ValueError):
                pass
            argv.append(item)
        env = os.environ.copy()
        if command.environment is not None:
            for key, value in command.environment.items():
                if str(original) in value:
                    raise ContainmentBlocked(
                        f"environment value {key!r} exposes original workspace locator"
                    )
                env[key] = value
        return argv, env

    def _start_worker(
        self,
        *,
        request: Mapping[str, Any],
        capture: _CombinedCapture,
    ) -> tuple[subprocess.Popen[bytes], Any, list[threading.Thread]]:
        kwargs: dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        custody: Any = None
        if os.name == "nt":
            process = subprocess.Popen(
                [sys.executable, "-m", "localbench.v2._containment_worker"],
                **kwargs,
            )
            custody = _WindowsJob()
            try:
                custody.assign(process.pid)
            except BaseException:
                custody.close()
                process.kill()
                process.wait()
                raise
        else:
            process = subprocess.Popen(
                [sys.executable, "-m", "localbench.v2._containment_worker"],
                start_new_session=True,
                **kwargs,
            )
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        threads = [
            threading.Thread(target=capture.reader, args=(process.stdout, capture.stdout), daemon=True),
            threading.Thread(target=capture.reader, args=(process.stderr, capture.stderr), daemon=True),
        ]
        for thread in threads:
            thread.start()
        process.stdin.write(json.dumps(request, sort_keys=True).encode("utf-8"))
        process.stdin.close()
        return process, custody, threads

    def _kill_tree(self, process: subprocess.Popen[bytes], custody: Any) -> bool:
        success = True
        if os.name == "nt":
            try:
                if custody is not None:
                    custody.close()
            except BaseException:
                success = False
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                success = False
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            success = False
            try:
                process.kill()
                process.wait(timeout=5)
            except BaseException:
                success = False
        return success

    def execute(self, command: CommandSpec, policy: ContainmentPolicy) -> BackendExecution:
        preflight(policy, self.capabilities).require_allowed()
        original = command.cwd
        before = _tree_state(original)
        with tempfile.TemporaryDirectory(prefix="localbench-contained-") as temp_name:
            sandbox = Path(temp_name) / "workspace"
            _copy_tree(original, sandbox)
            argv, env = self._rewrite_command(command, sandbox)
            capture = _CombinedCapture(policy.max_output_bytes)
            request = {"command": argv, "cwd": str(sandbox), "env": env}
            started = time.monotonic()
            process: subprocess.Popen[bytes] | None = None
            custody: Any = None
            threads: list[threading.Thread] = []
            stop_reason = "spawn_error"
            status = "error"
            exit_code: int | None = None
            cleanup = False
            try:
                process, custody, threads = self._start_worker(request=request, capture=capture)
                while True:
                    if capture.overflow.is_set():
                        status = "resource_limit"
                        stop_reason = "output_limit"
                        break
                    exit_code = process.poll()
                    if exit_code is not None:
                        status = "completed"
                        stop_reason = "process_exit"
                        break
                    if time.monotonic() - started >= policy.wall_seconds:
                        status = "timeout"
                        stop_reason = "wall_clock_limit"
                        break
                    time.sleep(min(0.02, max(0.001, policy.wall_seconds / 100.0)))
            except BaseException as exc:
                status = "error"
                stop_reason = f"spawn_error:{type(exc).__name__}"
                capture.stderr.extend(str(exc).encode("utf-8", errors="replace"))
            finally:
                if process is not None:
                    cleanup = self._kill_tree(process, custody)
                for thread in threads:
                    thread.join(timeout=5)
            duration = max(0.0, time.monotonic() - started)
            if status == "completed" and exit_code == 0:
                try:
                    after = _tree_state(sandbox)
                    changed = _changed_paths(before, after)
                    _promote_authorized(
                        sandbox=sandbox,
                        original=original,
                        changed=changed,
                        writable=set(policy.writable_paths or ()),
                    )
                except ContainmentBlocked as exc:
                    status = "resource_limit"
                    stop_reason = "workspace_scope_violation"
                    capture.stderr.extend(str(exc).encode("utf-8", errors="replace"))
            return BackendExecution(
                status=status,
                stop_reason=stop_reason,
                exit_code=exit_code,
                stdout=bytes(capture.stdout),
                stderr=bytes(capture.stderr),
                duration_seconds=duration,
                cleanup_performed=cleanup,
            )


class StrictAssessorBackend(StrictProcessBackend):
    """StrictProcessBackend with assessor staging proof enabled.

    The caller must provide the V1/V2 workspace record and confirm the candidate
    has reached a terminal state. Assessment material remains outside the
    candidate stage and execution still occurs in a disposable copy.
    """

    def __init__(self, *, workspace_record: Mapping[str, Any], candidate_terminal: bool) -> None:
        validate_assessor_staging(workspace_record, candidate_terminal=candidate_terminal)

    @property
    def capabilities(self) -> ContainmentCapabilities:
        base = super().capabilities
        return ContainmentCapabilities(
            backend_id="strict-assessor-process",
            backend_version="1",
            wall_clock_timeout=base.wall_clock_timeout,
            process_custody=base.process_custody,
            network_policies=base.network_policies,
            workspace_isolation=base.workspace_isolation,
            workspace_write_scope=base.workspace_write_scope,
            assessor_isolation=True,
            output_limit=base.output_limit,
            memory_limit=base.memory_limit,
        )
