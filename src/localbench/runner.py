from __future__ import annotations

import csv
import json
import os
import platform
import socket
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .models import BenchmarkCase, Suite
from .providers import Provider, ProviderError, make_provider
from .suites import normalized_suite
from .util import atomic_write_json, path_key, read_json, redact_config, utc_now, validate_id


TERMINAL_CASE_STATUSES = {"success", "error"}


class WallClockLimitReached(RuntimeError):
    """Raised when the configured whole-run wall-clock boundary is exhausted."""



def _host_metadata() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version,
        "logical_cpu_count": os.cpu_count(),
    }


def _result_root(config: dict[str, Any], config_path: Path) -> Path:
    value = config.get("result_root", "results")
    return (config_path.parent / value).resolve()


def _new_run_id(config_hash: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{config_hash[:8]}"


def _case_filename(sequence: int, suite: Suite, case: BenchmarkCase) -> str:
    return f"{sequence:04d}-{path_key(suite.id)}--{path_key(case.id)}.json"


def _error_record(exc: BaseException) -> dict[str, Any]:
    record: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc),
        "occurred_at": utc_now(),
    }
    if isinstance(exc, ProviderError):
        record["http_status"] = exc.status_code
        record["response_body"] = exc.body
    return record


def _case_messages(
    case: BenchmarkCase,
    conversations: dict[tuple[str, str], list[dict[str, str]]],
    suite_id: str,
) -> list[dict[str, str]]:
    current = [dict(message) for message in case.messages]
    if case.context_mode == "isolated":
        return current
    key = (suite_id, case.context_group or "")
    prior = [dict(message) for message in conversations.get(key, [])]
    if prior and current and current[0]["role"] == "system":
        previous_system = next((m for m in prior if m["role"] == "system"), None)
        if previous_system == current[0]:
            current = current[1:]
    return prior + current


def _restore_conversation(
    record: dict[str, Any],
    case: BenchmarkCase,
    suite_id: str,
    conversations: dict[tuple[str, str], list[dict[str, str]]],
) -> None:
    if case.context_mode != "preserve" or record.get("status") != "success":
        return
    messages = record.get("request", {}).get("messages")
    content = record.get("response", {}).get("content")
    if isinstance(messages, list) and isinstance(content, str):
        conversations[(suite_id, case.context_group or "")] = [
            *[dict(message) for message in messages],
            {"role": "assistant", "content": content},
        ]


def _throughput(output_tokens: int | None, generation_seconds: float | None, wall: float) -> float | None:
    denominator = generation_seconds if generation_seconds and generation_seconds > 0 else wall
    if output_tokens is None or denominator <= 0:
        return None
    return output_tokens / denominator


