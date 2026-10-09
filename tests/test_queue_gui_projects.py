"""Additive GUI project-selection and legacy-persistence checks (no inference)."""
from __future__ import annotations
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from localbench.queue_gui.core import (
    BENCHMARKS, BenchmarkSettings, QueueState, benchmark_tasks,
    build_command, load_state, save_state,
)


class ProjectQueueCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="queue-projects-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.state_file = self.repo / "queue.json"
        for project in ("assistant-001", "assistant-002"):
            path = self.repo / "project-benchmarks" / project / "v1" / "packet.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "packet_id": project + "-v1",
                "tasks": [{"id": "T01", "title": "First stage"},
                          {"id": "T02", "title": "Second stage"}]
            }), encoding="utf-8")

    def test_tasks_come_from_packet_not_hardcoded(self):
        self.assertEqual(benchmark_tasks(self.repo, "roles"), [])
        self.assertEqual(benchmark_tasks(self.repo, "assistant-001"),
                         [("T01", "First stage"), ("T02", "Second stage")])
        path = self.repo / "project-benchmarks/assistant-002/v1/packet.json"
        value = json.loads(path.read_text())
        value["tasks"].append({"id": "T03", "title": "New project stage"})
        path.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(benchmark_tasks(self.repo, "assistant-002")[-1],
                         ("T03", "New project stage"))
        self.assertEqual(set(BENCHMARKS), {"roles", "assistant-001", "assistant-002"})

    def test_project_command_forwards_exact_flags_without_governor_or_runtime(self):
        settings = BenchmarkSettings.from_fields(
            benchmark="assistant-001", through="T02", phase="qualification",
            allow_host_execution=True, context_tokens="4096",
            max_output_tokens="2048", timeout_seconds="45.5", keep_alive_seconds="-1",
        )
        args = build_command(self.repo, "gemma3:12b", settings)
        self.assertEqual(args[args.index("-QueueBenchmark") + 1], "assistant-001")
        self.assertEqual(args[args.index("-Action") + 1], "run")
        self.assertEqual(args[args.index("-Through") + 1], "T02")
        self.assertEqual(args[args.index("-Phase") + 1], "qualification")
        self.assertIn("-AllowHostExecution", args)
        self.assertNotIn("-GovernorRoot", args)
        self.assertNotIn("-Runtime", args)
        self.assertEqual(args[-8:], ["-ContextTokens", "4096", "-MaxOutputTokens", "2048",
                                    "-TimeoutSeconds", "45.5", "-KeepAliveSeconds", "-1.0"])

    def test_project_runs_fail_closed_for_invalid_task_and_missing_consent(self):
        for project in ("assistant-001", "assistant-002"):
            with self.subTest(project=project):
                settings = BenchmarkSettings(benchmark=project, through="T01")
                with self.assertRaisesRegex(ValueError, "host-execution consent"):
                    build_command(self.repo, "gemma:latest", settings)
                with self.assertRaisesRegex(ValueError, "not in the selected"):
                    build_command(self.repo, "gemma:latest", BenchmarkSettings(
                        benchmark=project, through="T99", allow_host_execution=True))
        with self.assertRaises(ValueError):
            BenchmarkSettings(benchmark="unknown")
        with self.assertRaises(ValueError):
            BenchmarkSettings(benchmark="roles", through="T01")
        with self.assertRaises(ValueError):
            BenchmarkSettings(benchmark="roles", allow_host_execution=True)
        with self.assertRaises(ValueError):
            BenchmarkSettings(benchmark="assistant-001", through="T01",
                              allow_host_execution="true")
        (self.repo / "project-benchmarks/assistant-001/v1/packet.json").unlink()
        with self.assertRaisesRegex(ValueError, "Cannot read"):
            build_command(self.repo, "gemma:latest", BenchmarkSettings(
                benchmark="assistant-001", through="T01", allow_host_execution=True))

    def test_mixed_queue_settings_are_immutable_per_item_and_survive_restart(self):
        queue = QueueState()
        roles = BenchmarkSettings(phase="qualification")
        a001 = BenchmarkSettings(benchmark="assistant-001", through="T01",
                                 allow_host_execution=True, timeout_seconds=400)
        a002 = BenchmarkSettings(benchmark="assistant-002", through="T02",
                                 allow_host_execution=True, phase="qualification")
        queue.add_models(["same:latest"], roles)
        queue.add_models(["same:latest"], a001)
        queue.add_models(["same:latest"], a002)
        queue.add_models(["same:latest"], a001)  # exact entry duplicate
        self.assertEqual(len(queue.items), 3)
        queue.settings = BenchmarkSettings(phase="screen")
        queue.start()
        first = queue.start_next()
        self.assertEqual(first.settings, roles)
        queue.request_pause()
        queue.finish(first.id, 0)
        save_state(self.state_file, queue)
        restored = load_state(self.state_file)
        self.assertEqual(restored, queue)
        self.assertEqual([i.settings for i in restored.items], [roles, a001, a002])
        restored.start()
        second = restored.start_next()
        self.assertEqual(build_command(self.repo, second.model, second.settings)[
                         build_command(self.repo, second.model, second.settings).index("-Through")+1], "T01")

    def test_existing_v1_queue_upgrades_without_rerun_or_consent(self):
        original = QueueState(settings=BenchmarkSettings(
            phase="qualification", context_tokens=8192))
        original.add_models(["old:first", "old:second"])
        original.start()
        item = original.start_next()
        item.pid = 199
        original.request_pause()
        original.finish(item.id, 0)
        save_state(self.state_file, original)
        raw = json.loads(self.state_file.read_text())
        raw["version"] = 1
        for key in ("benchmark", "through", "allow_host_execution"):
            raw["settings"].pop(key)
        for old_item in raw["items"]:
            old_item.pop("settings")
        self.state_file.write_text(json.dumps(raw), encoding="utf-8")
        upgraded = load_state(self.state_file)
        self.assertEqual([i.settings for i in upgraded.items],
                         [original.settings, original.settings])
        self.assertEqual([i.status for i in upgraded.items], ["Complete", "Waiting"])
        self.assertEqual(upgraded.items[0].pid, 199)
        save_state(self.state_file, upgraded)
        self.assertEqual(json.loads(self.state_file.read_text())["version"], 2)

    def test_project_resume_never_runs_interrupted_item(self):
        settings = BenchmarkSettings(benchmark="assistant-002", through="T02", allow_host_execution=True)
        q = QueueState(settings=settings)
        q.add_models(["m:1", "m:2"], settings)
        q.start()
        first=q.start_next()
        first.pid=999
        save_state(self.state_file,q)
        recovered=load_state(self.state_file)
        self.assertEqual(recovered.status,"Paused")
        self.assertEqual(recovered.items[0].status,"Interrupted")
        recovered.start()
        self.assertEqual(recovered.start_next().model,"m:2")


