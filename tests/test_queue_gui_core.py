from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from localbench.queue_gui.core import (
    BenchmarkSettings,
    QueueState,
    build_command,
    load_state,
    parse_ollama_list,
    parse_run_dir,
    save_state,
    validate_model,
)


class SettingsAndCommandTests(unittest.TestCase):
    def test_defaults_delegate_advanced_values_to_cli(self):
        settings = BenchmarkSettings.from_fields(
            context_tokens="", max_output_tokens=" ", timeout_seconds="", keep_alive_seconds="",
        )
        root = Path("checkout with spaces")
        self.assertEqual(build_command(root, "gemma3:27b", settings), [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(root / "tools" / "gui" / "run-queue-item.ps1"),
            "-Runtime", "ollama", "-Model", "gemma3:27b", "-Phase", "screen",
            "-GovernorRoot", r"C:\Projects\governor",
        ])

    def test_explicit_fields_and_qualification_construct_exact_arguments(self):
        settings = BenchmarkSettings.from_fields(
            phase="qualification", governor_root=r"C:\My Projects\governor",
            context_tokens="32768", max_output_tokens="8192",
            timeout_seconds="600.5", keep_alive_seconds="-1",
        )
        command = build_command(Path("repo"), "host:1234/team/Model:Q4_K_M", settings, "pwsh")
        self.assertEqual(command[0], "pwsh")
        self.assertEqual(command[command.index("-Model") + 1], "host:1234/team/Model:Q4_K_M")
        self.assertEqual(command[command.index("-Phase") + 1], "qualification")
        self.assertEqual(command[command.index("-GovernorRoot") + 1], r"C:\My Projects\governor")
        self.assertEqual(command[-8:], [
            "-ContextTokens", "32768", "-MaxOutputTokens", "8192",
            "-TimeoutSeconds", "600.5", "-KeepAliveSeconds", "-1.0",
        ])

    def test_path_metacharacters_remain_one_literal_argument(self):
        governor = r"C:\Projects\governor; $(Write-Output unexpected)"
        command = build_command(Path("repo"), "gemma3:27b", BenchmarkSettings(governor_root=governor))
        self.assertEqual(command[-2:], ["-GovernorRoot", governor])

    def test_models_are_exact_and_unsafe_or_flag_like_names_are_rejected(self):
        for model in ("gemma3:27b", "127.0.0.1:5000/owner/model:Q4_K_M", "team/model-name:v1.2"):
            with self.subTest(model=model):
                self.assertEqual(validate_model(model), model)
        for model in ("", " gemma3:27b", "gemma3:27b ", "foo bar", "-EncodedCommand",
                      "gemma3\n-File", "foo;calc.exe", "$(calc)", "foo\x00bar", None):
            with self.subTest(model=model):
                with self.assertRaises(ValueError):
                    build_command(Path("repo"), model, BenchmarkSettings())

    def test_positive_int32_token_limits(self):
        self.assertEqual(BenchmarkSettings.from_fields(context_tokens="2147483647").context_tokens,
                         2_147_483_647)
        for field_name in ("context_tokens", "max_output_tokens"):
            for value in ("0", "-1", "2147483648", "1.5", "nan", True, 1.5):
                with self.subTest(field=field_name, value=value):
                    with self.assertRaises(ValueError):
                        BenchmarkSettings.from_fields(**{field_name: value})

    def test_duration_values_are_finite_and_timeout_positive(self):
        for value in ("0", "-1", "nan", "inf", "-inf", True, "not a number", 10 ** 500):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    BenchmarkSettings.from_fields(timeout_seconds=value)
        for value in ("0", "-1", "-100", "0.5"):
            with self.subTest(value=value):
                self.assertEqual(BenchmarkSettings.from_fields(keep_alive_seconds=value).keep_alive_seconds,
                                 float(value))
        for value in ("nan", "inf", "-inf", True):
            with self.subTest(keep_alive=value):
                with self.assertRaises(ValueError):
                    BenchmarkSettings.from_fields(keep_alive_seconds=value)

    def test_invalid_phase_and_governor_are_rejected(self):
        for fields in ({"phase": "smoke"}, {"governor_root": " "},
                       {"governor_root": "C:\\bad\npath"}, {"governor_root": None}):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):
                    BenchmarkSettings.from_fields(**fields)

    def test_direct_settings_reject_wrong_types_and_are_immutable(self):
        for fields in ({"context_tokens": "123"}, {"timeout_seconds": "600"},
                       {"keep_alive_seconds": float("nan")}):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):
                    BenchmarkSettings(**fields)
        with self.assertRaises(FrozenInstanceError):
            BenchmarkSettings().phase = "qualification"


