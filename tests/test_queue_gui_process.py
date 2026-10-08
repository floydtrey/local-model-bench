from __future__ import annotations

import errno
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from localbench.queue_gui import process as module
from localbench.queue_gui.process import (
    InstanceAlreadyRunning,
    InstanceLock,
    ProcessRunner,
    list_ollama,
    process_is_running,
)


class ChunkStream:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.closed = False

    def read(self, _size):
        chunk = next(self.chunks, b"")
        if isinstance(chunk, Exception):
            raise chunk
        return chunk

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, chunks=(), exit_code=0):
        self.stdout = ChunkStream(chunks)
        self.pid = 42424
        self.exit_code = exit_code
        self.returncode = None

    def wait(self):
        self.returncode = self.exit_code
        return self.returncode

    def poll(self):
        return self.returncode


class ProcessTests(unittest.TestCase):
    def finish(self, runner, timeout=5):
        events = []
        deadline = time.monotonic() + timeout
        while True:
            event = runner.events.get(timeout=max(0.001, deadline - time.monotonic()))
            events.append(event)
            if event.kind == "finished":
                return events
            if time.monotonic() >= deadline:
                self.fail("Process did not finish before the test deadline")

    def test_partial_output_is_live_and_next_process_waits_for_acknowledgement(self):
        # A file handshake keeps the child alive until the test has RECEIVED its
        # partial output. A buffered-until-newline implementation cannot pass.
        with tempfile.TemporaryDirectory() as temp:
            gate = Path(temp) / "continue"
            code = (
                "import pathlib,sys,time; "
                "sys.stdout.write('partial'); sys.stdout.flush(); "
                "gate=pathlib.Path(sys.argv[1]); deadline=time.monotonic()+10\n"
                "while not gate.exists() and time.monotonic()<deadline: time.sleep(0.01)\n"
                "sys.stdout.write(' line\\n'); sys.stdout.flush(); "
                "sys.stderr.write('stderr evidence\\n'); sys.stderr.flush(); sys.exit(7)"
            )
            runner = ProcessRunner(encoding="utf-8")
            pid = runner.start("first", [sys.executable, "-u", "-c", code, str(gate)], temp)
            try:
                self.assertEqual(runner.pid, pid)
                first = runner.events.get(timeout=5)
                self.assertEqual((first.kind, first.item_id, first.text), ("output", "first", "partial"))
                self.assertTrue(runner.active)
                with self.assertRaises(RuntimeError):
                    runner.start("second", [sys.executable, "-c", "pass"], temp)
                with self.assertRaises(RuntimeError):
                    runner.acknowledge("first")
            finally:
                gate.touch()
                events = self.finish(runner)
            self.assertEqual(events[-1].exit_code, 7)
            self.assertIsNone(events[-1].error)
            self.assertIn("stderr evidence", "".join(event.text for event in events))
            self.assertTrue(runner.active)
            with self.assertRaises(RuntimeError):
                runner.start("second", [sys.executable, "-c", "pass"], temp)
            with self.assertRaises(ValueError):
                runner.acknowledge("wrong-item")
            runner.acknowledge("first")
            self.assertFalse(runner.active)
            self.assertIsNone(runner.pid)
            runner.start("second", [sys.executable, "-c", "pass"], temp)
            self.assertEqual(self.finish(runner)[-1].exit_code, 0)
            runner.acknowledge("second")

    def test_chunks_decode_incrementally_and_finish_follows_all_output(self):
        child = FakeProcess([b"caf\xc3", b"\xa9\n", b"RUN_DIR=C:\\runs\\one\n"], 3)
        runner = ProcessRunner(encoding="utf-8")
        with patch.object(module.subprocess, "Popen", return_value=child) as launch:
            runner.start("model", ["powershell.exe", "-File", "has spaces.ps1"], "repo root")
            events = self.finish(runner)
        self.assertEqual("".join(event.text for event in events), "caf\u00e9\nRUN_DIR=C:\\runs\\one\n")
        self.assertEqual([event.kind for event in events], ["output", "output", "output", "finished"])
        self.assertEqual(events[-1].exit_code, 3)
        self.assertTrue(child.stdout.closed)
        self.assertEqual(launch.call_args.args[0], ["powershell.exe", "-File", "has spaces.ps1"])
        self.assertFalse(launch.call_args.kwargs["shell"])
        self.assertEqual(launch.call_args.kwargs["cwd"], "repo root")
        self.assertEqual(launch.call_args.kwargs["stderr"], subprocess.STDOUT)
        self.assertEqual(launch.call_args.kwargs["bufsize"], 0)
        if not module._IS_WINDOWS:
            self.assertTrue(launch.call_args.kwargs["start_new_session"])
        runner.acknowledge("model")

    def test_launch_errors_leave_no_active_process_or_completion_event(self):
        runner = ProcessRunner()
        with patch.object(module.subprocess, "Popen", side_effect=FileNotFoundError("missing")):
            with self.assertRaises(FileNotFoundError):
                runner.start("model", ["missing-executable"], ".")
        self.assertFalse(runner.active)
        self.assertTrue(runner.events.empty())
        self.assertFalse(runner.emergency_stop())
        with self.assertRaises(ValueError):
            runner.start("model", "powershell -Command bad", ".")

    def test_read_error_still_waits_for_exit_before_finishing(self):
        child = FakeProcess([OSError("test pipe failure")], 9)
        runner = ProcessRunner()
        with patch.object(module.subprocess, "Popen", return_value=child):
            runner.start("model", ["stub"], ".")
            event = self.finish(runner)[-1]
        self.assertEqual(event.exit_code, 9)
        self.assertIn("test pipe failure", event.error)
        self.assertEqual(child.returncode, 9)
        runner.acknowledge("model")

    def test_windows_emergency_stop_targets_only_owned_pid_tree_off_ui_thread(self):
        exited = threading.Event()
        killing = threading.Event()
        permit_kill = threading.Event()
        child = FakeProcess()
        child.poll = lambda: 1 if exited.is_set() else None
        child.stdout.read = lambda _size: (exited.wait(5) and b"")
        child.wait = lambda: (exited.wait(5) and 1)

        def taskkill(*args, **kwargs):
            killing.set()
            if not permit_kill.wait(5):
                raise TimeoutError("test did not release taskkill")
            exited.set()
            return subprocess.CompletedProcess(args[0], 0, stdout=b"")

        runner = ProcessRunner()
        with patch.object(module, "_IS_WINDOWS", True), \
             patch.object(module.subprocess, "Popen", return_value=child) as launch, \
             patch.object(module.subprocess, "run", side_effect=taskkill) as terminate:
            runner.start("model", ["powershell.exe", "-File", "runner.ps1"], ".")
            try:
                self.assertTrue(runner.emergency_stop())
                self.assertTrue(killing.wait(3))
                self.assertTrue(runner.active)
                self.assertFalse(runner.emergency_stop())
                self.assertTrue(runner.events.empty())
            finally:
                permit_kill.set()
                self.finish(runner)
            self.assertEqual(terminate.call_args.args[0], ["taskkill.exe", "/PID", "42424", "/T", "/F"])
            self.assertFalse(terminate.call_args.kwargs["shell"])
            self.assertEqual(terminate.call_args.kwargs["timeout"], 20)
            self.assertTrue(launch.call_args.kwargs["creationflags"] & module._CREATE_NEW_PROCESS_GROUP)
            self.assertFalse(runner.emergency_stop())
            runner.acknowledge("model")

    @unittest.skipIf(os.name == "nt", "POSIX process groups only")
    def test_posix_emergency_reaps_owned_process(self):
        runner = ProcessRunner()
        runner.start("model", [sys.executable, "-u", "-c", "import time; print('ready'); time.sleep(30)"], ".")
        try:
            self.assertIn("ready", runner.events.get(timeout=5).text)
        finally:
            runner.emergency_stop()
            event = self.finish(runner)[-1]
        self.assertLess(event.exit_code, 0)
        runner.acknowledge("model")

    def test_failed_emergency_stop_keeps_the_actual_benchmark_active(self):
        exited = threading.Event()
        child = FakeProcess()
        child.poll = lambda: 0 if exited.is_set() else None
        child.stdout.read = lambda _size: (exited.wait(5) and b"")
        child.wait = lambda: (exited.wait(5) and 0)
        failure = subprocess.CompletedProcess([], 1, stdout=b"Access denied")
        runner = ProcessRunner()
        with patch.object(module, "_IS_WINDOWS", True), \
             patch.object(module.subprocess, "Popen", return_value=child), \
             patch.object(module.subprocess, "run", return_value=failure):
            runner.start("model", ["stub"], ".")
            try:
                self.assertTrue(runner.emergency_stop())
                event = runner.events.get(timeout=5)
                self.assertEqual(event.kind, "output")
                self.assertIn("Access denied", event.text)
                self.assertTrue(runner.active)
                with self.assertRaises(RuntimeError):
                    runner.start("next", ["stub"], ".")
            finally:
                exited.set()
                events = self.finish(runner)
            self.assertEqual(events[-1].exit_code, 0)
            runner.acknowledge("model")

    @unittest.skipUnless(os.name == "nt", "Requires actual Windows PowerShell")
    def test_real_powershell_file_wrapper_argument_unicode_output_and_exit(self):
        from localbench.queue_gui.core import BenchmarkSettings, build_command, parse_run_dir

        # This temporary script deliberately occupies the CLI's relative path;
        # neither the real benchmark runner nor Ollama is ever invoked.
        with tempfile.TemporaryDirectory(prefix="queue gui ") as temp:
            repo = Path(temp)
            scripts = repo / "tools" / "campaigns"
            scripts.mkdir(parents=True)
            gate = scripts / "continue"
            (scripts / "run-all-roles.ps1").write_text(
                "[CmdletBinding()]\n"
                "param([string]$Runtime, [string]$Model, [string]$Phase, [string]$GovernorRoot)\n"
                "$ErrorActionPreference = 'Stop'\n"
                "[Console]::Out.WriteLine(\"ARGS=$Runtime|$Model|$Phase|$GovernorRoot\")\n"
                "$RunPath = 'C:\\Bench runs\\Jos' + [char]233\n"
                "[Console]::Out.WriteLine(\"PS_PATH=$RunPath\")\n"
                "[Console]::Out.Flush()\n"
                "[Console]::Error.WriteLine('PS_STDERR=evidence')\n"
                "[Console]::Error.Flush()\n"
                "& $env:QUEUE_TEST_PYTHON -u (Join-Path $PSScriptRoot 'child.py') (Join-Path $PSScriptRoot 'continue')\n"
                "exit $LASTEXITCODE\n",
                encoding="ascii",
            )
            (scripts / "child.py").write_text(
                "import pathlib, sys, time\n"
                "print('RUN_DIR=C:\\\\Bench runs\\\\Jos' + chr(233), flush=True)\n"
                "gate = pathlib.Path(sys.argv[1]); deadline = time.monotonic() + 15\n"
                "while not gate.exists() and time.monotonic() < deadline: time.sleep(0.01)\n"
                "sys.stderr.write('NATIVE_STDERR=evidence\\n'); sys.stderr.flush()\n"
                "sys.exit(17)\n",
                encoding="ascii",
            )
            governor = str(repo / "governor root with spaces")
            settings = BenchmarkSettings(phase="qualification", governor_root=governor)
            command = build_command(repo, "qwen:9b", settings)
            runner = ProcessRunner()
            text = ""
            with patch.dict(os.environ, {"QUEUE_TEST_PYTHON": sys.executable}):
                runner.start("windows-stub", command, repo)
                try:
                    deadline = time.monotonic() + 10
                    while "RUN_DIR=" not in text or "\n" not in text.split("RUN_DIR=", 1)[-1]:
                        event = runner.events.get(timeout=max(0.001, deadline - time.monotonic()))
                        self.assertEqual(event.kind, "output", event.error)
                        text += event.text
                        if time.monotonic() >= deadline:
                            self.fail("PowerShell did not stream the stub output before exit")
                    self.assertIn(f"ARGS=ollama|qwen:9b|qualification|{governor}", text)
                    self.assertIn("PS_PATH=C:\\Bench runs\\Jos\u00e9", text)
                    self.assertIn("C:\\Bench runs\\Jos\u00e9", [parse_run_dir(line) for line in text.splitlines()])
                    self.assertTrue(runner.active)
                finally:
                    gate.touch()
                    events = self.finish(runner, timeout=10)
                text += "".join(event.text for event in events)
                self.assertIn("PS_STDERR=evidence", text)
                self.assertIn("NATIVE_STDERR=evidence", text)
                self.assertEqual(events[-1].exit_code, 17)
                self.assertIsNone(events[-1].error)
                runner.acknowledge("windows-stub")