@unittest.skipUnless(os.name == "nt", "Native PowerShell command routing on Windows")
class PowerShellRoutingTests(unittest.TestCase):
    def test_real_proxy_forwards_project_commands_and_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix="gui project cli ") as tmp:
            repo = Path(tmp)
            gui = repo / "tools/gui"
            scripts = repo / "tools/campaigns"
            gui.mkdir(parents=True)
            scripts.mkdir(parents=True)
            source = Path(__file__).resolve().parents[1] / "tools/gui/run-queue-item.ps1"
            (gui / source.name).write_bytes(source.read_bytes())
            for name in ("run-all-roles.ps1", "run-assistant-001.ps1", "run-assistant-002.ps1"):
                # Two dummy project command parsers; never invoke actual benchmarks.
                (scripts / name).write_text(
                    "param([string]$Action,[string]$Model,[string]$Phase,[string]$Through,"
                    "[switch]$AllowHostExecution,[double]$TimeoutSeconds)\n"
                    "[Console]::WriteLine(\"ROUTED=%s|$Action|$Model|$Phase|$Through|$AllowHostExecution|$TimeoutSeconds\")\n"
                    "[Console]::WriteLine('RUN_DIR=C:\\Bench runs\\Jos' + [char]233)\n"
                    "exit 19\n" % name,
                    encoding="utf-8",
                )
            for project in ("assistant-001", "assistant-002"):
                packet = repo / "project-benchmarks" / project / "v1" / "packet.json"
                packet.parent.mkdir(parents=True)
                packet.write_text(json.dumps({
                    "packet_id": project + "-v1",
                    "tasks": [{"id": "T01", "title": "First stage"},
                              {"id": "T02", "title": "Second stage"}],
                }), encoding="utf-8")
                settings = BenchmarkSettings(
                    benchmark=project, through="T02", phase="qualification",
                    allow_host_execution=True, timeout_seconds=42.5)
                command = build_command(repo, "gemma3:27b", settings)
                run = subprocess.run(command, cwd=repo, capture_output=True,
                                     text=True, encoding="utf-8", timeout=20)
                self.assertEqual(run.returncode, 19, run.stdout+" "+run.stderr)
                self.assertIn(f"ROUTED=run-{project}.ps1|run|gemma3:27b|qualification|T02|True|42.5",run.stdout)
                self.assertIn("RUN_DIR=C:\\Bench runs\\José", run.stdout)


if __name__ == "__main__":
    unittest.main()
