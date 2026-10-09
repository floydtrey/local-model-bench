"""Real Tk widgets with controlled discovery and runner events; never benchmarks."""

from __future__ import annotations

import os
import gc
from pathlib import Path
from queue import Queue
import tempfile
import time
import threading
import weakref
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import tkinter as tk
except ImportError:
    tk = None


class FakeRunner:
    """A process stays active until the GUI acknowledges its finished event."""

    def __init__(self):
        self.events = Queue()
        self.active = False
        self.started = []
        self.current_item_id = None
        self.emergency_calls = 0

    def start(self, item_id, argv, cwd):
        if self.active:
            raise AssertionError("The GUI attempted concurrent benchmark launches")
        self.active = True
        self.current_item_id = item_id
        self.started.append((item_id, list(argv), Path(cwd)))
        return 2_147_483_000 + len(self.started)

    def output(self, text):
        self.events.put(SimpleNamespace(
            kind="output", item_id=self.current_item_id,
            text=text, exit_code=None, error=None,
        ))

    def finish(self, exit_code=0, error=None):
        self.events.put(SimpleNamespace(
            kind="finished", item_id=self.current_item_id,
            text="", exit_code=exit_code, error=error,
        ))

    def acknowledge(self, item_id):
        if item_id != self.current_item_id:
            raise AssertionError("The GUI acknowledged a different process")
        self.active = False
        self.current_item_id = None

    def emergency_stop(self):
        self.emergency_calls += 1
        return self.active


class QueueGuiWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_tk = os.environ.get("LOCALBENCH_REQUIRE_TK") == "1"
        if tk is None:
            if require_tk:
                raise RuntimeError("Required Tkinter module is unavailable")
            raise unittest.SkipTest("Tkinter is unavailable in this environment")
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.update()
            probe.destroy()
        except tk.TclError as exc:
            if require_tk:
                raise RuntimeError("Required real Tk display could not start") from exc
            raise unittest.SkipTest(f"A Tk display is unavailable: {exc}") from exc
        from localbench.queue_gui.app import BenchmarkQueueApp
        cls.app_type = BenchmarkQueueApp

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="localbench-gui-test-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        runner_script = self.repo / "tools" / "campaigns" / "run-all-roles.ps1"
        runner_script.parent.mkdir(parents=True)
        runner_script.write_text("# Test fixture; never executed.\n", encoding="utf-8")
        proxy_script = self.repo / "tools" / "gui" / "run-queue-item.ps1"
        proxy_script.parent.mkdir(parents=True)
        proxy_script.write_text("# Test fixture; never executed.\n", encoding="utf-8")
        self.governor = self.repo / "governor"
        self.governor.mkdir()
        self.state_path = self.repo / "queue-state.json"
        self.tags = ["alpha:small", "beta:medium", "gamma:large"]
        self.discovery_calls = 0
        no_processes = patch(
            "subprocess.Popen",
            side_effect=AssertionError("Widget tests must never launch a real process"),
        )
        no_processes.start()
        self.addCleanup(no_processes.stop)
        self._create_app()
        self.app.governor_var.set(str(self.governor))

    def _discover(self):
        self.discovery_calls += 1
        return "NAME  ID  SIZE  MODIFIED\n" + "".join(
            f"{tag}  {index:012x}  1 GB  2 days ago\n"
            for index, tag in enumerate(self.tags, start=1)
        )

    def _create_app(self):
        # Closed fixtures must release their Tcl interpreter on its owner thread,
        # before a later discovery worker can trigger cyclic collection.
        self.app = None
        self.root = None
        gc.collect()
        self.root = tk.Tk()
        self.root.withdraw()
        self.runner = FakeRunner()
        self.app = self.app_type(
            self.root, self.repo,
            state_path=self.state_path,
            runner=self.runner,
            discover_models=self._discover,
        )
        self.root.update_idletasks()

    def tearDown(self):
        try:
            for callback in self.root.tk.call("after", "info"):
                self.root.after_cancel(callback)
            self.root.destroy()
        except tk.TclError:
            pass
        self.app = None
        self.root = None
        gc.collect()

    def test_discovery_does_not_retain_closed_app_on_worker_thread(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()

        def discover():
            entered.set()
            release.wait(5)
            finished.set()
            return "NAME ID SIZE MODIFIED\n"

        self.app.discover_models = discover
        ref = weakref.ref(self.app)
        self.app.refresh_models()
        self.assertTrue(entered.wait(5))
        try:
            self.app.request_close()
            self.app = None
            gc.collect()
            self.assertIsNone(ref(), "Discovery must not own a closed Tk app")
        finally:
            release.set()
            self.assertTrue(finished.wait(5))

    def _wait_until(self, predicate, description):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.005)
        self.fail(f"Timed out waiting for {description}")

    def _pump_for(self, seconds=0.2):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.005)

    def _queue_models(self, count=2):
        self.app.refresh_models()
        self._wait_until(lambda: self.app.models.size() == len(self.tags), "model discovery")
        self.app.models.selection_set(0, count - 1)
        self.app.add_selected_models()
        self.assertEqual([item.model for item in self.app.queue.items], self.tags[:count])

    def _start_first(self, count=2):
        self._queue_models(count)
        self.app.start_queue()
        self._wait_until(lambda: len(self.runner.started) == 1, "first queued model")
        self.assertEqual(self.app.queue.items[0].status, "Running")

    def test_constructor_is_idle_and_refresh_populates_real_listbox(self):
        self.assertIsInstance(self.app.models, tk.Listbox)
        self.assertIsInstance(self.app.terminal, tk.Text)
        self.assertEqual(self.discovery_calls, 0)
        self.assertEqual(self.runner.started, [])
        self._queue_models(3)
        self.assertEqual(self.discovery_calls, 1)
        self.assertEqual(list(self.app.models.get(0, "end")), self.tags)
        self.assertEqual(self.runner.started, [])

    def test_sequential_runs_stream_output_and_capture_exit_codes_and_run_dir(self):
        self._start_first(3)
        self.assertEqual([item.status for item in self.app.queue.items], ["Running", "Waiting", "Waiting"])
        run_dir = r"C:\Bench runs\alpha"
        self.runner.output("planner progress before process exit\n")
        self.runner.output(f"RUN_DIR={run_dir}\n")
        self._wait_until(
            lambda: run_dir in self.app.terminal.get("1.0", "end"),
            "live process output before completion",
        )
        self.assertTrue(self.runner.active)
        self.assertEqual(len(self.runner.started), 1)
        self.assertIn("planner progress before process exit", self.app.terminal.get("1.0", "end"))
        self.assertEqual(str(self.app.queue.items[0].run_dir), run_dir)
        self.runner.finish(0)
        self._wait_until(lambda: len(self.runner.started) == 2, "second queued model")
        self.assertEqual(self.app.queue.items[0].status, "Complete")
        self.assertEqual(self.app.queue.items[0].exit_code, 0)
        self.runner.finish(7)
        self._wait_until(lambda: len(self.runner.started) == 3, "third queued model after failure")
        self.assertEqual(self.app.queue.items[1].status, "Failed")
        self.assertEqual(self.app.queue.items[1].exit_code, 7)
        self.runner.finish(0)
        self._wait_until(lambda: not self.runner.active, "queue completion")
        self.assertEqual([item.status for item in self.app.queue.items], ["Complete", "Failed", "Complete"])
        self.assertEqual(len(self.runner.started), 3)
        for tag, (_, argv, cwd) in zip(self.tags, self.runner.started):
            self.assertEqual(argv[argv.index("-Model") + 1], tag)
            self.assertEqual(argv[argv.index("-Runtime") + 1], "ollama")
            self.assertEqual(cwd, self.repo.resolve())

    def test_pause_finishes_current_and_continue_starts_next(self):
        self._start_first()
        self.app.pause_after_current()
        self.assertTrue(self.runner.active)
        self.assertEqual(self.app.queue.items[0].status, "Running")
        self.assertEqual(self.runner.emergency_calls, 0)
        self.runner.finish(0)
        self._wait_until(lambda: self.app.queue.status == "Paused", "pause after current model")
        self._pump_for()
        self.assertEqual(len(self.runner.started), 1)
        self.assertEqual(self.app.queue.items[1].status, "Waiting")
        self.app.continue_queue()
        self._wait_until(lambda: len(self.runner.started) == 2, "continue from next waiting model")
        self.assertEqual(self.app.queue.items[1].status, "Running")
        self.runner.finish(0)
        self._wait_until(lambda: not self.runner.active, "continued queue completion")

    def test_stop_finishes_current_and_keeps_remaining_models_unrun(self):
        self._start_first()
        self.app.stop_after_current()
        self.assertTrue(self.runner.active)
        self.assertEqual(self.app.queue.items[0].status, "Running")
        self.assertEqual(self.runner.emergency_calls, 0)
        self.runner.finish(0)
        self._wait_until(lambda: not self.runner.active, "stop after current model")
        self._pump_for()
        self.assertEqual(self.app.queue.status, "Stopped")
        self.assertEqual([item.status for item in self.app.queue.items], ["Complete", "Waiting"])
        self.assertEqual(len(self.runner.started), 1)

    def test_pause_before_scheduled_launch_starts_no_process(self):
        self._queue_models()
        self.app.start_queue()
        self.app.pause_after_current()
        self._pump_for()
        self.assertEqual(self.app.queue.status, "Paused")
        self.assertEqual(self.runner.started, [])
        self.assertEqual([item.status for item in self.app.queue.items], ["Waiting", "Waiting"])
        self.app.continue_queue()
        self._wait_until(lambda: len(self.runner.started) == 1, "first model after early pause")
        self.app.stop_after_current()
        self.runner.finish(0)
        self._wait_until(lambda: not self.runner.active, "early-pause test cleanup")

    def test_reopen_preserves_completed_and_waiting_evidence_without_auto_run(self):
        self._start_first()
        self.runner.output("RUN_DIR=C:\\benchmark\\first-run\n")
        self.app.pause_after_current()
        self.runner.finish(0)
        self._wait_until(lambda: self.app.queue.status == "Paused", "persisted paused queue")
        self.app.request_close()
        self.assertTrue(self.state_path.is_file())
        self._create_app()
        self._pump_for()
        self.assertEqual([item.model for item in self.app.queue.items], self.tags[:2])
        self.assertEqual([item.status for item in self.app.queue.items], ["Complete", "Waiting"])
        self.assertEqual(self.app.queue.items[0].exit_code, 0)
        self.assertEqual(str(self.app.queue.items[0].run_dir), r"C:\benchmark\first-run")
        self.assertEqual(self.app.queue.status, "Paused")
        self.assertEqual(self.runner.started, [])
        self.app.continue_queue()
        self._wait_until(lambda: len(self.runner.started) == 1, "restored next waiting model")
        self.assertEqual(self.runner.started[0][1][self.runner.started[0][1].index("-Model") + 1], self.tags[1])
        self.runner.finish(0)
        self._wait_until(lambda: not self.runner.active, "restored queue completion")

    def test_prelaunch_save_failure_pauses_without_spawning_and_can_retry(self):
        self._queue_models()
        self.app.start_queue()
        with patch("localbench.queue_gui.app.save_state", side_effect=OSError("fixture disk failure")):
            self._wait_until(lambda: self.app.queue.status == "Paused", "failed prelaunch state save")
        self.assertEqual(self.runner.started, [])
        self.assertEqual([item.status for item in self.app.queue.items], ["Waiting", "Waiting"])
        self.assertIsNone(self.app.queue.pending_action)
        self.assertIsNone(self.app.queue.items[0].started_at)
        self.assertIn("Could not save queue state", self.app.error_var.get())
        self.app.continue_queue()
        self._wait_until(lambda: len(self.runner.started) == 1, "retry after state saving recovers")
        self.assertEqual(self.app.error_var.get(), "")
        self.app.stop_after_current()
        self.runner.finish(0)
        self._wait_until(lambda: not self.runner.active, "recovered save test completion")

    def test_recovered_live_process_blocks_continue_and_new_queue(self):
        from localbench.queue_gui.core import BenchmarkSettings, QueueState, save_state

        self.app.request_close()
        saved = QueueState(settings=BenchmarkSettings(governor_root=str(self.governor)))
        saved.add_models(self.tags[:2])
        saved.start()
        saved.start_next().pid = 32123
        save_state(self.state_path, saved)
        self._create_app()
        self.assertEqual([item.status for item in self.app.queue.items], ["Interrupted", "Waiting"])
        with patch("localbench.queue_gui.app.process_is_running", return_value=True), \
                patch("localbench.queue_gui.app.messagebox.showwarning") as warning, \
                patch("localbench.queue_gui.app.messagebox.askyesno", return_value=True):
            self.app.continue_queue()
            self.app.new_queue()
            self._pump_for()
        self.assertTrue(warning.called)
        self.assertEqual(self.runner.started, [])
        self.assertEqual([item.status for item in self.app.queue.items], ["Interrupted", "Waiting"])
        self.assertEqual(self.app.queue.status, "Paused")
        self.assertEqual(self.runner.emergency_calls, 0)

    def test_close_during_run_finishes_current_and_leaves_remaining_unrun(self):
        self._start_first()
        with patch("localbench.queue_gui.app.messagebox.askyesno", return_value=True):
            self.app.request_close()
        self.assertFalse(self.app._closed)
        self.assertTrue(self.runner.active)
        self.assertEqual(self.app.queue.items[0].status, "Running")
        self.assertEqual(self.runner.emergency_calls, 0)
        self.runner.finish(0)
        self._wait_until(lambda: self.app._closed, "close after current model finishes")
        self.assertEqual(len(self.runner.started), 1)
        self.assertEqual([item.status for item in self.app.queue.items], ["Complete", "Waiting"])
        from localbench.queue_gui.core import load_state
        restored = load_state(self.state_path)
        self.assertEqual([item.status for item in restored.items], ["Complete", "Waiting"])
        self.assertEqual(restored.status, "Stopped")

    def test_unstarted_settings_edits_survive_close_and_reopen(self):
        self._queue_models()
        self.app.phase_var.set("qualification")
        self.app.advanced_vars["context_tokens"].set("16384")
        self.app.advanced_vars["timeout_seconds"].set("123.5")
        self.app.request_close()
        self._create_app()
        self.assertEqual(self.app.phase_var.get(), "qualification")
        self.assertEqual(self.app.advanced_vars["context_tokens"].get(), "16384")
        self.assertEqual(float(self.app.advanced_vars["timeout_seconds"].get()), 123.5)
        self.assertEqual(self.runner.started, [])

    def test_declining_close_after_save_failure_keeps_event_polling_alive(self):
        self._start_first()
        with patch("localbench.queue_gui.app.messagebox.askyesno", return_value=True):
            self.app.request_close()
        self.runner.finish(0)
        with patch("localbench.queue_gui.app.save_state", side_effect=OSError("fixture disk failure")), \
                patch("localbench.queue_gui.app.messagebox.askyesno", return_value=False):
            self._wait_until(lambda: not self.runner.active, "completion with unsuccessful close save")
        self.assertFalse(self.app._closed)
        self.assertEqual(self.app.queue.status, "Paused")
        self.app.continue_queue()
        self._wait_until(lambda: len(self.runner.started) == 2, "continue after declining close")
        self.runner.output("event polling survived canceled close\n")
        self._wait_until(
            lambda: "event polling survived canceled close" in self.app.terminal.get("1.0", "end"),
            "live output after canceled close",
        )
        self.runner.finish(0)
        self._wait_until(lambda: not self.runner.active, "final model after canceled close")

    def test_waiting_rows_can_be_reordered_before_start(self):
        self._queue_models(3)
        self.app.queue_tree.selection_set(self.app.queue.items[2].id)
        self.app.move_selected(-1)
        self.app.move_selected(-1)
        self.assertEqual([item.model for item in self.app.queue.items], [self.tags[2], self.tags[0], self.tags[1]])
        self.app.start_queue()
        self._wait_until(lambda: len(self.runner.started) == 1, "reordered first model")
        command = self.runner.started[0][1]
        self.assertEqual(command[command.index("-Model") + 1], self.tags[2])
        self.app.stop_after_current()
        self.runner.finish(0)
        self._wait_until(lambda: not self.runner.active, "reordering test completion")


    def _install_project_fixtures(self):
        for project in ("assistant-001", "assistant-002"):
            packet = self.repo / "project-benchmarks" / project / "v1" / "packet.json"
            packet.parent.mkdir(parents=True, exist_ok=True)
            packet.write_text(__import__("json").dumps({
                "packet_id": project + "-v1",
                "tasks": [{"id": "T01", "title": "Normalize"},
                          {"id": "T02", "title": "Persist"}],
            }), encoding="utf-8")
            (self.repo / "tools/campaigns" / ("run-" + project + ".ps1")).write_text(
                "# Fake project runner; FakeRunner prevents execution.\\n", encoding="utf-8")

    def test_project_selector_reflects_packet_tasks_and_requires_consent(self):
        self._install_project_fixtures()
        self.app.refresh_models()
        self._wait_until(lambda: self.app.models.size() == len(self.tags), "model list")
        self.app.models.selection_set(0)
        self.app.benchmark_var.set("assistant-001")
        self.app._on_benchmark_change()
        self.assertEqual(self.app.through_widget.cget("values"), ("T01", "T02"))
        self.assertEqual(self.app.through_var.get(), "T01")
        with patch("localbench.queue_gui.app.messagebox.showerror") as show:
            self.app.add_selected_models()
        self.assertTrue(show.called)
        self.assertEqual(len(self.app.queue.items), 0)
        self.app.host_ack_var.set(True)
        self.app.through_var.set("T02")
        with patch("localbench.queue_gui.app.messagebox.askyesno", return_value=False):
            self.app.add_selected_models()
        self.assertEqual(self.app.queue.items, [])
        with patch("localbench.queue_gui.app.messagebox.askyesno", return_value=True):
            self.app.add_selected_models()
        self.assertEqual(len(self.app.queue.items), 1)
        item = self.app.queue.items[0]
        self.assertEqual((item.settings.benchmark, item.settings.through,
                          item.settings.allow_host_execution),
                         ("assistant-001", "T02", True))
        self.assertEqual(self.app.queue_tree.set(item.id, "benchmark"), "assistant-001")
        self.assertEqual(self.app.queue_tree.set(item.id, "through"), "T02")

    def test_mixed_benchmarks_launch_the_correct_item_snapshot(self):
        self._install_project_fixtures()
        self.app.refresh_models()
        self._wait_until(lambda: self.app.models.size() == len(self.tags), "model list")
        self.app.models.selection_set(0)
        self.app.add_selected_models()
        self.app.models.selection_clear(0, "end")
        self.app.models.selection_set(0)
        self.app.benchmark_var.set("assistant-002")
        self.app._on_benchmark_change()
        self.app.phase_var.set("qualification")
        self.app.through_var.set("T02")
        self.app.host_ack_var.set(True)
        with patch("localbench.queue_gui.app.messagebox.askyesno", return_value=True):
            self.app.add_selected_models()
        self.assertEqual(len(self.app.queue.items), 2)
        self.assertEqual(self.app.queue.items[0].settings.benchmark, "roles")
        self.assertEqual(self.app.queue.items[1].settings.benchmark, "assistant-002")
        self.app.start_queue()
        self._wait_until(lambda: len(self.runner.started) == 1, "role item")
        first_cmd = self.runner.started[0][1]
        self.assertNotIn("-QueueBenchmark", first_cmd)
        self.runner.finish(0)
        self._wait_until(lambda: len(self.runner.started) == 2, "assistant item")
        second_cmd = self.runner.started[1][1]
        self.assertEqual(second_cmd[second_cmd.index("-QueueBenchmark") + 1], "assistant-002")
        self.assertEqual(second_cmd[second_cmd.index("-Through") + 1], "T02")
        self.assertEqual(second_cmd[second_cmd.index("-Phase") + 1], "qualification")
        self.assertIn("-AllowHostExecution", second_cmd)
        self.app.stop_after_current()
        self.runner.finish(0)
        self._wait_until(lambda: not self.runner.active, "project completion")
        from localbench.queue_gui.core import load_state
        restored = load_state(self.state_path)
        self.assertEqual([i.settings.benchmark for i in restored.items], ["roles", "assistant-002"])

    def test_recovered_project_queue_keeps_consent_and_through_selection(self):
        self._install_project_fixtures()
        self.app.refresh_models()
        self._wait_until(lambda: self.app.models.size() == len(self.tags), "model list")
        self.app.models.selection_set(0)
        self.app.benchmark_var.set("assistant-001")
        self.app._on_benchmark_change()
        self.app.host_ack_var.set(True)
        self.app.through_var.set("T02")
        with patch("localbench.queue_gui.app.messagebox.askyesno", return_value=True):
            self.app.add_selected_models()
        self.app.request_close()
        self._create_app()
        self.assertEqual(self.app.benchmark_var.get(), "assistant-001")
        self.assertEqual(self.app.through_var.get(), "T02")
        self.assertEqual(len(self.app.queue.items), 1)
        self.assertEqual(self.app.queue.items[0].settings.benchmark, "assistant-001")
        self.assertEqual(self.runner.started, [])


if __name__ == "__main__":
    unittest.main()