class OutputParsingTests(unittest.TestCase):
    def test_ollama_table_handles_spacing_ansi_crlf_and_stable_duplicates(self):
        output = (
            "Warning: unrelated text\r\n"
            "\x1b[1mNAME                    ID              SIZE      MODIFIED\x1b[0m\r\n"
            "gemma3:27b               84f2d2fe49bd    17 GB     2 hours ago\r\n"
            "host:5000/me/qwen:Q4_K_M abcdef012345    6.5 GB    Just now\r\n"
            "gemma3:27b               84f2d2fe49bd    17 GB     2 hours ago\r\n"
            "Error: could not connect to server\r\n"
        )
        self.assertEqual(parse_ollama_list(output), ["gemma3:27b", "host:5000/me/qwen:Q4_K_M"])

    def test_ollama_empty_and_non_table_output(self):
        for output in ("", "NAME ID SIZE MODIFIED\n", "Error: server unavailable\n",
                       "model explanation this is not a table\n",
                       "NAME ID SIZE MODIFIED\nbogus not-a-hash 1 GB today\n"):
            with self.subTest(output=output):
                self.assertEqual(parse_ollama_list(output), [])

    def test_run_dir_plain_quoted_and_timestamped(self):
        expected = r"C:\My Benchmarks\run-01"
        for output in (
            f"RUN_DIR={expected}\r\n", f'RUN_DIR="{expected}"', f"RUN_DIR='{expected}'",
            f"[2026-10-08T00:20:00Z] RUN_DIR={expected}",
            f"[00:20:00] RUN_DIR={expected}", f"\x1b[32mRUN_DIR={expected}\x1b[0m",
        ):
            with self.subTest(output=output):
                self.assertEqual(parse_run_dir(output), expected)

    def test_run_dir_ignores_incidental_or_empty_markers(self):
        for output in ("example RUN_DIR=C:\\other", "[INFO] example RUN_DIR=C:\\other",
                       "RUN_DIR=", 'RUN_DIR=""', 'RUN_DIR="unclosed',
                       "RUN_DIR=C:\\a\nRUN_DIR=C:\\b", "RUN_DIR=bad\x00path"):
            with self.subTest(output=output):
                self.assertIsNone(parse_run_dir(output))