class ListingAndLockTests(unittest.TestCase):
    def test_model_listing_uses_the_same_local_host_as_the_cli(self):
        result = subprocess.CompletedProcess([], 0, stdout=b"NAME ID SIZE MODIFIED\nqwen:9b abc 6GB now\n", stderr=b"")
        with patch.dict(os.environ, {"OLLAMA_HOST": "https://different-host.example"}), \
             patch.object(module.subprocess, "run", return_value=result) as run:
            self.assertIn("qwen:9b", list_ollama())
            self.assertEqual(os.environ["OLLAMA_HOST"], "https://different-host.example")
        self.assertEqual(run.call_args.args[0], ["ollama", "list"])
        self.assertEqual(run.call_args.kwargs["env"]["OLLAMA_HOST"], "http://127.0.0.1:11434")
        self.assertEqual(run.call_args.kwargs["timeout"], 15)
        self.assertFalse(run.call_args.kwargs["shell"])

    def test_listing_explains_missing_command_timeout_and_cli_error(self):
        for error, expected in [(FileNotFoundError(), "not found"), (subprocess.TimeoutExpired("ollama", 15), "timed out")]:
            with self.subTest(error=error), patch.object(module.subprocess, "run", side_effect=error):
                with self.assertRaisesRegex(RuntimeError, expected):
                    list_ollama()
        result = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"Ollama server unavailable")
        with patch.object(module.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "server unavailable"):
                list_ollama()

    def test_instance_lock_blocks_second_handle_and_survives_stale_lock_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "queue.lock"
            second = InstanceLock(path)
            with InstanceLock(path) as first:
                self.assertIs(first.acquire(), first)
                with self.assertRaises(InstanceAlreadyRunning):
                    second.acquire()
            self.assertTrue(path.exists())
            with second:
                with self.assertRaises(InstanceAlreadyRunning):
                    InstanceLock(path).acquire()
            second.close()
            with InstanceLock(path):
                pass

    def test_native_recovery_probe_sees_this_process(self):
        self.assertIs(process_is_running(os.getpid()), True)
        self.assertIsNone(process_is_running(None))
        self.assertIsNone(process_is_running(-1))

    def test_posix_recovery_probe_never_sends_a_terminating_signal(self):
        with patch.object(module, "_IS_WINDOWS", False), patch.object(module.os, "kill") as check:
            self.assertIs(process_is_running(12345), True)
            check.assert_called_once_with(12345, 0)
            check.side_effect = ProcessLookupError(errno.ESRCH, "gone")
            self.assertIs(process_is_running(12345), False)
            check.side_effect = PermissionError(errno.EPERM, "unverifiable")
            self.assertIsNone(process_is_running(12345))

    def test_windows_recovery_uses_wait_handle_and_closes_it(self):
        kernel = Mock()
        kernel.OpenProcess.return_value = 123
        with patch("ctypes.WinDLL", return_value=kernel, create=True):
            for status, expected in [(0, False), (258, True), (0xFFFFFFFF, None)]:
                kernel.WaitForSingleObject.return_value = status
                self.assertIs(module._windows_process_is_running(456), expected)
        kernel.OpenProcess.assert_called_with(0x00100000, False, 456)
        kernel.WaitForSingleObject.assert_called_with(123, 0)
        self.assertEqual(kernel.CloseHandle.call_count, 3)

    def test_windows_recovery_distinguishes_gone_from_unknown(self):
        kernel = Mock()
        kernel.OpenProcess.return_value = None
        with patch("ctypes.WinDLL", return_value=kernel, create=True), \
             patch("ctypes.get_last_error", create=True) as error:
            error.return_value = 87
            self.assertIs(module._windows_process_is_running(12345), False)
            error.return_value = 5
            self.assertIsNone(module._windows_process_is_running(12345))
        kernel.CloseHandle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
