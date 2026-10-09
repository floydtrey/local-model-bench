"""Sequential Tk front end for supported campaign launchers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import queue as event_queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .core import (
    BENCHMARKS, BenchmarkSettings, QueueState, benchmark_tasks, build_command, load_state, parse_ollama_list,
    parse_run_dir, save_state,
)
from .process import (
    InstanceAlreadyRunning, InstanceLock, ProcessRunner, list_ollama,
    process_is_running,
)


ADVANCED_FIELDS = (
    ("context_tokens", "Context tokens", "32768"),
    ("max_output_tokens", "Max output tokens", "8192"),
    ("timeout_seconds", "Timeout seconds", "600"),
    ("keep_alive_seconds", "Keep-alive seconds", "3600"),
)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class BenchmarkQueueApp:
    """The Tk thread owns every queue transition, including the next launch."""

    def __init__(self, root, repo_root: Path, state_path=None, runner=None,
                 discover_models=None):
        self.root = root
        self.repo_root = Path(repo_root).resolve()
        self.state_path = Path(state_path or self.repo_root / "local-state" / "queue-gui" / "queue.json")
        self.runner = runner if runner is not None else ProcessRunner()
        self.discover_models = discover_models or list_ollama
        self.discovery_events = event_queue.Queue()
        self._refresh_busy = False
        self._closed = False
        self._close_after_current = False
        self._line_buffer = ""
        self._terminal_chars = 0
        self._poll_id = None
        self._next_id = None
        self._tick_id = None
        self._load_error = None
        self._save_error = None
        try:
            self.queue = load_state(self.state_path)
        except (OSError, ValueError) as exc:
            self.queue = QueueState()
            self._load_error = str(exc)
        self._recovery_review = any(item.status == "Interrupted" for item in self.queue.items)
        self._build_widgets()
        self._render()
        if self._load_error:
            self.error_var.set("Saved queue could not be read. New Queue preserves the invalid file before resetting. " + self._load_error)
        elif self._recovery_review:
            self._append_terminal("Recovered an interrupted session. No benchmark was started.\n"
                                  "Interrupted entries will not be retried automatically.\n")
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)
        self._poll_id = self.root.after(50, self._poll)
        self._tick_id = self.root.after(1000, self._tick)

    def _build_widgets(self):
        root = self.root
        root.title("Model Benchmark Queue")
        root.geometry("1210x900")
        root.minsize(990, 720)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        outer = ttk.Frame(root, padding=12)
        outer.grid(sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)
        ttk.Label(outer, text="Model Benchmark Queue", font=("Segoe UI", 16, "bold")).grid(sticky="w")
        self.status_var = tk.StringVar()
        ttk.Label(outer, textvariable=self.status_var, wraplength=1040).grid(row=1, sticky="ew", pady=(4, 8))

        setup = ttk.Frame(outer)
        setup.grid(row=2, sticky="ew")
        setup.columnconfigure(0, weight=1)
        setup.columnconfigure(1, weight=1)
        model_frame = ttk.LabelFrame(setup, text="Installed Ollama models · click rows to select", padding=8)
        model_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        model_frame.columnconfigure(0, weight=1)
        self.refresh_button = ttk.Button(model_frame, text="Refresh Ollama Models", command=self.refresh_models)
        self.refresh_button.grid(row=0, sticky="w", pady=(0, 4))
        self.models = tk.Listbox(model_frame, selectmode=tk.MULTIPLE, exportselection=False, height=7)
        self.models.grid(row=1, sticky="nsew")
        model_scroll = ttk.Scrollbar(model_frame, orient="vertical", command=self.models.yview)
        model_scroll.grid(row=1, column=1, sticky="ns")
        self.models.configure(yscrollcommand=model_scroll.set)
        model_buttons = ttk.Frame(model_frame)
        model_buttons.grid(row=2, sticky="w", pady=(6, 0))
        ttk.Button(model_buttons, text="Select all", command=lambda: self.models.selection_set(0, tk.END)).pack(side="left")
        ttk.Button(model_buttons, text="Clear selection", command=lambda: self.models.selection_clear(0, tk.END)).pack(side="left", padx=4)
        self.add_button = ttk.Button(model_buttons, text="Add selected to queue", command=self.add_selected_models)
        self.add_button.pack(side="left")
        self.model_message = tk.StringVar(value="Local Ollama endpoint: 127.0.0.1:11434")
        ttk.Label(model_frame, textvariable=self.model_message, wraplength=470).grid(row=3, sticky="w", pady=(4, 0))

        settings = ttk.LabelFrame(setup, text="Benchmark settings · runtime: ollama", padding=8)
        settings.grid(row=0, column=1, sticky="nsew")
        settings.columnconfigure(1, weight=1)

        self.benchmark_var = tk.StringVar(value=self.queue.settings.benchmark)
        self.through_var = tk.StringVar(value=self.queue.settings.through or "")
        self.phase_var = tk.StringVar(value=self.queue.settings.phase)
        self.governor_var = tk.StringVar(value=self.queue.settings.governor_root)
        self.host_ack_var = tk.BooleanVar(value=self.queue.settings.allow_host_execution)
        ttk.Label(settings, text="Benchmark").grid(row=0, column=0, sticky="w")
        self.benchmark_widget = ttk.Combobox(
            settings, values=tuple(BENCHMARKS), textvariable=self.benchmark_var,
            state="readonly", width=20,
        )
        self.benchmark_widget.grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)
        self.benchmark_widget.bind("<<ComboboxSelected>>", self._on_benchmark_change)
        ttk.Label(settings, text="Through task").grid(row=1, column=0, sticky="w")
        self.through_widget = ttk.Combobox(settings, textvariable=self.through_var, state="readonly", width=20)
        self.through_widget.grid(row=1, column=1, columnspan=2, sticky="ew", pady=2)
        self.task_description = tk.StringVar()
        ttk.Label(settings, textvariable=self.task_description, wraplength=440).grid(row=2, columnspan=3, sticky="w", pady=(0, 3))
        ttk.Label(settings, text="Phase").grid(row=3, column=0, sticky="w")
        self.phase_widget = ttk.Combobox(settings, values=("screen", "qualification"), textvariable=self.phase_var, state="readonly", width=20)
        self.phase_widget.grid(row=3, column=1, sticky="ew", pady=2)
        ttk.Label(settings, text="Governor root (roles)").grid(row=4, column=0, sticky="w", padx=(0, 8))
        self.governor_widget = ttk.Entry(settings, textvariable=self.governor_var)
        self.governor_widget.grid(row=4, column=1, columnspan=2, sticky="ew", pady=2)
        self.settings_widgets = [self.governor_widget]
        self.advanced_vars = {}
        for row, (key, label, default) in enumerate(ADVANCED_FIELDS, start=5):
            value = getattr(self.queue.settings, key)
            variable = tk.StringVar(value="" if value is None else str(value))
            self.advanced_vars[key] = variable
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky="w")
            entry = ttk.Entry(settings, textvariable=variable, width=13)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            self.settings_widgets.append(entry)
            ttk.Label(settings, text="CLI: " + default).grid(row=row, column=2, sticky="w", padx=6)
        self.host_ack_widget = ttk.Checkbutton(
            settings, text="I authorize executing model-generated Python on this host (NOT sandboxed)",
            variable=self.host_ack_var,
        )
        self.host_ack_widget.grid(row=9, columnspan=3, sticky="w", pady=(7, 0))
        ttk.Label(
            settings, text="Each queued model retains its own benchmark, phase, task and overrides. "
                           "Blank advanced fields use the chosen CLI's defaults.",
            wraplength=460,
        ).grid(row=10, columnspan=3, sticky="w", pady=(6, 0))
        self._sync_project_tasks()

        controls = ttk.Frame(outer)
        controls.grid(row=3, sticky="ew", pady=10)
        self.buttons = {}
        for key, text, command in (
            ("start", "Start Queue", self.start_queue),
            ("pause", "Pause After Current", self.pause_after_current),
            ("continue", "Continue", self.continue_queue),
            ("stop", "Stop After Current", self.stop_after_current),
            ("emergency", "Emergency Stop…", self.emergency_stop),
        ):
            self.buttons[key] = ttk.Button(controls, text=text, command=command)
            self.buttons[key].pack(side="left", padx=(0, 6))

        panes = ttk.Panedwindow(outer, orient="vertical")
        panes.grid(row=4, sticky="nsew")
        queue_frame = ttk.LabelFrame(panes, text="Queue · Complete means CLI exit 0; review model results separately", padding=6)
        queue_frame.columnconfigure(0, weight=1)
        queue_frame.rowconfigure(0, weight=1)
        columns = ("model", "benchmark", "phase", "through", "status", "exit", "elapsed", "run_dir")
        self.queue_tree = ttk.Treeview(queue_frame, columns=columns, show="headings", selectmode="browse", height=7)
        for key, label, width in (
            ("model", "Model", 160), ("benchmark", "Benchmark", 130),
            ("phase", "Phase", 90), ("through", "Through", 65),
            ("status", "State", 90), ("exit", "Exit", 52),
            ("elapsed", "Elapsed", 73), ("run_dir", "RUN_DIR", 350),
        ):
            self.queue_tree.heading(key, text=label)
            self.queue_tree.column(key, width=width, minwidth=60, stretch=key in ("model", "run_dir"))
        self.queue_tree.grid(row=0, sticky="nsew")
        qscroll = ttk.Scrollbar(queue_frame, orient="vertical", command=self.queue_tree.yview)
        qscroll.grid(row=0, column=1, sticky="ns")
        self.queue_tree.configure(yscrollcommand=qscroll.set)
        queue_buttons = ttk.Frame(queue_frame)
        queue_buttons.grid(row=1, sticky="w", pady=(5, 0))
        self.edit_buttons = []
        for label, command in (("Move up", lambda: self.move_selected(-1)), ("Move down", lambda: self.move_selected(1)), ("Remove waiting", self.remove_selected), ("New Queue", self.new_queue)):
            button = ttk.Button(queue_buttons, text=label, command=command)
            button.pack(side="left", padx=(0, 5))
            self.edit_buttons.append(button)
        ttk.Button(queue_buttons, text="Open run folder", command=self.open_run_folder).pack(side="left", padx=(10, 5))
        ttk.Button(queue_buttons, text="Open review workbook", command=self.open_review_workbook).pack(side="left")
        panes.add(queue_frame, weight=1)

        terminal_frame = ttk.LabelFrame(panes, text="Live terminal · stdout + stderr · recent 300,000 characters", padding=6)
        terminal_frame.columnconfigure(0, weight=1)
        terminal_frame.rowconfigure(0, weight=1)
        self.terminal = tk.Text(terminal_frame, height=13, wrap="word", state="disabled", background="#151b23", foreground="#e3e9f1", insertbackground="white", font=("Consolas", 10))
        self.terminal.grid(sticky="nsew")
        tscroll = ttk.Scrollbar(terminal_frame, orient="vertical", command=self.terminal.yview)
        tscroll.grid(row=0, column=1, sticky="ns")
        self.terminal.configure(yscrollcommand=tscroll.set)
        panes.add(terminal_frame, weight=2)
        self.error_var = tk.StringVar()
        ttk.Label(outer, textvariable=self.error_var, foreground="#a32626", wraplength=1040).grid(row=5, sticky="ew", pady=(5, 0))

    def _settings_locked(self):
        # Frozen per queued item, not globally after the first run.
        return False

    def _on_benchmark_change(self, _event=None):
        self._sync_project_tasks()
        self.host_ack_var.set(False)
        self._render()

    def _sync_project_tasks(self):
        benchmark = self.benchmark_var.get()
        if benchmark == "roles":
            self.through_var.set("")
            self.through_widget.configure(values=(), state="disabled")
            self.task_description.set("Existing five-role Planner / Governor / Worker / Tester / Reviewer battery")
            return
        try:
            tasks = benchmark_tasks(self.repo_root, benchmark)
        except ValueError as exc:
            self.through_widget.configure(values=(), state="disabled")
            self.task_description.set(str(exc))
            return
        ids = [task for task, _ in tasks]
        if self.through_var.get() not in ids:
            self.through_var.set(ids[0])
        self.through_widget.configure(values=ids, state="readonly")
        self.task_description.set(" / ".join(f"{task}: {title}" for task, title in tasks))

    def _read_settings(self):
        return BenchmarkSettings.from_fields(
            phase=self.phase_var.get(), governor_root=self.governor_var.get(),
            benchmark=self.benchmark_var.get(),
            through=self.through_var.get() if self.benchmark_var.get() != "roles" else None,
            allow_host_execution=self.host_ack_var.get() if self.benchmark_var.get() != "roles" else False,
            **{key: variable.get() for key, variable in self.advanced_vars.items()},
        )

    def _save(self):
        if self._load_error:
            return False
        try:
            save_state(self.state_path, self.queue)
        except (OSError, ValueError) as exc:
            self._save_error = str(exc)
            self.queue.request_pause()
            self.error_var.set("Could not save queue state; further launches are paused. " + str(exc))
            return False
        if self._save_error:
            self.error_var.set("")
        self._save_error = None
        return True

    def refresh_models(self):
        if self._refresh_busy or self._closed:
            return
        self._refresh_busy = True
        self.refresh_button.configure(state="disabled")
        self.model_message.set("Reading ollama list…")

        def discover():
            try:
                self.discovery_events.put((True, self.discover_models()))
            except Exception as exc:
                self.discovery_events.put((False, str(exc)))
        threading.Thread(target=discover, daemon=True, name="ollama-model-list").start()

    def add_selected_models(self):
        if self.runner.active or self.queue.status == "Running" or self._load_error:
            return
        selected = [self.models.get(index) for index in self.models.curselection()]
        if not selected:
            return
        try:
            chosen = self._read_settings()
            if chosen.benchmark != "roles":
                if not chosen.allow_host_execution:
                    raise ValueError("Project benchmarks execute model-generated Python. Check the explicit host-execution acknowledgement before adding.")
                if not messagebox.askyesno(
                    "Execute model-generated Python?",
                    f"Add {len(selected)} model(s) for {chosen.benchmark} through {chosen.through} "
                    f"({chosen.phase})?\\n\\nBounded file tools are NOT an OS/network sandbox. "
                    "The generated Python runs on this computer. Prefer a disposable VM. "
                    "Confirm authorization for these queued tasks.",
                    parent=self.root,
                ):
                    return
            # Validate the chosen packet and its task before queuing any item.
            build_command(self.repo_root, selected[0], chosen)
            self.queue.settings = chosen
            self.queue.add_models(selected, settings=chosen)
        except ValueError as exc:
            messagebox.showerror("Queue settings", str(exc), parent=self.root)
            return
        self._save()
        self._render()

    def _check_recovery(self):
        if not self._recovery_review:
            return True
        unknown = False
        for item in self.queue.items:
            if item.status != "Interrupted":
                continue
            if item.pid is None:
                unknown = True
                continue
            alive = process_is_running(item.pid)
            if alive is not False:
                messagebox.showwarning("Previous run needs attention", f"The previous runner (PID {item.pid}) may still be active.\nWait for it to finish and verify it has stopped before continuing.\nThe GUI will not terminate a recovered process.", parent=self.root)
                return False
        if unknown and not messagebox.askyesno("Interrupted launch", "The previous GUI closed before it saved a process ID.\nHave you verified that its benchmark runner is no longer running?\nContinue will start only Waiting models.", parent=self.root):
            return False
        self._recovery_review = False
        return True

    def start_queue(self):
        if self.runner.active or self.queue.status == "Running" or self._load_error:
            return
        if not self.queue.items:
            self.add_selected_models()
        if not self.queue.waiting or not self._check_recovery():
            return
        try:
            for item in self.queue.waiting:
                script = BENCHMARKS[item.settings.benchmark][1]
                if not (self.repo_root / "tools" / "campaigns" / script).is_file():
                    raise ValueError(f"Cannot find tools/campaigns/{script} in this checkout.")
                build_command(self.repo_root, item.model, item.settings)
            if not (self.repo_root / "tools" / "gui" / "run-queue-item.ps1").is_file():
                raise ValueError("Cannot find tools/gui/run-queue-item.ps1 in this checkout.")
            self.queue.start()
        except ValueError as exc:
            messagebox.showerror("Cannot start queue", str(exc), parent=self.root)
            return
        if self._save():
            self._schedule_next()
        self._render()

    def continue_queue(self):
        if self.queue.status in ("Paused", "Stopped"):
            self.start_queue()

    def pause_after_current(self):
        self.queue.request_pause()
        self._save()
        self._render()

    def stop_after_current(self):
        self.queue.request_stop()
        self._save()
        self._render()

    def _schedule_next(self):
        if not self._closed and self._next_id is None and self.queue.status == "Running":
            self._next_id = self.root.after(50, self._start_next)

    def _start_next(self):
        self._next_id = None
        if self._closed or self.runner.active or self.queue.status != "Running":
            return
        item = self.queue.start_next()
        if item is None:
            self._save()
            self._render()
            return
        # Claim and persist before spawning. A crash never silently requeues a run.
        if not self._save():
            item.status, item.started_at = "Waiting", None
            self.queue.status = "Paused"
            self.queue.pending_action = None
            self._render()
            return
        self._line_buffer = ""
        try:
            command = build_command(self.repo_root, item.model, item.settings)
            self._append_terminal(f"\n[{datetime.now().astimezone().isoformat(timespec='seconds')}] Starting {item.model} · {item.settings.benchmark} · {item.settings.phase} · {item.settings.through or 'all roles'}\n")
            self._append_terminal(subprocess.list2cmdline(command) + "\n")
            item.pid = self.runner.start(item.id, command, self.repo_root)
        except (OSError, ValueError, RuntimeError) as exc:
            self.queue.request_stop()
            self.queue.finish(item.id, None, error=f"Could not launch CLI: {exc}")
            self._append_terminal(f"Could not launch CLI: {exc}\n")
        self._save()
        self._render()

    def _capture_output(self, item, text):
        self._append_terminal(text)
        self._line_buffer += text
        lines = re.split(r"\r\n|\n|\r", self._line_buffer)
        self._line_buffer = lines.pop()[-65536:]
        for line in lines:
            self._capture_run_dir(item, line)

    def _capture_run_dir(self, item, line):
        path = parse_run_dir(line)
        if path is not None and path != item.run_dir:
            item.run_dir = path
            self._save()

    def _poll(self):
        self._poll_id = None
        if self._closed:
            return
        try:
            success, value = self.discovery_events.get_nowait()
        except event_queue.Empty:
            pass
        else:
            self._refresh_busy = False
            self.refresh_button.configure(state="normal")
            if success:
                try:
                    models = parse_ollama_list(value)
                except ValueError as exc:
                    self.model_message.set("Refresh failed: " + str(exc))
                else:
                    selected = {self.models.get(index) for index in self.models.curselection()}
                    self.models.delete(0, tk.END)
                    for index, model in enumerate(models):
                        self.models.insert(tk.END, model)
                        if model in selected:
                            self.models.selection_set(index)
                    self.model_message.set(f"{len(models)} installed model(s) · local Ollama at 127.0.0.1:11434")
            else:
                self.model_message.set("Refresh failed; existing selection kept. " + value)
                self._append_terminal("Ollama refresh failed: " + value + "\n")

        changed = False
        for _ in range(80):
            try:
                event = self.runner.events.get_nowait()
            except event_queue.Empty:
                break
            item = self.queue.active
            if item is None or event.item_id != item.id:
                continue
            if event.kind == "output":
                self._capture_output(item, event.text)
            elif event.kind == "finished":
                self._capture_run_dir(item, self._line_buffer)
                self._line_buffer = ""
                self.queue.finish(item.id, event.exit_code, error=event.error)
                self.runner.acknowledge(item.id)
                self._append_terminal(f"\n{item.model}: {item.status}; exit code {item.exit_code}\n")
                if event.error:
                    self._append_terminal(event.error + "\n")
                saved = self._save()
                changed = True
                if self._close_after_current:
                    self._finish_close()
                    if self._closed:
                        return
                if saved:
                    self._schedule_next()
        if changed:
            self._render()
        self._poll_id = self.root.after(50, self._poll)

    def _append_terminal(self, text):
        text = ANSI.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
        follow = self.terminal.yview()[1] >= 0.99
        self.terminal.configure(state="normal")
        self.terminal.insert(tk.END, text)
        self._terminal_chars += len(text)
        if self._terminal_chars > 300000:
            excess = self._terminal_chars - 240000
            self.terminal.delete("1.0", f"1.0+{excess}c")
            self._terminal_chars -= excess
        self.terminal.configure(state="disabled")
        if follow:
            self.terminal.see(tk.END)

    @staticmethod
    def _elapsed(item):
        if item.started_at is None:
            return ""
        start = datetime.fromisoformat(item.started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(item.finished_at.replace("Z", "+00:00")) if item.finished_at else datetime.now(timezone.utc)
        seconds = max(0, int((end - start).total_seconds()))
        return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"

    def _render(self):
        active = self.queue.active
        pending = f" · {self.queue.pending_action.title()} after current" if self.queue.pending_action else ""
        finished = sum(item.status in ("Complete", "Failed", "Interrupted") for item in self.queue.items)
        current = active.model if active else "—"
        self.status_var.set(f"Queue: {self.queue.status}{pending}   |   Current: {current}   |   Finished: {finished}/{len(self.queue.items)}   |   Waiting: {len(self.queue.waiting)}")
        existing = set(self.queue_tree.get_children())
        for index, item in enumerate(self.queue.items):
            values = (
                item.model, item.settings.benchmark, item.settings.phase,
                item.settings.through or "all", item.status,
                "" if item.exit_code is None else item.exit_code,
                self._elapsed(item), item.run_dir or "",
            )
            if item.id in existing:
                self.queue_tree.item(item.id, values=values)
                existing.remove(item.id)
            else:
                self.queue_tree.insert("", "end", iid=item.id, values=values)
            self.queue_tree.move(item.id, "", index)
        for item_id in existing:
            self.queue_tree.delete(item_id)
        running = self.queue.status == "Running"
        busy = running or self.runner.active
        can_edit = not busy and not self._load_error and not self._close_after_current
        for button in self.edit_buttons:
            button.configure(state="disabled" if busy else "normal")
        self.add_button.configure(state="normal" if can_edit else "disabled")
        locked = busy or self._load_error or self._close_after_current
        self.phase_widget.configure(state="disabled" if locked else "readonly")
        self.benchmark_widget.configure(state="disabled" if locked else "readonly")
        self.through_widget.configure(state="disabled" if locked or self.benchmark_var.get() == "roles" else "readonly")
        self.host_ack_widget.configure(state="disabled" if locked or self.benchmark_var.get() == "roles" else "normal")
        for widget in self.settings_widgets:
            widget.configure(state="disabled" if locked else "normal")
        self.governor_widget.configure(state="normal" if not locked and self.benchmark_var.get() == "roles" else "disabled")
        enabled = {
            "start": can_edit and self.queue.status not in ("Paused", "Stopped") and (bool(self.queue.waiting) or not self.queue.items),
            "pause": running and self.queue.pending_action != "stop",
            "continue": can_edit and self.queue.status in ("Paused", "Stopped") and bool(self.queue.waiting),
            "stop": running or self.queue.status == "Paused",
            "emergency": self.runner.active,
        }
        for key, button in self.buttons.items():
            button.configure(state="normal" if enabled[key] else "disabled")

    def _tick(self):
        self._tick_id = None
        if not self._closed:
            self._render()
            self._tick_id = self.root.after(1000, self._tick)

    def _selected_item(self):
        selection = self.queue_tree.selection()
        return next((item for item in self.queue.items if selection and item.id == selection[0]), None)

    def move_selected(self, offset):
        if self.runner.active or self.queue.status == "Running":
            return
        item = self._selected_item()
        if item is None or item.status != "Waiting":
            return
        index = self.queue.items.index(item)
        target = index + offset
        if 0 <= target < len(self.queue.items) and self.queue.items[target].status == "Waiting":
            self.queue.items[index], self.queue.items[target] = self.queue.items[target], item
            self._save()
            self._render()

    def remove_selected(self):
        if self.runner.active or self.queue.status == "Running":
            return
        item = self._selected_item()
        if item is not None and item.status == "Waiting":
            self.queue.items.remove(item)
            self._save()
            self._render()

    def new_queue(self):
        if self.runner.active or self.queue.status == "Running":
            return
        if not self._check_recovery():
            return
        if self.queue.items and not messagebox.askyesno("New Queue", "Clear the queue list and start a new queue?\nBenchmark result files are kept.", parent=self.root):
            return
        if self._load_error and self.state_path.exists():
            backup = self.state_path.with_name(self.state_path.stem + ".invalid-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")
            try:
                self.state_path.rename(backup)
            except OSError as exc:
                messagebox.showerror("Could not preserve state", str(exc), parent=self.root)
                return
        self._load_error = None
        self._recovery_review = False
        self._close_after_current = False
        self.queue = QueueState(settings=self.queue.settings)
        self.error_var.set("")
        self._save()
        self._render()

    def emergency_stop(self):
        if not self.runner.active:
            return
        if not messagebox.askyesno("Emergency Stop", "Terminate the benchmark process tree launched by this GUI now?\nPartial benchmark evidence may result. The shared Ollama service will remain running.\nPause/Stop After Current lets the current model finish normally.", parent=self.root):
            return
        self.queue.request_stop()
        self._save()
        if self.runner.emergency_stop():
            self._append_terminal("Emergency Stop requested. Waiting for the owned process tree to exit.\n")
        self._render()

    def _open_path(self, workbook=False):
        item = self._selected_item()
        if item is None or not item.run_dir:
            messagebox.showinfo("No run directory", "Select a queue row with a captured RUN_DIR first.", parent=self.root)
            return
        path = Path(item.run_dir)
        if not path.is_absolute():
            path = self.repo_root / path
        if workbook:
            path = path / "review" / "review-package.xlsx"
        if not (path.is_file() if workbook else path.is_dir()):
            messagebox.showerror("Output unavailable", f"Cannot find {path}", parent=self.root)
            return
        try:
            if os.name == "nt":
                os.startfile(str(path))
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror("Could not open output", str(exc), parent=self.root)

    def open_run_folder(self):
        self._open_path()

    def open_review_workbook(self):
        self._open_path(workbook=True)

    def request_close(self):
        if self.runner.active:
            if self._close_after_current:
                return
            if messagebox.askyesno("Finish current model before closing", "A benchmark is running. Finish this model, save the queue, and then close?\nThe window will stay open until it finishes. Remaining models will stay Waiting.", parent=self.root):
                self._close_after_current = True
                self.stop_after_current()
            return
        if self.queue.status == "Running":
            self.queue.request_stop()
        self._finish_close()

    def _finish_close(self):
        if self._closed:
            return
        if not self._settings_locked() and not self._load_error:
            try:
                self.queue.settings = self._read_settings()
            except ValueError as exc:
                messagebox.showerror("Queue settings", str(exc), parent=self.root)
                return
        if not self._load_error and not self._save():
            if not messagebox.askyesno("Queue state not saved", "The latest queue state could not be saved. Close anyway?", parent=self.root):
                self._close_after_current = False
                return
        self._closed = True
        for callback in (self._poll_id, self._next_id, self._tick_id):
            if callback is not None:
                self.root.after_cancel(callback)
        self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Tkinter queue for supported Ollama benchmark campaigns.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--state-file", type=Path, help="Default: <repo>/local-state/queue-gui/queue.json")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Tkinter could not open a window: {exc}", file=sys.stderr)
        return 2
    # Always lock by checkout, even when an alternate JSON state path is supplied.
    lock = InstanceLock(repo_root / "local-state" / "queue-gui" / "instance.lock")
    try:
        lock.acquire()
    except (InstanceAlreadyRunning, OSError) as exc:
        messagebox.showerror("Benchmark queue unavailable", str(exc), parent=root)
        root.destroy()
        return 2
    try:
        app = BenchmarkQueueApp(root, repo_root, state_path=args.state_file)
        root.after(100, app.refresh_models)
        root.mainloop()
    finally:
        lock.close()
    return 0
