"""Small subprocess and instance-lock helpers; no benchmark or Tkinter logic."""

from __future__ import annotations

import codecs
import errno
import locale
import os
import queue
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


_IS_WINDOWS = os.name == "nt"
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000
OLLAMA_BASE_URL = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class ProcessEvent:
    kind: str  # "output" or "finished"
    item_id: str
    text: str = ""
    exit_code: int | None = None
    error: str | None = None


class ProcessRunner:
    """Own one child at a time and publish events for the UI thread to consume.

    ``start`` raises synchronously if launching fails; no event is published in
    that case. A successful run stays active until its finished event has been
    handled and ``acknowledge(item_id)`` is called. Neither worker thread calls
    Tkinter or changes the persistent queue.
    """

    def __init__(self, *, encoding: str | None = None) -> None:
        # Bound pending output to roughly 1 MiB of raw chunks. Backpressure keeps
        # all markers/events intact while a modal dialog temporarily stops polls.
        self.events: queue.Queue[ProcessEvent] = queue.Queue(maxsize=256)
        self.encoding = encoding or locale.getpreferredencoding(False)
        codecs.lookup(self.encoding)
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._item_id: str | None = None
        self._finished = False
        self._stop_requested = False
        self._stop_done = threading.Event()
        self._stop_done.set()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._process is not None

    @property
    def pid(self) -> int | None:
        with self._lock:
            return self._process.pid if self._process is not None else None

    def start(self, item_id: str, command: Sequence[str], cwd: Path | str) -> int:
        if isinstance(command, (str, bytes)) or not command:
            raise ValueError("Pass a nonempty argument list, not a shell command string.")
        with self._lock:
            if self._process is not None:
                raise RuntimeError("A benchmark is still active or awaiting acknowledgement.")
            options: dict = {"creationflags": _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW} if _IS_WINDOWS else {"start_new_session": True}
            process = subprocess.Popen(
                list(command), cwd=str(cwd), shell=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, bufsize=0, **options,
            )
            self._process = process
            self._item_id = item_id
            self._finished = False
            self._stop_requested = False
            self._stop_done = threading.Event()
            self._stop_done.set()
            threading.Thread(
                target=self._read, args=(item_id, process, self._stop_done),
                name="benchmark-output", daemon=True,
            ).start()
            return process.pid

    def acknowledge(self, item_id: str) -> None:
        """Release a completed run, after the caller consumes its final event."""
        with self._lock:
            if self._item_id != item_id:
                raise ValueError("Completion does not belong to the active queue item.")
            if not self._finished:
                raise RuntimeError("The benchmark has not finished.")
            self._process = None
            self._item_id = None
            self._finished = False

    def _read(self, item_id: str, process: subprocess.Popen[bytes], stop_done: threading.Event) -> None:
        decoder = codecs.getincrementaldecoder(self.encoding)(errors="replace")
        error = None
        assert process.stdout is not None
        try:
            # bufsize=0 makes this a raw read: partial lines are delivered now,
            # not held until a newline or a full buffered read becomes available.
            while chunk := process.stdout.read(4096):
                text = decoder.decode(chunk)
                if text:
                    self.events.put(ProcessEvent("output", item_id, text=text))
            tail = decoder.decode(b"", final=True)
            if tail:
                self.events.put(ProcessEvent("output", item_id, text=tail))
        except (OSError, ValueError) as exc:
            error = f"Unable to read benchmark output: {exc}"
            self.events.put(ProcessEvent(
                "output", item_id,
                text=f"\n[Queue] {error}. Waiting for the benchmark process to exit.\n",
            ))
        finally:
            process.stdout.close()
        # A pipe error is not permission to overlap another run. Reap the child
        # before publishing completion, even when its output could not be read.
        exit_code = process.wait()
        stop_done.wait()
        with self._lock:
            self._finished = True
        self.events.put(ProcessEvent("finished", item_id, exit_code=exit_code, error=error))

    def emergency_stop(self) -> bool:
        """Request termination of this instance's live child tree, off the UI thread.

        Returns False if no live owned child exists or a request is already in
        progress. Recovered PIDs are never adopted or terminated by this class.
        Completion is still reported only after the actual child exits.
        """
        with self._lock:
            process = self._process
            if process is None or self._finished or self._stop_requested or process.poll() is not None:
                return False
            self._stop_requested = True
            self._stop_done.clear()
            threading.Thread(
                target=self._terminate, args=(self._item_id, process, self._stop_done),
                name="benchmark-emergency-stop", daemon=True,
            ).start()
            return True

    def _terminate(self, item_id: str, process: subprocess.Popen[bytes], stop_done: threading.Event) -> None:
        try:
            if process.poll() is None:
                if _IS_WINDOWS:
                    result = subprocess.run(
                        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                        shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, timeout=20, creationflags=_CREATE_NO_WINDOW,
                    )
                    if result.returncode and process.poll() is None:
                        detail = result.stdout.decode(self.encoding, errors="replace").strip()
                        raise OSError(detail or f"taskkill exited {result.returncode}")
                else:
                    # start_new_session=True gives only this launch its own group.
                    os.killpg(process.pid, signal.SIGKILL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            if process.poll() is None:
                self.events.put(ProcessEvent(
                    "output", item_id,
                    text=f"\n[Queue] Emergency stop failed: {exc}. Benchmark remains active.\n",
                ))
        finally:
            with self._lock:
                self._stop_requested = False
            stop_done.set()


def list_ollama() -> str:
    """Run the read-only local model listing; callers should use a worker thread."""
    env = os.environ.copy()
    # Match run-all-roles.ps1's V1 default, even if the shell targets another host.
    env["OLLAMA_HOST"] = OLLAMA_BASE_URL
    options = {"creationflags": _CREATE_NO_WINDOW} if _IS_WINDOWS else {}
    try:
        result = subprocess.run(
            ["ollama", "list"], shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            timeout=15, check=False, **options,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Ollama was not found. Make sure ollama is on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ollama list timed out after 15 seconds.") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"ollama list exited {result.returncode}.")
    return result.stdout.decode("utf-8", errors="replace")


class InstanceAlreadyRunning(RuntimeError):
    """Another GUI instance holds the state-file lock."""


class InstanceLock:
    """OS-held lock; its persistent file is harmless after a crash or close."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._file = None

    def acquire(self) -> InstanceLock:
        if self._file is not None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if _IS_WINDOWS:
                import msvcrt
                if stream.seek(0, os.SEEK_END) == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise InstanceAlreadyRunning("Another benchmark queue GUI is using this checkout.") from exc
            raise
        self._file = stream
        return self

    def close(self) -> None:
        stream, self._file = self._file, None
        if stream is None:
            return
        try:
            if _IS_WINDOWS:
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()
        # Never unlink: another instance may already hold this same file's lock.

    def __enter__(self) -> InstanceLock:
        return self.acquire()

    def __exit__(self, *_exc) -> None:
        self.close()


def process_is_running(pid: int | None) -> bool | None:
    """Read-only recovery probe: True=live, False=gone, None=unverifiable.

    Callers must treat None conservatively. This does not establish process
    identity or authorize termination, even if a saved PID is currently live.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if _IS_WINDOWS:
        return _windows_process_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OSError, OverflowError):
        return None
    return True


def _windows_process_is_running(pid: int) -> bool | None:
    import ctypes
    from ctypes import wintypes

    if pid > 0xFFFFFFFF:
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
    if not handle:
        return False if ctypes.get_last_error() == 87 else None
    try:
        status = kernel.WaitForSingleObject(handle, 0)
        return {0: False, 258: True}.get(status)
    finally:
        kernel.CloseHandle(handle)
