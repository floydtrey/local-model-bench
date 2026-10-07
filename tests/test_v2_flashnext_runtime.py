from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from localbench.v2 import flashnext_runtime as runtime
from localbench.v2.records import host_profile


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "campaigns" / "flashnext-all-roles-v1"


def profile() -> dict:
    return json.loads((CAMPAIGN / "runtime-profile.json").read_bytes())


def fake_artifacts(root: Path) -> dict:
    result = profile()
    root.mkdir(parents=True, exist_ok=True)
    executable = root / "llama-server.exe"
    executable.write_bytes(b"synthetic runtime; never execute\n")
    (root / "ggml-cuda.dll").write_bytes(b"synthetic adjacent runtime DLL\n")
    entry = root / "Qwen3.8-Flash-Next-UD-IQ3_XXS-00001-of-00003.gguf"
    for ordinal in range(1, 4):
        entry.with_name(entry.name.replace("00001-of", f"{ordinal:05d}-of")).write_bytes(
            b"GGUF" + ordinal.to_bytes(4, "little") + b"synthetic header only\n"
        )
    result["server_executable"] = str(executable)
    result["model_entry"] = str(entry)
    return result


def fake_host(logical_id: str, **_) :
    return host_profile(
        logical_id, captured_at="2026-10-07T00:00:00Z",
        os_info={"system": "Windows", "release": "11", "machine": "AMD64"},
        cpu={"model": "synthetic CPU", "physical_cores": 8, "logical_cores": 16},
        memory={"installed_bytes": 64 * 2**30, "available_bytes": 32 * 2**30},
        gpus=[{"name": "synthetic GPU", "vram_bytes": 16 * 2**30}],
        storage=[{"volume": "C:", "total_bytes": 1000, "free_bytes": 500}],
        python={"version": "3.12", "architecture": "64bit"},
        compute_runtimes=[], power_thermal={},
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def valid_props(config: dict) -> dict:
    return {
        "total_slots": 1,
        "default_generation_settings": {"n_ctx": runtime.CONTEXT_TOKENS},
        "model_path": config["model_entry"],
        "chat_template": "{{ messages }}",
    }


class FakeChild:
    def __init__(self, *, exited: int | None = None, stubborn: bool = False):
        self.pid = 45678
        self.returncode = exited
        self.terminated = 0
        self.killed = 0
        self.waits = []
        self.stubborn = stubborn

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1
        self.returncode = -9

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.stubborn and self.killed == 0:
            raise subprocess.TimeoutExpired("synthetic child", timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class FlashNextRuntimeTests(unittest.TestCase):
    def test_pinned_launch_argv_and_environment_are_preserved(self) -> None:
        config = profile()
        command = runtime.server_command(config)
        self.assertEqual(command[:15], [
            config["server_executable"], "--model", config["model_entry"],
            "--alias", "C01", "--ctx-size", "262144", "--parallel", "1",
            "--host", "127.0.0.1", "--port", str(config["port"]), "-ngl", "99",
        ])
        self.assertEqual(command[13:], [
            "-ngl", "99", "-ncmoe", "99", "-fa", "on", "-ctk", "f16", "-ctv", "f16",
            "-t", "8", "-b", "256", "-ub", "128", "--no-sched-async-cpu",
            "--no-context-shift", "--predict", "-1", "--reasoning-budget", "-1",
            "--timeout", "-1", "--jinja", "--reasoning", "auto", "--reasoning-format",
            "deepseek", "--metrics",
        ])
        self.assertEqual(config["environment"], {"GGML_CUDA_REGISTER_HOST": "1", "HF_HUB_OFFLINE": "1"})
        for change in ({"candidate_id": "other"}, {"context_tokens": 32768}, {"fork_revision": "0" * 40},
                       {"parallel_slots": 2}, {"host": "0.0.0.0"}, {"server_args": []},
                       {"environment": {"HF_HUB_OFFLINE": "0"}}):
            with self.subTest(change=change), self.assertRaises(runtime.FlashNextBlocked):
                runtime.server_command({**config, **change})

    def test_all_three_model_shards_are_required_and_header_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = fake_artifacts(Path(temp))
            entry = Path(config["model_entry"])
            shards = runtime.shard_paths(entry)
            self.assertEqual(len(shards), 3)
            self.assertEqual(shards[0], entry)
            for ordinal, shard in enumerate(shards, 1):
                self.assertIn(f"{ordinal:05d}-of-00003.gguf", shard.name)
            saved = shards[-1].read_bytes()
            shards[-1].unlink()
            with self.assertRaisesRegex(runtime.FlashNextBlocked, "missing required model shard"):
                runtime.shard_paths(entry)
            shards[-1].write_bytes(b"NOPE" + saved[4:])
            with self.assertRaisesRegex(runtime.FlashNextBlocked, "not a GGUF"):
                runtime.shard_paths(entry)
            with self.assertRaisesRegex(runtime.FlashNextBlocked, "shard 00001"):
                runtime.shard_paths(shards[1])

    def test_revision_requires_a_matching_reported_commit(self) -> None:
        self.assertEqual(runtime.verify_version_revision("version: 7170 (27c54b4bb)\n"), "27c54b4bb")
        self.assertEqual(runtime.verify_version_revision("build " + runtime.FORK_REVISION), runtime.FORK_REVISION)
        for output in ("llama-server 7170 built with CUDA", "version: 7170 (abcdef01)", "27c54b"):
            with self.subTest(output=output), self.assertRaises(runtime.FlashNextBlocked):
                runtime.verify_version_revision(output)

    def _preflight(self, config: dict, output: Path, version: subprocess.CompletedProcess):
        with patch.object(runtime, "validate_sources", return_value={"test_sources": "synthetic"}), \
             patch.object(runtime, "SystemHostProbe"), \
             patch.object(runtime, "collect_host_profile", side_effect=fake_host), \
             patch.object(runtime.subprocess, "run", return_value=version) as run, \
             patch.object(runtime.subprocess, "Popen") as popen:
            result = runtime.preflight_identity(
                profile=config, repo_root=ROOT, campaign_root=CAMPAIGN,
                output_dir=output, progress=lambda _: None,
            )
            popen.assert_not_called()
            self.assertEqual(run.call_args.args[0], [config["server_executable"], "--version"])
            self.assertEqual(run.call_args.kwargs["env"]["HF_HUB_OFFLINE"], "1")
            self.assertEqual(run.call_args.kwargs["env"]["GGML_CUDA_REGISTER_HOST"], "1")
            return result

    def test_preflight_records_all_artifacts_without_loading_or_qualifying_a_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fake_artifacts(root / "installation")
            version = subprocess.CompletedProcess([], 0, b"version: 7170 (27c54b4bb)\n", b"CUDA build\n")
            result = self._preflight(config, root / "run", version)
            receipt = result["preflight"]
            self.assertFalse(receipt["model_started"])
            self.assertFalse(receipt["model_or_role_qualified"])
            self.assertEqual(len(receipt["model_artifacts"]), 3)
            self.assertEqual({item["file"] for item in receipt["runtime_installation"]}, {"llama-server.exe", "ggml-cuda.dll"})
            self.assertEqual((root / "run/runtime/version.stdout.bin").read_bytes(), version.stdout)
            self.assertEqual((root / "run/runtime/version.stderr.bin").read_bytes(), version.stderr)
            self.assertEqual(result["runtime"].payload["build"], runtime.FORK_REVISION)
            self.assertEqual(result["interface"].payload["backend_kind"], "llama_cpp")
            for artifact in receipt["model_artifacts"]:
                self.assertEqual(artifact["sha256"], hashlib.sha256((root / "installation" / artifact["file"]).read_bytes()).hexdigest())

    def test_missing_executable_or_model_blocks_before_even_version_execution(self) -> None:
        for missing in ("executable", "model"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config = fake_artifacts(root / "installation")
                Path(config["server_executable"] if missing == "executable" else config["model_entry"]).unlink()
                with patch.object(runtime, "validate_sources", return_value={}), \
                     patch.object(runtime.subprocess, "run") as run, \
                     patch.object(runtime.subprocess, "Popen") as popen, \
                     self.assertRaises(runtime.FlashNextBlocked):
                    runtime.preflight_identity(profile=config, repo_root=ROOT, campaign_root=CAMPAIGN,
                                               output_dir=root / "run", progress=lambda _: None)
                run.assert_not_called()
                popen.assert_not_called()

    def test_wrong_version_is_preserved_but_cannot_advance_to_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fake_artifacts(root / "installation")
            version = subprocess.CompletedProcess([], 0, b"version: 9999 (abcdef01)\n", b"diagnostic\n")
            with patch.object(runtime, "validate_sources", return_value={}), \
                 patch.object(runtime.subprocess, "run", return_value=version), \
                 patch.object(runtime.subprocess, "Popen") as popen, \
                 self.assertRaisesRegex(runtime.FlashNextBlocked, "pinned fork"):
                runtime.preflight_identity(profile=config, repo_root=ROOT, campaign_root=CAMPAIGN,
                                           output_dir=root / "run", progress=lambda _: None)
            self.assertEqual((root / "run/runtime/version.stdout.bin").read_bytes(), version.stdout)
            self.assertFalse((root / "run/preflight.json").exists())
            popen.assert_not_called()

    def test_repeated_preflight_cannot_overwrite_earlier_raw_version_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fake_artifacts(root / "installation")
            original = subprocess.CompletedProcess([], 0, b"version: 7170 (27c54b4bb)\n", b"original diagnostic\n")
            self._preflight(config, root / "run", original)
            raw = root / "run/runtime"
            saved = {name: (raw / name).read_bytes() for name in ("version.stdout.bin", "version.stderr.bin", "version.json")}
            replacement = subprocess.CompletedProcess([], 0, b"version: 9999 (abcdef01)\n", b"changed diagnostic\n")
            with self.assertRaises(runtime.FlashNextBlocked):
                self._preflight(config, root / "run", replacement)
            self.assertEqual({name: (raw / name).read_bytes() for name in saved}, saved)

    def test_source_validation_accepts_both_actual_manifest_schemas(self) -> None:
        result = runtime.validate_sources(ROOT, CAMPAIGN)
        self.assertEqual(result["shared_case_counts"], {"L0": 9, "L1": 5, "L2": 8})
        self.assertEqual(set(result["role_source_manifests"]), {"local-model-bench", "deepseek-lab"})

    def _source_fixture(self, destination: Path) -> tuple[Path, Path]:
        repo = destination / "repo"
        campaign = repo / "campaigns" / "flashnext-all-roles-v1"
        campaign.mkdir(parents=True)
        lock = json.loads((CAMPAIGN / "accepted-battery-lock.json").read_bytes())
        shutil.copy2(CAMPAIGN / "accepted-battery-lock.json", campaign)
        shutil.copytree(CAMPAIGN / "sources", campaign / "sources")
        for row in lock["files"]:
            target = repo / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / row["path"], target)
        return repo, campaign

    def test_accepted_battery_and_vendored_source_tampering_block(self) -> None:
        for kind in ("battery", "source", "manifest-pin", "manifest-entry", "manifest-blob", "manifest-bytes"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                repo, campaign = self._source_fixture(Path(temp))
                source = campaign / "sources" / "deepseek-lab"
                if kind == "battery":
                    path = repo / "benchmark-packs/v2/shared-l0-core-v1.json"
                    path.write_bytes(path.read_bytes() + b" ")
                elif kind == "source":
                    path = source / "native-lab/reviewer-role.md"
                    path.write_bytes(path.read_bytes() + b"changed\n")
                else:
                    path = source / "SOURCE_MANIFEST.json"
                    manifest = json.loads(path.read_bytes())
                    if kind == "manifest-pin":
                        manifest["source_commit"] = "0" * 40
                        manifest["commit"] = "0" * 40
                    elif kind == "manifest-entry":
                        manifest["files"].pop()
                    elif kind == "manifest-blob":
                        manifest["files"][0]["source_git_blob"] = "0" * 40
                        manifest["files"][0]["git_blob_sha"] = "0" * 40
                    else:
                        manifest["files"][0]["bytes"] += 1
                    path.write_text(json.dumps(manifest))
                with self.assertRaises(runtime.FlashNextBlocked):
                    runtime.validate_sources(repo, campaign)

    def test_occupied_loopback_port_never_attaches_or_starts_a_child(self) -> None:
        with tempfile.TemporaryDirectory() as temp, socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            config = profile()
            config["port"] = listener.getsockname()[1]
            server = runtime.OwnedFlashNextServer(config, Path(temp), progress=lambda _: None)
            with patch.object(runtime.subprocess, "Popen") as popen, self.assertRaisesRegex(runtime.FlashNextBlocked, "already occupied"):
                server.start()
            popen.assert_not_called()
            self.assertIsNone(server.process)
            self.assertEqual(listener.getsockname()[1], config["port"])

    def test_owned_lifecycle_preserves_config_and_stops_only_the_created_child(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = profile()
            config["port"] = free_port()
            server = runtime.OwnedFlashNextServer(config, Path(temp), progress=lambda _: None)
            child = FakeChild()
            replies = {"/health": {"status": "ok"}, "/v1/models": {"data": [{"id": "C01"}]}, "/props": valid_props(config), "/metrics": None}
            with patch.object(runtime.subprocess, "Popen", return_value=child) as popen, \
                 patch.object(server, "_get", side_effect=lambda path, **_: replies[path]), \
                 patch.object(runtime.subprocess, "run") as unrelated:
                with server:
                    self.assertEqual(server.process.pid, child.pid)
                    self.assertEqual(child.terminated, 0)
                    self.assertIsNotNone(server.ready_seconds)
                unrelated.assert_not_called()
            self.assertEqual(popen.call_args.args[0], runtime.server_command(config))
            self.assertEqual(popen.call_args.kwargs["env"]["HF_HUB_OFFLINE"], "1")
            self.assertEqual(popen.call_args.kwargs["env"]["GGML_CUDA_REGISTER_HOST"], "1")
            self.assertEqual(child.terminated, 1)
            self.assertEqual(child.killed, 0)
            self.assertTrue(all(stream.closed for stream in server._files))
            self.assertEqual(json.loads((Path(temp) / "process.json").read_bytes())["pid"], child.pid)
            self.assertEqual(json.loads((Path(temp) / "ready.json").read_bytes())["cold_kind"], "new_process_os_file_cache_unknown")

    def test_props_mismatch_stops_owned_process_and_does_not_become_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = profile()
            config["port"] = free_port()
            server = runtime.OwnedFlashNextServer(config, Path(temp), progress=lambda _: None)
            child = FakeChild()
            replies = {"/health": {"status": "ok"}, "/v1/models": {"data": [{"id": "C01"}]},
                       "/props": {**valid_props(config), "model_path": "C:\\wrong\\model.gguf"}}
            with patch.object(runtime.subprocess, "Popen", return_value=child), \
                 patch.object(server, "_get", side_effect=lambda path, **_: replies[path]), \
                 self.assertRaisesRegex(runtime.FlashNextBlocked, "model_path"):
                server.start()
            self.assertEqual(child.terminated, 1)
            self.assertTrue(all(stream.closed for stream in server._files))
            self.assertFalse((Path(temp) / "ready.json").exists())

    def test_context_requires_measured_props_or_unambiguous_owned_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            config = profile()
            server = runtime.OwnedFlashNextServer(config, output, progress=lambda _: None)
            props = valid_props(config)
            server._validate_props(props)
            server._validate_props({**props, "default_generation_settings": {}, "n_ctx": runtime.CONTEXT_TOKENS})
            (output / "server.stdout.log").write_text("llama_context: n_ctx = 262144\n")
            (output / "server.stderr.log").write_text("n_ctx_per_seq = 262144\n")
            without_context = {**props, "default_generation_settings": {}}
            server._validate_props(without_context)
            (output / "server.stderr.log").write_text("n_ctx_per_seq = 32768\n")
            with self.assertRaisesRegex(runtime.FlashNextBlocked, "effective context"):
                server._validate_props(without_context)
            for changed in ({"total_slots": 2}, {"chat_template": ""}, {"default_generation_settings": {"n_ctx": 32768}}):
                with self.subTest(changed=changed), self.assertRaises(runtime.FlashNextBlocked):
                    server._validate_props({**props, **changed})

    def test_stop_escalates_only_owned_stubborn_child_and_cancels_watchdog(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            server = runtime.OwnedFlashNextServer(profile(), Path(temp), progress=lambda _: None)
            child = FakeChild(stubborn=True)
            server.process = child
            timer = Mock()
            server._timers.append(timer)
            server.stop()
            self.assertEqual(child.terminated, 1)
            self.assertEqual(child.killed, 1)
            self.assertEqual(child.waits, [5, 5])
            timer.cancel.assert_called()
            server.stop()
            self.assertEqual(child.terminated, 1)

    def test_http_errors_and_plaintext_metrics_remain_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            server = runtime.OwnedFlashNextServer(profile(), output, progress=lambda _: None)
            metrics = io.BytesIO(b"llamacpp:tokens_predicted_total 12\n")
            metrics.status = 200
            malformed = io.BytesIO(b"{malformed props")
            malformed.status = 200
            opener = Mock()
            opener.open.side_effect = [metrics, malformed]
            server._opener = opener
            self.assertIsNone(server._get("/metrics", required=False))
            with self.assertRaisesRegex(runtime.FlashNextBlocked, "malformed JSON"):
                server._get("/props")
            self.assertEqual((output / "get-0001-metrics.body.bin").read_bytes(), b"llamacpp:tokens_predicted_total 12\n")
            self.assertEqual((output / "get-0002-props.body.bin").read_bytes(), b"{malformed props")
            observation = json.loads((output / "get-0002-props.json").read_bytes())
            self.assertEqual(observation["http_status"], 200)
            self.assertEqual(observation["body_sha256"], hashlib.sha256(b"{malformed props").hexdigest())


if __name__ == "__main__":
    unittest.main()
