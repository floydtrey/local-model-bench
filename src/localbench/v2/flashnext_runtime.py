"""Owned, offline Flash-Next process lifecycle for the separate V2 campaign.

Nothing here selects an alternative runtime, downloads an artifact, or attaches to
an already running server. Runtime qualification is produced by the campaign,
not by successfully creating these identity records.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from .contracts import SealedEvidence, canonical_json_bytes, sha256_json
from .execution_interface import execution_interface_identity
from .host import SystemHostProbe, collect_host_profile
from .orchestrator import EvidenceStore
from .records import model_identity, runtime_profile


FORK_REVISION = "27c54b4bbcefadedcec6397477cc2e866c1db716"
CONTEXT_TOKENS = 262144
BASE_COMMIT = "b01ec0a7cc693c8f4d731e13dedac613f2defba2"
CAMPAIGN_NAME = "flashnext-all-roles-v1"
CUDA_RUNTIME_DLLS = ("cudart64_13.dll", "cublas64_13.dll", "cublasLt64_13.dll")
SERVER_ARGS = (
    "-ngl", "99", "-ncmoe", "99", "-fa", "on", "-ctk", "f16", "-ctv", "f16",
    "-t", "8", "-b", "256", "-ub", "128", "--no-sched-async-cpu",
    "--no-context-shift", "--predict", "-1", "--reasoning-budget", "-1",
    "--timeout", "-1", "--jinja", "--reasoning", "auto", "--reasoning-format",
    "deepseek", "--metrics",
)


class FlashNextBlocked(RuntimeError):
    """An operational prerequisite failed; no intrinsic model verdict follows."""


def write_json_once(path: Path, value: Any) -> None:
    write_bytes_once(path, canonical_json_bytes(value) + b"\n")


def write_bytes_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise FlashNextBlocked(f"refusing to overwrite evidence: {path}")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_digest(path: Path, progress: Callable[[str], None] | None = None) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    count = 0
    last = time.monotonic()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
            count += len(block)
            if progress and time.monotonic() - last >= 15:
                progress(f"Hashing {path.name}: {count / 2**30:.1f}/{before.st_size / 2**30:.1f} GiB")
                last = time.monotonic()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise FlashNextBlocked(f"artifact changed while hashing: {path}")
    return digest.hexdigest()


def validate_profile(profile: Mapping[str, Any]) -> None:
    if profile.get("schema_version") != "flashnext-runtime-profile:v1":
        raise FlashNextBlocked("unsupported Flash-Next profile version")
    expected = {
        "candidate_id": "C01", "fork_revision": FORK_REVISION,
        "context_tokens": CONTEXT_TOKENS, "parallel_slots": 1, "host": "127.0.0.1",
    }
    for key, value in expected.items():
        if profile.get(key) != value:
            raise FlashNextBlocked(f"campaign requires {key}={value!r}")
    if tuple(profile.get("server_args", ())) != SERVER_ARGS:
        raise FlashNextBlocked("server flags differ from the pinned verified configuration; version the campaign before retuning")
    if profile.get("environment") != {"GGML_CUDA_REGISTER_HOST": "1", "HF_HUB_OFFLINE": "1",
                                       "LLAMA_WIN32_PREFETCH": "0"}:
        raise FlashNextBlocked("the pinned offline/CUDA settings and Windows bulk-prefetch opt-out must be preserved")
    port = profile.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        raise FlashNextBlocked("port must be an unprivileged TCP port")
    for key in ("model_entry", "server_executable", "cuda_runtime_path"):
        if not isinstance(profile.get(key), str) or not profile[key]:
            raise FlashNextBlocked(f"missing {key}")
    for name in ("startup_seconds", "smoke_total_seconds", "case_seconds", "max_tool_calls", "telemetry_interval_ms"):
        value = profile.get("limits", {}).get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise FlashNextBlocked(f"limits.{name} must be a positive integer")
    if profile["limits"]["smoke_total_seconds"] > 600 or profile["limits"]["case_seconds"] > 600:
        raise FlashNextBlocked("this campaign keeps the first smoke and each role/task within 600 seconds")
    if profile["limits"]["telemetry_interval_ms"] < 100:
        raise FlashNextBlocked("telemetry interval must be at least 100 ms")
    if profile["limits"]["max_tool_calls"] != 40:
        raise FlashNextBlocked("role campaign v1 declares a 40-call budget; shared L2 keeps its separate accepted 3/4/5 limits")


def cuda_runtime_dependencies(profile: Mapping[str, Any]) -> tuple[Path, ...]:
    root = Path(profile["cuda_runtime_path"])
    if not root.is_dir():
        raise FlashNextBlocked(f"pinned CUDA runtime directory is missing: {root}")
    paths = tuple(root / name for name in CUDA_RUNTIME_DLLS)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FlashNextBlocked(f"pinned CUDA runtime DLLs are missing: {missing}")
    return paths


def runtime_environment(profile: Mapping[str, Any]) -> dict[str, str]:
    """Recreate the verified Flash-Next runtime environment for every child process."""
    validate_profile(profile)
    cuda_root = str(Path(profile["cuda_runtime_path"]))
    cuda_runtime_dependencies(profile)
    env = {**os.environ, **profile["environment"]}
    inherited = os.environ.get("PATH", "")
    env["PATH"] = cuda_root if not inherited else cuda_root + os.pathsep + inherited
    return env


def validate_sources(repo_root: Path, campaign_root: Path) -> dict[str, Any]:
    """Verify frozen battery and vendored source bytes; do not repair drift."""
    lock = read_json(campaign_root / "accepted-battery-lock.json")
    if lock.get("base_commit") != BASE_COMMIT:
        raise FlashNextBlocked("accepted battery lock has a different V2 base")
    for item in lock["files"]:
        path = repo_root / item["path"]
        if not path.is_file() or file_digest(path) != item["sha256"]:
            raise FlashNextBlocked(f"accepted battery/source drift: {item['path']}")
    counts = {}
    for level in ("l0", "l1", "l2"):
        pack = read_json(repo_root / f"benchmark-packs/v2/shared-{level}-core-v1.json")
        counts[level.upper()] = len(pack["cases"])
        if any(c["repetitions"] != {"screen_trials": 1, "qualification_trials": 3} for c in pack["cases"]):
            raise FlashNextBlocked("accepted repetition policy changed")
    if counts != {"L0": 9, "L1": 5, "L2": 8}:
        raise FlashNextBlocked("accepted shared battery must contain 9 L0, 5 L1, 8 L2 cases")
    manifests = {}
    pins = {"local-model-bench": "fce91a7fa409aecd824a3fa1229724b0aab56812",
            "deepseek-lab": "e8bf69e664504fc54fbb94a00131b52e0a9c0de9"}
    for repository in ("local-model-bench", "deepseek-lab"):
        source_root = campaign_root / "sources" / repository
        path = source_root / "SOURCE_MANIFEST.json"
        manifest = read_json(path)
        if (manifest.get("source_repository") != f"floydtrey/{repository}"
                or manifest.get("source_commit") != pins[repository]):
            raise FlashNextBlocked(f"vendored source manifest has an incorrect source pin: {repository}")
        if not isinstance(manifest.get("files"), list) or not manifest["files"]:
            raise FlashNextBlocked(f"empty vendored source manifest: {repository}")
        declared = set()
        for item in manifest["files"]:
            relative = item.get("source_path", item.get("path"))
            if (not isinstance(relative, str) or relative.startswith(("/", "\\"))
                    or ".." in Path(relative).parts or "\\" in relative or ":" in relative
                    or relative in declared):
                raise FlashNextBlocked(f"invalid/duplicate source path: {relative!r}")
            declared.add(relative)
            local = source_root / relative
            if not local.is_file() or file_digest(local) != item["sha256"]:
                raise FlashNextBlocked(f"vendored source drift: {repository}/{relative}")
            raw = local.read_bytes()
            blob = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
            if (item.get("bytes") != len(raw) or item.get("source_git_blob") != blob
                    or item.get("source_repository") != f"floydtrey/{repository}"
                    or item.get("source_commit") != pins[repository]):
                raise FlashNextBlocked(f"source provenance mismatch: {repository}/{relative}")
        actual = {p.relative_to(source_root).as_posix() for p in source_root.rglob("*")
                  if p.is_file() and p.name != "SOURCE_MANIFEST.json" and "__pycache__" not in p.parts}
        if declared != actual:
            raise FlashNextBlocked(f"source manifest is incomplete: {repository}")
        manifests[repository] = sha256_json(manifest)
    behavior = []
    # Include all active V2 implementation bytes, including the new adapter and
    # role runner. Docs and disposable paths cannot invalidate a valid screen.
    for path in sorted((repo_root / "src/localbench/v2").glob("*.py")):
        behavior.append({"path": path.relative_to(repo_root).as_posix(), "sha256": file_digest(path)})
    for path in sorted((repo_root / "schemas/v2").glob("*.json")):
        behavior.append({"path": path.relative_to(repo_root).as_posix(), "sha256": file_digest(path)})
    for path in sorted(campaign_root.glob("*.json")):
        behavior.append({"path": path.relative_to(repo_root).as_posix(), "sha256": file_digest(path)})
    return {"battery_lock_sha256": sha256_json(lock), "role_source_manifests": manifests,
            "implementation_sha256": sha256_json(behavior), "shared_case_counts": counts}


def shard_paths(entry: Path) -> tuple[Path, ...]:
    match = re.fullmatch(r"(.+)-00001-of-(\d{5})\.gguf", entry.name)
    if not match or int(match.group(2)) != 3:
        raise FlashNextBlocked("Flash-Next model entry must be shard 00001-of-00003.gguf")
    paths = tuple(entry.with_name(f"{match.group(1)}-{i:05d}-of-00003.gguf") for i in range(1, 4))
    for path in paths:
        if not path.is_file():
            raise FlashNextBlocked(f"missing required model shard: {path}")
        with path.open("rb") as stream:
            if stream.read(4) != b"GGUF":
                raise FlashNextBlocked(f"model shard is not a GGUF file: {path}")
    return paths


def server_command(profile: Mapping[str, Any]) -> list[str]:
    validate_profile(profile)
    return [profile["server_executable"], "--model", profile["model_entry"],
            "--alias", profile["candidate_id"], "--ctx-size", str(profile["context_tokens"]),
            "--parallel", "1", "--host", profile["host"], "--port", str(profile["port"]),
            *profile["server_args"]]


def verify_version_revision(text: str, expected: str = FORK_REVISION) -> str:
    # llama.cpp --version often prints a short commit. Record the exact observed
    # abbreviation; do not pretend it independently proves the full build source.
    tokens = re.findall(r"(?<![0-9a-fA-F])[0-9a-fA-F]{7,40}(?![0-9a-fA-F])", text)
    matches = [token.lower() for token in tokens if expected.startswith(token.lower())]
    if not matches:
        raise FlashNextBlocked(f"llama-server --version does not identify pinned fork {expected}; inspect runtime-version evidence")
    return max(matches, key=len)


def preflight_identity(*, profile: Mapping[str, Any], repo_root: Path, campaign_root: Path,
                       output_dir: Path, progress: Callable[[str], None] = print) -> dict[str, Any]:
    from .llama_cpp_driver import LLAMA_CPP_ADAPTER_ID

    validate_profile(profile)
    sources = validate_sources(repo_root, campaign_root)
    executable = Path(profile["server_executable"])
    if not executable.is_file():
        raise FlashNextBlocked(f"runtime not present on this host: {executable}; run this command on the FlashNext Windows machine")
    shards = shard_paths(Path(profile["model_entry"]))
    raw_dir = output_dir / "runtime"
    raw_dir.mkdir(parents=True, exist_ok=True)
    env = runtime_environment(profile)
    progress("Capturing the pinned runtime version (no model load).")
    try:
        version = subprocess.run([str(executable), "--version"], capture_output=True, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FlashNextBlocked(f"runtime version command failed: {exc}") from exc
    write_bytes_once(raw_dir / "version.stdout.bin", version.stdout)
    write_bytes_once(raw_dir / "version.stderr.bin", version.stderr)
    version_text = (version.stdout + b"\n" + version.stderr).decode("utf-8", errors="replace")
    write_json_once(raw_dir / "version.json", {"argv": [str(executable), "--version"], "exit_code": version.returncode,
                    "stdout_sha256": hashlib.sha256(version.stdout).hexdigest(), "stderr_sha256": hashlib.sha256(version.stderr).hexdigest()})
    if version.returncode:
        raise FlashNextBlocked("runtime --version exited nonzero; preserved stdout/stderr")
    observed_revision = verify_version_revision(version_text)
    progress("Hashing all three model shards and the exact runtime installation.")
    artifacts = [{"file": p.name, "bytes": p.stat().st_size, "sha256": file_digest(p, progress)} for p in shards]
    binaries = [executable, *sorted(executable.parent.glob("*.dll")), *cuda_runtime_dependencies(profile)]
    installation = [{"file": p.name, "bytes": p.stat().st_size, "sha256": file_digest(p, progress)} for p in binaries]
    progress("Capturing two V2 host profiles and comparing stable facts.")
    probe = SystemHostProbe(target_path=Path(profile["model_entry"]).parent)
    host1 = collect_host_profile("flashnext-host-capture-1", probe=probe)
    host2 = collect_host_profile("flashnext-host-capture-2", probe=probe)
    store = EvidenceStore(output_dir / "evidence")
    store.persist_many((host1, host2))
    if host1.payload["facts_sha256"] != host2.payload["facts_sha256"]:
        raise FlashNextBlocked("BL-3 host captures disagree; compare their preserved stable facts before running models")
    runtime = runtime_profile(
        "flashnext-llama-cpp-runtime", runtime_kind="llama_cpp", version=observed_revision,
        build=FORK_REVISION,
        transport={"kind": "loopback_http", "base_uri": f"http://127.0.0.1:{profile['port']}",
                   "context_tokens": CONTEXT_TOKENS, "model_alias": "C01", "reasoning_mode": "auto",
                   "parallel_slots": 1, "launch_argv": server_command(profile),
                   "environment": {**profile["environment"], "PATH_prepend": profile["cuda_runtime_path"]}, "process_lifecycle": "owned_per_command",
                   "revision_verification": "binary-reported-abbreviation-plus-owner-supplied-full-pin"},
        executable={"path": str(executable), **installation[0]},
        installation_digest=sha256_json(installation),
        capabilities={"candidate_chat_endpoint": "/v1/chat/completions", "candidate_tool_transport": "native_structured",
                      "tool_execution": "forbidden", "qualification": "requires-v2-smoke"})
    model = model_identity(
        "flashnext-ud-iq3-xxs", family="Qwen3.8-Flash-Next", name="Qwen3.8-Flash-Next UD-IQ3_XXS",
        source={"kind": "local_gguf_shards", "entry": str(shards[0]), "artifacts": artifacts},
        artifact_digest=sha256_json(artifacts), provider_digest=None, parameter_count=None,
        quantization="UD-IQ3_XXS", precision=None, declared_context_tokens=CONTEXT_TOKENS)
    interface = execution_interface_identity(
        "flashnext-native-llama-cpp", runtime=runtime.reference, model=model.reference,
        backend_kind="llama_cpp", adapter_id=LLAMA_CPP_ADAPTER_ID,
        tool_transport_mode="model_aware_structured", parser_mode="model_aware",
        parser_id=f"llama-cpp-server-jinja-deepseek-{FORK_REVISION[:12]}",
        raw_interaction_contract="llama-cpp-raw-http-sidecars:v1",
        capabilities={"native_structured_tool_calls": "candidate-until-smoke", "plain_text_tool_fallback": False,
                      "tools_execute_only_through_lab": True, "server_reasoning": "auto"})
    store.persist_many((runtime, model, interface))
    fingerprint = {
        "campaign": CAMPAIGN_NAME, "profile_sha256": sha256_json(profile),
        "host_facts_sha256": host1.payload["facts_sha256"], "runtime_sha256": runtime.sha256,
        "model_sha256": model.sha256, "execution_interface_sha256": interface.sha256, **sources,
    }
    value = {"schema_version": "flashnext-preflight:v1", "status": "pass", "fingerprint": fingerprint,
             "fingerprint_sha256": sha256_json(fingerprint), "host_captures": [host1.reference.to_dict(), host2.reference.to_dict()],
             "foundation": {name: item.reference.to_dict() for name, item in
                            (("host", host1), ("runtime", runtime), ("model", model), ("interface", interface))},
             "model_artifacts": artifacts, "runtime_installation": installation,
             "model_started": False, "model_or_role_qualified": False}
    write_json_once(output_dir / "preflight.json", value)
    return {"host": host1, "runtime": runtime, "model": model, "interface": interface,
            "fingerprint": fingerprint, "store": store, "preflight": value}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class OwnedFlashNextServer:
    """Own only the process launched here and preserve its raw startup evidence."""

    def __init__(self, profile: Mapping[str, Any], output_dir: Path, *, progress=print):
        self.profile = profile
        self.output_dir = output_dir
        self.progress = progress
        self.process: subprocess.Popen | None = None
        self.started = None
        self.ready_seconds = None
        self.expired = False
        self._files = []
        self._timers: list[threading.Timer] = []
        self._stop_lock = threading.Lock()
        self._http_count = 0
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _get(self, path: str, *, required=True) -> Any:
        self._http_count += 1
        stem = f"get-{self._http_count:04d}-{path.strip('/').replace('/', '-') or 'root'}"
        request = urllib.request.Request(f"http://127.0.0.1:{self.profile['port']}{path}", headers={"Accept": "application/json"})
        status = None
        body = b""
        error = None
        try:
            with self._opener.open(request, timeout=2) as response:
                status, body = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, body = exc.code, exc.read()
            error = str(exc)
        except (OSError, urllib.error.URLError) as exc:
            error = str(exc)
        write_bytes_once(self.output_dir / f"{stem}.body.bin", body)
        write_json_once(self.output_dir / f"{stem}.json", {"method": "GET", "path": path, "http_status": status,
                        "error": error, "body_sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)})
        if status != 200:
            if required:
                raise FlashNextBlocked(f"runtime {path} request failed: HTTP {status}; raw evidence preserved")
            return None
        try:
            return json.loads(body)
        except (ValueError, UnicodeError) as exc:
            if required:
                raise FlashNextBlocked(f"runtime {path} returned malformed JSON") from exc
            return None

    def watchdog(self, seconds: float) -> threading.Timer:
        def expire():
            self.expired = True
            self.progress("Time budget reached; stopping only the campaign-owned Flash-Next server.")
            self.stop()
        timer = threading.Timer(max(0.01, seconds), expire)
        timer.daemon = True
        self._timers.append(timer)
        timer.start()
        return timer

    def start(self) -> "OwnedFlashNextServer":
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Do not attach to, replace, unload, or kill a pre-existing listener.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as check:
            try:
                check.bind(("127.0.0.1", self.profile["port"]))
            except OSError as exc:
                raise FlashNextBlocked(f"port {self.profile['port']} is already occupied; choose a free loopback port in the profile") from exc
        argv = server_command(self.profile)
        write_json_once(self.output_dir / "launch.json", {"argv": argv, "environment_overrides": {**self.profile["environment"], "PATH_prepend": self.profile["cuda_runtime_path"]},
                       "process_ownership": "created_here_only", "cold_kind": "new_process_os_file_cache_unknown"})
        self.started = time.monotonic()
        try:
            for name in ("server.stdout.log", "server.stderr.log"):
                self._files.append((self.output_dir / name).open("xb"))
            if self.expired:
                raise FlashNextBlocked("startup time budget expired before launch")
            self.process = subprocess.Popen(argv, stdout=self._files[0], stderr=self._files[1],
                                            env=runtime_environment(self.profile), stdin=subprocess.DEVNULL)
            write_json_once(self.output_dir / "process.json", {"pid": self.process.pid, "owned": True})
            self.progress(f"Loading C01 in the pinned fork (owned PID {self.process.pid}).")
            last_message = time.monotonic()
            while time.monotonic() - self.started < self.profile["limits"]["startup_seconds"]:
                if self.expired or self.process.poll() is not None:
                    raise FlashNextBlocked("Flash-Next server exited or hit its time budget during startup; inspect raw server logs")
                health = self._get("/health", required=False)
                if isinstance(health, dict) and health.get("status") == "ok":
                    break
                if time.monotonic() - last_message >= 15:
                    self.progress(f"Still loading C01: {time.monotonic() - self.started:.0f}s; server logs are being preserved.")
                    last_message = time.monotonic()
                time.sleep(0.5)
            else:
                raise FlashNextBlocked("Flash-Next startup exceeded its bounded deadline")
            if self.process.poll() is not None:
                raise FlashNextBlocked("owned server exited at readiness; refusing a foreign listener")
            models = self._get("/v1/models")
            if not isinstance(models, dict) or "C01" not in [x.get("id") for x in models.get("data", []) if isinstance(x, dict)]:
                raise FlashNextBlocked("runtime model list does not expose the requested C01 alias")
            props = self._get("/props")
            self._validate_props(props)
            self.ready_seconds = time.monotonic() - self.started
            self._get("/metrics", required=False)
            write_json_once(self.output_dir / "ready.json", {"process_start_to_ready_seconds": self.ready_seconds,
                            "cold_kind": "new_process_os_file_cache_unknown", "resident_after_ready": True,
                            "context_tokens": CONTEXT_TOKENS, "parallel_slots": 1, "model_alias": "C01",
                            "chat_template_sha256": hashlib.sha256(str(props.get("chat_template", "")).encode()).hexdigest(),
                            "chat_template_tool_use_sha256": hashlib.sha256(props["chat_template_tool_use"].encode()).hexdigest()
                            if isinstance(props.get("chat_template_tool_use"), str) else None})
            self.progress(f"C01 is ready after {self.ready_seconds:.1f}s; starting bounded inference.")
            return self
        except BaseException:
            self.stop()
            raise

    def _validate_props(self, props: Any) -> None:
        if not isinstance(props, dict):
            raise FlashNextBlocked("runtime /props is not an object")
        if props.get("total_slots") != 1:
            raise FlashNextBlocked("runtime did not confirm one slot; refusing a divided/unknown context")
        settings = props.get("default_generation_settings", {})
        observed = settings.get("n_ctx") if isinstance(settings, dict) else None
        if observed is None:
            observed = props.get("n_ctx")
        if observed is None:
            # Fork builds have exposed n_ctx in different /props locations. Raw
            # server logs are an alternative measured source, never a guess.
            log_text = "\n".join((self.output_dir / name).read_text(encoding="utf-8", errors="replace")
                                 for name in ("server.stdout.log", "server.stderr.log"))
            matches = re.findall(r"\bn_ctx(?:_per_seq)?\s*=\s*(\d+)\b", log_text)
            if matches and all(int(value) == CONTEXT_TOKENS for value in matches):
                observed = CONTEXT_TOKENS
        if observed != CONTEXT_TOKENS:
            raise FlashNextBlocked(f"runtime effective context is {observed!r}, expected {CONTEXT_TOKENS}; inspect /props and server logs")
        model_path = props.get("model_path")
        if model_path is not None:
            normalized = lambda value: str(value).replace("\\", "/").casefold()
            if normalized(model_path) != normalized(self.profile["model_entry"]):
                raise FlashNextBlocked("runtime /props model_path differs from the pinned model entry")
        if not isinstance(props.get("chat_template"), str) or not props["chat_template"]:
            raise FlashNextBlocked("runtime did not expose the active Jinja template; inspect parser/template support before scoring")

    def finish_metrics(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self._get("/metrics", required=False)

    def stop(self) -> None:
        with self._stop_lock:
            for timer in self._timers:
                timer.cancel()
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            for stream in self._files:
                if not stream.closed:
                    stream.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        try:
            self.finish_metrics()
        finally:
            for timer in self._timers:
                timer.cancel()
            self.stop()