class QueueTransitionTests(unittest.TestCase):
    def make_queue(self):
        state = QueueState()
        state.add_models(["gemma3:12b", "gemma3:27b", "qwen3.5:9b"])
        state.start()
        return state

    def test_add_preserves_order_and_deduplicates(self):
        state = QueueState()
        added = state.add_models(["gemma3:27b", "qwen3.5:9b", "gemma3:27b"])
        self.assertEqual([item.model for item in state.items], ["gemma3:27b", "qwen3.5:9b"])
        self.assertEqual(len(added), 2)
        self.assertEqual(len({item.id for item in state.items}), 2)

    def test_invalid_add_is_atomic_and_running_queue_cannot_be_edited(self):
        state = QueueState()
        with self.assertRaises(ValueError):
            state.add_models(["gemma3:12b", "bad model"])
        self.assertEqual(state.items, [])
        state = self.make_queue()
        with self.assertRaises(ValueError):
            state.add_models(["another:latest"])

    def test_only_one_active_and_completion_does_not_start_next(self):
        state = self.make_queue()
        first = state.start_next()
        self.assertEqual(first.model, "gemma3:12b")
        self.assertIsNone(state.start_next())
        with self.assertRaises(ValueError):
            state.start()
        state.finish(first.id, 0)
        self.assertIsNone(state.active)
        self.assertEqual([item.status for item in state.items], ["Complete", "Waiting", "Waiting"])
        second = state.start_next()
        self.assertEqual(second.model, "gemma3:27b")
        self.assertIsNone(state.start_next())

    def test_pause_after_current_and_continue(self):
        state = self.make_queue()
        first = state.start_next()
        first.pid = 42
        state.request_pause()
        self.assertEqual(state.pending_action, "pause")
        self.assertEqual(state.status, "Running")
        self.assertIs(state.active, first)
        self.assertIsNone(state.start_next())
        state.finish(first.id, 0)
        self.assertEqual(state.status, "Paused")
        self.assertEqual(first.pid, 42)
        self.assertIsNone(state.start_next())
        state.start()
        self.assertEqual(state.start_next().model, "gemma3:27b")
        self.assertEqual(first.status, "Complete")

    def test_stop_after_current_keeps_remaining_waiting(self):
        state = self.make_queue()
        first = state.start_next()
        state.request_stop()
        self.assertIs(state.active, first)
        state.finish(first.id, 0)
        self.assertEqual(state.status, "Stopped")
        self.assertEqual(len(state.waiting), 2)
        self.assertIsNone(state.start_next())

    def test_stop_supersedes_pause_in_either_order(self):
        for order in (("request_pause", "request_stop"), ("request_stop", "request_pause")):
            with self.subTest(order=order):
                state = self.make_queue()
                first = state.start_next()
                for method in order:
                    getattr(state, method)()
                self.assertEqual(state.pending_action, "stop")
                state.finish(first.id, 0)
                self.assertEqual(state.status, "Stopped")

    def test_pause_or_stop_between_completion_and_next_claim(self):
        for method, expected in (("request_pause", "Paused"), ("request_stop", "Stopped")):
            with self.subTest(method=method):
                state = self.make_queue()
                first = state.start_next()
                state.finish(first.id, 0)
                getattr(state, method)()
                self.assertEqual(state.status, expected)
                self.assertIsNone(state.start_next())

    def test_last_item_drains_to_complete_even_with_pending_pause_or_stop(self):
        for method in ("request_pause", "request_stop"):
            with self.subTest(method=method):
                state = QueueState()
                state.add_models(["gemma3:27b"])
                state.start()
                item = state.start_next()
                getattr(state, method)()
                state.finish(item.id, 0)
                self.assertEqual(state.status, "Complete")
                self.assertIsNone(state.pending_action)
                self.assertIsNone(state.start_next())

    def test_failed_or_unlaunchable_item_does_not_discard_evidence_or_block_next(self):
        for code, error in ((7, None), (None, "PowerShell was not found")):
            with self.subTest(code=code):
                state = self.make_queue()
                first = state.start_next()
                first.run_dir = r"C:\run with spaces"
                state.finish(first.id, code, error=error)
                self.assertEqual(first.status, "Failed")
                self.assertEqual(first.exit_code, code)
                self.assertEqual(first.run_dir, r"C:\run with spaces")
                self.assertIsNotNone(first.started_at)
                self.assertIsNotNone(first.finished_at)
                self.assertEqual(state.start_next().model, "gemma3:27b")

    def test_interruption_and_stale_completion(self):
        state = self.make_queue()
        first = state.start_next()
        state.request_stop()
        state.finish(first.id, -1, error="Stopped by user", interrupted=True)
        self.assertEqual(first.status, "Interrupted")
        state.start()
        second = state.start_next()
        with self.assertRaises(ValueError):
            state.finish(first.id, 0)
        self.assertIs(state.active, second)

    def test_resume_never_retries_completed_failed_or_interrupted_entries(self):
        state = self.make_queue()
        for code, interrupted in ((0, False), (3, False), (-1, True)):
            item = state.start_next()
            state.finish(item.id, code, interrupted=interrupted)
        self.assertEqual(state.status, "Complete")
        state.start()
        self.assertIsNone(state.start_next())
        self.assertEqual(len(state.items), 3)
        state.add_models(["fresh:latest"])
        self.assertEqual(state.status, "Idle")


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "nested" / "queue.json"

    def make_queue(self):
        state = QueueState(settings=BenchmarkSettings.from_fields(phase="qualification", timeout_seconds="600.5"))
        state.add_models(["gemma3:12b", "gemma3:27b"])
        return state

    def test_nonexistent_state_returns_empty_idle_queue(self):
        state = load_state(self.path)
        self.assertEqual(state.status, "Idle")
        self.assertEqual(state.items, [])

    def test_roundtrip_preserves_order_settings_completed_and_waiting(self):
        state = self.make_queue()
        state.start()
        first = state.start_next()
        first.run_dir = r"C:\run with spaces\one"
        first.pid = 12345
        state.request_pause()
        state.finish(first.id, 0)
        save_state(self.path, state)
        restored = load_state(self.path)
        self.assertEqual(restored, state)
        self.assertEqual(restored.status, "Paused")
        self.assertEqual(restored.items[0].run_dir, r"C:\run with spaces\one")
        self.assertEqual(restored.items[0].exit_code, 0)
        self.assertEqual(restored.items[1].status, "Waiting")
        self.assertEqual(set(json.loads(self.path.read_text())),
                         {"version", "items", "settings", "status", "pending_action"})

    def test_running_recovery_preserves_pid_and_run_dir_but_never_retries(self):
        state = self.make_queue()
        state.start()
        first = state.start_next()
        first.pid = 12345
        first.run_dir = r"C:\partial run"
        state.request_stop()
        save_state(self.path, state)
        restored = load_state(self.path)
        self.assertEqual(restored.status, "Paused")
        self.assertIsNone(restored.pending_action)
        self.assertIsNone(restored.active)
        recovered = restored.items[0]
        self.assertEqual(recovered.status, "Interrupted")
        self.assertEqual(recovered.pid, 12345)
        self.assertEqual(recovered.run_dir, r"C:\partial run")
        self.assertEqual(recovered.started_at, first.started_at)
        self.assertIsNotNone(recovered.finished_at)
        self.assertIn("Verify", recovered.error)
        self.assertIsNone(restored.start_next())
        restored.start()
        self.assertEqual(restored.start_next().model, "gemma3:27b")

    def test_recovery_between_models_is_paused(self):
        state = self.make_queue()
        state.start()
        save_state(self.path, state)
        restored = load_state(self.path)
        self.assertEqual(restored.status, "Paused")
        self.assertIsNone(restored.start_next())
        self.assertTrue(all(item.status == "Waiting" for item in restored.items))

    def test_failed_atomic_replace_leaves_previous_file_intact_and_cleans_temp(self):
        state = self.make_queue()
        save_state(self.path, state)
        original = self.path.read_bytes()
        state.add_models(["qwen3.5:9b"])
        with patch("localbench.queue_gui.core.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaisesRegex(OSError, "disk failure"):
                save_state(self.path, state)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_corrupt_json_raises_without_overwriting_it(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid queue state"):
            load_state(self.path)
        self.assertEqual(self.path.read_text(), "{broken")

    def test_malformed_schema_and_inconsistent_results_are_rejected(self):
        state = self.make_queue()
        save_state(self.path, state)
        valid = json.loads(self.path.read_text())

        def changes():
            yield lambda data: data.update(version=3)
            yield lambda data: data.update(version=True)
            yield lambda data: data.update(environment={"TOKEN": "must not be accepted"})
            yield lambda data: data.update(items={})
            yield lambda data: data.update(pending_action="resume")
            yield lambda data: data.update(pending_action="pause")
            yield lambda data: data.update(status="Complete")
            yield lambda data: data["settings"].update(context_tokens="32768")
            yield lambda data: data["settings"].update(timeout_seconds=float("nan"))
            yield lambda data: data["items"][0].update(status="Other")
            yield lambda data: data["items"][0].update(id="not-a-uuid")
            yield lambda data: data["items"][1].update(id=data["items"][0]["id"])
            yield lambda data: data["items"][0].update(pid=True)
            yield lambda data: data["items"][0].update(exit_code=False)
            yield lambda data: data["items"][0].update(run_dir="C:\\unexpected")
            yield lambda data: data["items"][0].update(status="Complete", exit_code=0)
            yield lambda data: data["items"][0].update(status="Running", finished_at="2026-10-08T01:00:00+00:00")
            yield lambda data: data["items"][0].update(started_at="not-a-time")

        for index, change in enumerate(changes()):
            with self.subTest(case=index):
                malformed = json.loads(json.dumps(valid))
                change(malformed)
                self.path.write_text(json.dumps(malformed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_state(self.path)

    def test_more_than_one_active_process_is_rejected(self):
        state = self.make_queue()
        state.start()
        first = state.start_next()
        state.items[1].status = "Running"
        state.items[1].started_at = first.started_at
        with self.assertRaisesRegex(ValueError, "active process"):
            save_state(self.path, state)


if __name__ == "__main__":
    unittest.main()