class BenchmarkRunner:
    def __init__(
        self,
        config: dict[str, Any],
        config_path: Path,
        config_hash: str,
        suites: list[Suite],
        *,
        run_id: str | None = None,
        resume_dir: Path | None = None,
        rerun_errors: bool = False,
        progress: Callable[[str], None] | None = None,
    ):
        self.config = config
        self.config_path = config_path.resolve()
        self.config_hash = config_hash
        self.suites = suites
        self.rerun_errors = rerun_errors
        self.progress = progress or (lambda message: None)
        if resume_dir:
            self.run_dir = resume_dir.resolve()
            self.run_id = self.run_dir.name
            self._validate_resume()
        else:
            self.run_id = validate_id(run_id, "run id") if run_id else _new_run_id(config_hash)
            self.run_dir = _result_root(config, self.config_path) / self.run_id
            if self.run_dir.exists():
                raise FileExistsError(
                    f"run directory already exists: {self.run_dir}; use --resume"
                )
        self.manifest_path = self.run_dir / "manifest.json"
        self.checkpoint_path = self.run_dir / "checkpoint.json"
        wall_clock = self.config.get("run", {}).get("wall_clock_seconds")
        self.wall_clock_seconds = float(wall_clock) if wall_clock is not None else None
        self.wall_clock_deadline: datetime | None = None

    def _validate_resume(self) -> None:
        manifest_path = self.run_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"resume directory has no manifest.json: {self.run_dir}")
        manifest = read_json(manifest_path)
        if manifest.get("config_sha256") != self.config_hash:
            raise ValueError("config changed since this run started; resume with the original config")
        current_inputs = [
            {"suite_id": suite.id, "source_sha256": suite.source_sha256}
            for suite in self.suites
        ]
        original_inputs = [
            {"suite_id": item["suite_id"], "source_sha256": item["source_sha256"]}
            for item in manifest.get("suites", [])
        ]
        if current_inputs != original_inputs:
            raise ValueError("suite inputs or their deterministic order changed; cannot safely resume")

    def _initial_manifest(self) -> dict[str, Any]:
        started = datetime.now(timezone.utc)
        self.wall_clock_deadline = (
            started + timedelta(seconds=self.wall_clock_seconds)
            if self.wall_clock_seconds is not None
            else None
        )
        return {
            "schema_version": 1,
            "harness_version": __version__,
            "run_id": self.run_id,
            "status": "running",
            "started_at": started.isoformat().replace("+00:00", "Z"),
            "finished_at": None,
            "last_updated_at": utc_now(),
            "wall_clock": {
                "limit_seconds": self.wall_clock_seconds,
                "deadline_at": (
                    self.wall_clock_deadline.isoformat().replace("+00:00", "Z")
                    if self.wall_clock_deadline is not None
                    else None
                ),
            },
            "config_path": str(self.config_path),
            "config_sha256": self.config_hash,
            "host": _host_metadata(),
            "ordering": {
                "models": [model["id"] for model in self.config["models"]],
                "suites": [suite.id for suite in self.suites],
                "policy": "models in config order; suites by resolved path; cases in file order",
            },
            "suites": [
                {
                    "suite_id": suite.id,
                    "name": suite.name,
                    "source_path": str(suite.source_path),
                    "source_sha256": suite.source_sha256,
                    "case_count": len(suite.cases),
                }
                for suite in self.suites
            ],
            "models": [
                {
                    "sequence": index,
                    "id": model["id"],
                    "provider": model["provider"],
                    "name": model["name"],
                }
                for index, model in enumerate(self.config["models"], 1)
            ],
        }

    def _prepare(self) -> dict[str, Any]:
        if self.manifest_path.exists():
            manifest = read_json(self.manifest_path)
            started_at = datetime.fromisoformat(str(manifest["started_at"]).replace("Z", "+00:00"))
            if self.wall_clock_seconds is not None:
                self.wall_clock_deadline = started_at + timedelta(seconds=self.wall_clock_seconds)
            else:
                self.wall_clock_deadline = None
            manifest["wall_clock"] = {
                "limit_seconds": self.wall_clock_seconds,
                "deadline_at": (
                    self.wall_clock_deadline.isoformat().replace("+00:00", "Z")
                    if self.wall_clock_deadline is not None
                    else None
                ),
            }
            manifest["status"] = "running"
            manifest["finished_at"] = None
            manifest["last_updated_at"] = utc_now()
            manifest.setdefault("resume_count", 0)
            manifest["resume_count"] += 1
        else:
            self.run_dir.mkdir(parents=True)
            (self.run_dir / "inputs").mkdir()
            atomic_write_json(
                self.run_dir / "inputs" / "config.json", redact_config(self.config)
            )
            for sequence, suite in enumerate(self.suites, 1):
                atomic_write_json(
                    self.run_dir
                    / "inputs"
                    / f"{sequence:03d}-{path_key(suite.id)}.normalized.json",
                    normalized_suite(suite),
                )
            manifest = self._initial_manifest()
        atomic_write_json(self.manifest_path, manifest)
        self._write_checkpoint("running", None)
        return manifest

    def _remaining_wall_seconds(self) -> float | None:
        if self.wall_clock_deadline is None:
            return None
        return (self.wall_clock_deadline - datetime.now(timezone.utc)).total_seconds()

    def _bounded_timeout(self, configured_timeout: float) -> float:
        remaining = self._remaining_wall_seconds()
        if remaining is None:
            return configured_timeout
        if remaining <= 0:
            raise WallClockLimitReached("whole-run wall-clock boundary reached")
        return min(configured_timeout, remaining)

    def _require_wall_clock(self) -> None:
        remaining = self._remaining_wall_seconds()
        if remaining is not None and remaining <= 0:
            raise WallClockLimitReached("whole-run wall-clock boundary reached")

    def run(self) -> Path:
        manifest = self._prepare()
        try:
            self._require_wall_clock()
            for model_sequence, model in enumerate(self.config["models"], 1):
                self._require_wall_clock()
                self._run_model(model_sequence, model)
            manifest["status"] = (
                "completed_with_errors" if self._has_case_errors() else "completed"
            )
        except WallClockLimitReached:
            manifest["status"] = "wall_clock_exhausted"
        except KeyboardInterrupt:
            manifest["status"] = "interrupted"
            raise
        except BaseException as exc:
            manifest["status"] = "failed"
            manifest["fatal_error"] = {
                **_error_record(exc),
                "traceback": "".join(traceback.format_exception(exc))[-16000:],
            }
            raise
        finally:
            manifest["last_updated_at"] = utc_now()
            if manifest["status"] != "running":
                manifest["finished_at"] = utc_now()
            atomic_write_json(self.manifest_path, manifest)
            self._write_summary()
            self._write_checkpoint(manifest["status"], None)
        return self.run_dir

    def _run_model(self, sequence: int, model: dict[str, Any]) -> None:
        provider_settings = self.config["providers"][model["provider"]]
        provider = make_provider(model["provider"], provider_settings)
        model_dir = self.run_dir / "models" / f"{sequence:03d}-{path_key(model['id'])}"
        cases_dir = model_dir / "cases"
        cases_dir.mkdir(parents=True, exist_ok=True)
        run_settings = self.config.get("run", {})
        timeout = float(run_settings.get("timeout_seconds", 600))
        self.progress(f"model {sequence}/{len(self.config['models'])}: {model['id']}")
        metadata_record: dict[str, Any] = {
            "schema_version": 1,
            "sequence": sequence,
            "id": model["id"],
            "provider": model["provider"],
            "provider_type": provider_settings["type"],
            "name": model["name"],
            "configured_options": model.get("options", {}),
            "base_url": provider_settings["base_url"],
            "captured_at": utc_now(),
        }
        try:
            metadata_record["provider_runtime_metadata"] = provider.runtime_metadata(self._bounded_timeout(timeout))
            metadata_record["model_runtime_metadata"] = provider.model_metadata(model["name"], self._bounded_timeout(timeout))
            metadata_record["installed"] = metadata_record["model_runtime_metadata"] is not None
        except BaseException as exc:
            metadata_record["installed"] = None
            metadata_record["metadata_error"] = _error_record(exc)
        atomic_write_json(model_dir / "model.json", metadata_record)

        conversations: dict[tuple[str, str], list[dict[str, str]]] = {}
        global_sequence = 0
        unload_record: dict[str, Any] = {"attempted": False}
        try:
            for suite in self.suites:
                for case in suite.cases:
                    self._require_wall_clock()
                    global_sequence += 1
                    case_path = cases_dir / _case_filename(global_sequence, suite, case)
                    if case_path.exists():
                        existing = read_json(case_path)
                        if existing.get("status") in TERMINAL_CASE_STATUSES and not (
                            self.rerun_errors and existing.get("status") == "error"
                        ):
                            _restore_conversation(existing, case, suite.id, conversations)
                            continue
                    self._checkpoint(sequence, model, suite, case, "running")
                    messages = _case_messages(case, conversations, suite.id)
                    result = self._execute_case(
                        provider, model, suite, case, global_sequence, messages
                    )
                    atomic_write_json(case_path, result)
                    _restore_conversation(result, case, suite.id, conversations)
                    self._checkpoint(sequence, model, suite, case, result["status"])
                    self.progress(f"  {suite.id}/{case.id}: {result['status']}")
        finally:
            should_unload = run_settings.get("unload_after_model", True) or (
                provider_settings["type"] == "llama_cpp"
            )
            if should_unload:
                unload_record["attempted"] = True
                try:
                    unload_record["response"] = provider.unload_model(model["name"], self._bounded_timeout(timeout))
                    unload_record["status"] = "success"
                except WallClockLimitReached:
                    unload_record["status"] = "skipped_wall_clock_exhausted"
                except BaseException as exc:
                    unload_record["status"] = "error"
                    unload_record["error"] = _error_record(exc)
            atomic_write_json(model_dir / "unload.json", unload_record)
            self._write_model_summary(model_dir)

    def _execute_case(
        self,
        provider: Provider,
        model: dict[str, Any],
        suite: Suite,
        case: BenchmarkCase,
        sequence: int,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        settings = self.config.get("run", {})
        retries = int(settings.get("retries", 1))
        retry_delay = float(settings.get("retry_delay_seconds", 2))
        timeout = float(settings.get("timeout_seconds", 600))
        options = dict(model.get("options", {}))
        options.update(case.options)
        attempts: list[dict[str, Any]] = []
        started = utc_now()
        for attempt_number in range(1, retries + 2):
            monotonic_start = time.monotonic()
            attempt: dict[str, Any] = {"number": attempt_number, "started_at": utc_now()}
            try:
                response = provider.chat(model["name"], messages, options, self._bounded_timeout(timeout))
                wall = time.monotonic() - monotonic_start
                attempt.update({"status": "success", "wall_seconds": wall})
                attempts.append(attempt)
                return {
                    "schema_version": 1,
                    "status": "success",
                    "sequence": sequence,
                    "suite_id": suite.id,
                    "case_id": case.id,
                    "tags": case.tags,
                    "case_metadata": case.metadata,
                    "context": {"mode": case.context_mode, "group": case.context_group},
                    "model": {
                        "id": model["id"],
                        "name": model["name"],
                        "provider": model["provider"],
                    },
                    "request": {"messages": messages, "options": options},
                    "response": {
                        "content": response.content,
                        "finish_reason": response.finish_reason,
                        "raw": response.raw,
                    },
                    "tokens": {
                        "prompt": response.prompt_tokens,
                        "output": response.output_tokens,
                        "total": response.total_tokens,
                    },
                    "timing": {
                        "wall_seconds": wall,
                        "provider_total_seconds": response.provider_total_seconds,
                        "load_seconds": response.load_seconds,
                        "prompt_eval_seconds": response.prompt_eval_seconds,
                        "generation_seconds": response.generation_seconds,
                        "output_tokens_per_second": _throughput(
                            response.output_tokens, response.generation_seconds, wall
                        ),
                    },
                    "attempts": attempts,
                    "started_at": started,
                    "finished_at": utc_now(),
                }
            except WallClockLimitReached:
                raise
            except KeyboardInterrupt:
                raise
            except BaseException as exc:
                wall = time.monotonic() - monotonic_start
                attempt.update(
                    {"status": "error", "wall_seconds": wall, "error": _error_record(exc)}
                )
                attempts.append(attempt)
                if attempt_number <= retries:
                    remaining = self._remaining_wall_seconds()
                    if remaining is not None and remaining <= 0:
                        raise WallClockLimitReached("whole-run wall-clock boundary reached")
                    sleep_seconds = retry_delay if remaining is None else min(retry_delay, max(0.0, remaining))
                    time.sleep(sleep_seconds)
        return {
            "schema_version": 1,
            "status": "error",
            "sequence": sequence,
            "suite_id": suite.id,
            "case_id": case.id,
            "tags": case.tags,
            "case_metadata": case.metadata,
            "context": {"mode": case.context_mode, "group": case.context_group},
            "model": {
                "id": model["id"],
                "name": model["name"],
                "provider": model["provider"],
            },
            "request": {"messages": messages, "options": options},
            "response": None,
            "tokens": {"prompt": None, "output": None, "total": None},
            "timing": {"wall_seconds": sum(item["wall_seconds"] for item in attempts)},
            "attempts": attempts,
            "error": attempts[-1]["error"],
            "started_at": started,
            "finished_at": utc_now(),
        }

    def _checkpoint(
        self,
        model_sequence: int,
        model: dict[str, Any],
        suite: Suite,
        case: BenchmarkCase,
        status: str,
    ) -> None:
        current = {
            "model_sequence": model_sequence,
            "model_id": model["id"],
            "suite_id": suite.id,
            "case_id": case.id,
        }
        if status == "running":
            started = datetime.now(timezone.utc)
            current["started_at"] = started.isoformat().replace("+00:00", "Z")
        self._write_checkpoint(status, current)

    def _write_checkpoint(
        self, status: str, current: dict[str, Any] | None
    ) -> None:
        total = len(self.config["models"]) * sum(
            len(suite.cases) for suite in self.suites
        )
        completed = len(self._case_files())
        percent = round((completed / total) * 100, 2) if total else 100.0
        record: dict[str, Any] = {
            "schema_version": 1,
            "run_id": self.run_id,
            "last_updated_at": utc_now(),
            "status": status,
            "wall_clock": {
                "limit_seconds": self.wall_clock_seconds,
                "deadline_at": (
                    self.wall_clock_deadline.isoformat().replace("+00:00", "Z")
                    if self.wall_clock_deadline is not None
                    else None
                ),
                "remaining_seconds": (
                    max(0.0, self._remaining_wall_seconds())
                    if self._remaining_wall_seconds() is not None
                    else None
                ),
            },
            "progress": {
                "completed": completed,
                "total": total,
                "percent": percent,
            },
            "current": current,
        }
        if current:
            record.update(current)
        atomic_write_json(self.checkpoint_path, record)

    def _case_files(self, model_dir: Path | None = None) -> list[Path]:
        root = model_dir if model_dir else self.run_dir / "models"
        return sorted(root.glob("*/cases/*.json") if model_dir is None else root.glob("cases/*.json"))

    def _has_case_errors(self) -> bool:
        return any(read_json(path).get("status") == "error" for path in self._case_files())

    def _write_model_summary(self, model_dir: Path) -> None:
        records = [read_json(path) for path in self._case_files(model_dir)]
        successful = [item for item in records if item.get("status") == "success"]
        summary = {
            "schema_version": 1,
            "case_count": len(records),
            "success_count": len(successful),
            "error_count": sum(item.get("status") == "error" for item in records),
            "total_wall_seconds": sum(
                float(item.get("timing", {}).get("wall_seconds") or 0) for item in records
            ),
            "total_prompt_tokens": sum(
                int(item.get("tokens", {}).get("prompt") or 0) for item in successful
            ),
            "total_output_tokens": sum(
                int(item.get("tokens", {}).get("output") or 0) for item in successful
            ),
            "updated_at": utc_now(),
        }
        atomic_write_json(model_dir / "summary.json", summary)

    def _write_summary(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        fields = [
            "model_id",
            "model_name",
            "provider",
            "sequence",
            "suite_id",
            "case_id",
            "status",
            "context_mode",
            "context_group",
            "wall_seconds",
            "prompt_tokens",
            "output_tokens",
            "total_tokens",
            "output_tokens_per_second",
            "attempt_count",
            "error_type",
            "error_message",
        ]
        rows: list[dict[str, Any]] = []
        for path in self._case_files():
            item = read_json(path)
            rows.append(
                {
                    "model_id": item.get("model", {}).get("id"),
                    "model_name": item.get("model", {}).get("name"),
                    "provider": item.get("model", {}).get("provider"),
                    "sequence": item.get("sequence"),
                    "suite_id": item.get("suite_id"),
                    "case_id": item.get("case_id"),
                    "status": item.get("status"),
                    "context_mode": item.get("context", {}).get("mode"),
                    "context_group": item.get("context", {}).get("group"),
                    "wall_seconds": item.get("timing", {}).get("wall_seconds"),
                    "prompt_tokens": item.get("tokens", {}).get("prompt"),
                    "output_tokens": item.get("tokens", {}).get("output"),
                    "total_tokens": item.get("tokens", {}).get("total"),
                    "output_tokens_per_second": item.get("timing", {}).get(
                        "output_tokens_per_second"
                    ),
                    "attempt_count": len(item.get("attempts", [])),
                    "error_type": item.get("error", {}).get("type"),
                    "error_message": item.get("error", {}).get("message"),
                }
            )
        temp_path = self.run_dir / ".summary.csv.tmp"
        with temp_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, self.run_dir / "summary.csv")
