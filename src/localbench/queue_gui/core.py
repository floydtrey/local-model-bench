"""Pure queue state, command construction, and persistence for the local GUI.

This module deliberately knows nothing about role packets or benchmark results.
Only the UI/controller thread should mutate a QueueState.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable
from uuid import UUID, uuid4


STATE_VERSION = 2

# Only these pre-existing benchmark entrypoints may be launched by the GUI.
BENCHMARKS = {
    "roles": ("Five-role battery", "run-all-roles.ps1"),
    "assistant-001": ("ASSISTANT-001 · Persistent Event Journal", "run-assistant-001.ps1"),
    "assistant-002": ("ASSISTANT-002 · Event Simulator and Replay", "run-assistant-002.ps1"),
}


def benchmark_tasks(repo_root: Path, benchmark: str) -> list[tuple[str, str]]:
    """Read each project's released task list; the GUI does not define case IDs."""
    if benchmark not in BENCHMARKS:
        raise ValueError("Unknown benchmark: " + str(benchmark))
    if benchmark == "roles":
        return []
    packet_path = Path(repo_root) / "project-benchmarks" / benchmark / "v1" / "packet.json"
    try:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read {benchmark} packet.json: {exc}") from exc
    if packet.get("packet_id") != benchmark + "-v1" or not isinstance(packet.get("tasks"), list):
        raise ValueError(f"Invalid {benchmark} packet.json metadata.")
    tasks = []
    for entry in packet["tasks"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not re.fullmatch(r"T[0-9]{2,4}", entry["id"]) or not isinstance(entry.get("title"), str):
            raise ValueError(f"Invalid task metadata in {benchmark} packet.")
        tasks.append((entry["id"], entry["title"]))
    if not tasks or len({id for id, _ in tasks}) != len(tasks):
        raise ValueError(f"Empty or duplicate task IDs in {benchmark} packet.")
    return tasks

DEFAULT_GOVERNOR_ROOT = r"C:\Projects\governor"
ITEM_STATUSES = {"Waiting", "Running", "Complete", "Failed", "Interrupted"}
QUEUE_STATUSES = {"Idle", "Running", "Paused", "Stopped", "Complete"}
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]*")
_MODEL_ID = re.compile(r"[0-9a-fA-F]{8,64}")
_RUN_DIR = re.compile(
    r"\s*(?:\[(?:\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2})[^\]\r\n]*\]\s*)?"
    r"RUN_DIR=(.*?)\s*"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _has_controls(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def validate_model(model: str) -> str:
    """Validate an exact Ollama tag without normalizing it or invoking a shell."""
    if not isinstance(model, str) or not _MODEL.fullmatch(model):
        raise ValueError("Model must be an Ollama tag without spaces or a leading '-'.")
    return model


def _optional_integer(value: Any, label: str) -> int | None:
    if value is None or isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value.strip()):
        value = int(value.strip())
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise ValueError(f"{label} must be a positive 32-bit integer.")
    return value


def _optional_number(value: Any, label: str, *, positive: bool) -> float | None:
    if value is None or isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            raise ValueError(f"{label} must be a finite number.") from None
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite number.")
    try:
        valid = math.isfinite(value) and (not positive or value > 0)
    except OverflowError:
        valid = False
    if not valid:
        qualifier = "finite positive number" if positive else "finite number"
        raise ValueError(f"{label} must be a {qualifier}.")
    return float(value)


@dataclass(frozen=True)
class BenchmarkSettings:
    phase: str = "screen"
    governor_root: str = DEFAULT_GOVERNOR_ROOT
    context_tokens: int | None = None
    max_output_tokens: int | None = None
    timeout_seconds: float | None = None
    keep_alive_seconds: float | None = None
    benchmark: str = "roles"
    through: str | None = None
    allow_host_execution: bool = False

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.benchmark not in BENCHMARKS:
            raise ValueError("Select an available benchmark.")
        if self.benchmark == "roles" and self.through is not None:
            raise ValueError("The five-role battery has no project task range.")
        if self.benchmark != "roles" and (not isinstance(self.through, str) or not re.fullmatch(r"T[0-9]{2,4}", self.through)):
            raise ValueError("Select a project task from the packet.")
        if type(self.allow_host_execution) is not bool:
            raise ValueError("Host-execution consent must be a boolean.")
        if self.benchmark == "roles" and self.allow_host_execution:
            raise ValueError("Host-execution consent applies only to project benchmarks.")
        if self.phase not in ("screen", "qualification"):
            raise ValueError("Phase must be 'screen' or 'qualification'.")
        if (not isinstance(self.governor_root, str)
                or not self.governor_root.strip() or _has_controls(self.governor_root)):
            raise ValueError("Governor root must be a nonempty path without control characters.")
        for value, label in ((self.context_tokens, "Context tokens"),
                             (self.max_output_tokens, "Max output tokens")):
            if value is not None:
                if type(value) is not int:
                    raise ValueError(f"{label} must be a positive 32-bit integer.")
                _optional_integer(value, label)
        for value, label, positive in (
            (self.timeout_seconds, "Timeout seconds", True),
            (self.keep_alive_seconds, "Keep-alive seconds", False),
        ):
            if value is not None:
                if type(value) not in (int, float):
                    raise ValueError(f"{label} must be a finite number.")
                _optional_number(value, label, positive=positive)

    @classmethod
    def from_fields(
        cls, phase: str = "screen", governor_root: str = DEFAULT_GOVERNOR_ROOT,
        context_tokens: Any = None, max_output_tokens: Any = None,
        timeout_seconds: Any = None, keep_alive_seconds: Any = None,
        benchmark: str = "roles", through: str | None = None,
        allow_host_execution: bool = False,
    ) -> BenchmarkSettings:
        """Convert entry-field strings; blank overrides use the CLI's defaults."""
        return cls(
            phase=phase,
            benchmark=benchmark, through=through, allow_host_execution=allow_host_execution,
            governor_root=governor_root.strip() if isinstance(governor_root, str) else governor_root,
            context_tokens=_optional_integer(context_tokens, "Context tokens"),
            max_output_tokens=_optional_integer(max_output_tokens, "Max output tokens"),
            timeout_seconds=_optional_number(timeout_seconds, "Timeout seconds", positive=True),
            keep_alive_seconds=_optional_number(keep_alive_seconds, "Keep-alive seconds", positive=False),
        )


def build_command(
    repo_root: Path, model: str, settings: BenchmarkSettings,
    powershell_exe: str = "powershell.exe",
) -> list[str]:
    """Build argv for the UTF-8 proxy, which forwards unchanged args to the CLI."""
    validate_model(model)
    settings.validate()
    root = Path(repo_root)
    command = [
        powershell_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(root / "tools" / "gui" / "run-queue-item.ps1"),
    ]
    if settings.benchmark == "roles":
        command.extend(("-Runtime", "ollama", "-Model", model, "-Phase", settings.phase,
                        "-GovernorRoot", settings.governor_root))
    else:
        task_ids = [task for task, _ in benchmark_tasks(root, settings.benchmark)]
        if settings.through not in task_ids:
            raise ValueError(f"Task {settings.through!r} is not in the selected project's packet.")
        if not settings.allow_host_execution:
            raise ValueError("Project benchmarks execute model-generated Python. Explicit host-execution consent is required.")
        command.extend(("-QueueBenchmark", settings.benchmark, "-Action", "run",
                        "-Model", model, "-Phase", settings.phase,
                        "-Through", settings.through, "-AllowHostExecution"))
    for flag, value in (
        ("-ContextTokens", settings.context_tokens),
        ("-MaxOutputTokens", settings.max_output_tokens),
        ("-TimeoutSeconds", settings.timeout_seconds),
        ("-KeepAliveSeconds", settings.keep_alive_seconds),
    ):
        if value is not None:
            command.extend((flag, str(value)))
    return command


def parse_ollama_list(text: str) -> list[str]:
    """Extract stable, unique tags from Ollama's NAME/ID/SIZE/MODIFIED table."""
    models: list[str] = []
    in_table = False
    for line in _ANSI.sub("", text).splitlines():
        columns = line.split()
        if columns[:4] == ["NAME", "ID", "SIZE", "MODIFIED"]:
            in_table = True
            continue
        if not in_table or len(columns) < 4 or not _MODEL_ID.fullmatch(columns[1]):
            continue
        try:
            model = validate_model(columns[0])
        except ValueError:
            continue
        if model not in models:
            models.append(model)
    return models


def parse_run_dir(line: str) -> str | None:
    """Read a standalone RUN_DIR marker, optionally after a bracketed timestamp."""
    match = _RUN_DIR.fullmatch(_ANSI.sub("", line).strip())
    if not match:
        return None
    value = match.group(1).strip()
    if value[:1] in ("'", '"'):
        if len(value) < 2 or value[-1] != value[0]:
            return None
        value = value[1:-1]
    return value if value and not _has_controls(value) else None


@dataclass
class QueueItem:
    model: str
    id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "Waiting"
    exit_code: int | None = None
    run_dir: str | None = None
    pid: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    settings: BenchmarkSettings = field(default_factory=BenchmarkSettings)


@dataclass
class QueueState:
    items: list[QueueItem] = field(default_factory=list)
    settings: BenchmarkSettings = field(default_factory=BenchmarkSettings)
    status: str = "Idle"
    pending_action: str | None = None

    @property
    def active(self) -> QueueItem | None:
        return next((item for item in self.items if item.status == "Running"), None)

    @property
    def waiting(self) -> list[QueueItem]:
        return [item for item in self.items if item.status == "Waiting"]

    def add_models(self, models: Iterable[str], settings: BenchmarkSettings | None = None) -> list[QueueItem]:
        if self.status == "Running" or self.active is not None:
            raise ValueError("The queue cannot be edited while it is running.")
        models = [validate_model(model) for model in models]
        selected = settings if settings is not None else self.settings
        selected.validate()
        known = {(item.model, item.settings) for item in self.items}
        added = []
        for model in models:
            if (model, selected) not in known:
                item = QueueItem(model=model, settings=selected)
                self.items.append(item)
                added.append(item)
                known.add((model, selected))
        if added and self.status == "Complete":
            self.status = "Idle"
        return added

    def start(self) -> None:
        """Resume only waiting entries; never recreate or retry an existing item."""
        if self.active is not None:
            raise ValueError("A benchmark is already running.")
        self.pending_action = None
        self.status = "Running" if self.waiting else "Complete"

    def start_next(self) -> QueueItem | None:
        """Claim at most one item. The controller performs the actual spawn."""
        if self.status != "Running" or self.active is not None:
            return None
        self._settle_boundary()
        if self.status != "Running":
            return None
        item = self.waiting[0]
        item.status = "Running"
        item.started_at = _utc_now()
        return item

    def finish(
        self, item_id: str, exit_code: int | None, error: str | None = None,
        interrupted: bool = False,
    ) -> None:
        item = self.active
        if item is None or item.id != item_id:
            raise ValueError("Completion does not match the active queue item.")
        if exit_code is not None and type(exit_code) is not int:
            raise ValueError("Exit code must be an integer or None.")
        if error is not None and not isinstance(error, str):
            raise ValueError("Error must be text or None.")
        item.exit_code = exit_code
        item.error = error or None
        item.finished_at = _utc_now()
        item.status = ("Interrupted" if interrupted else
                       "Complete" if exit_code == 0 and not error else "Failed")
        self._settle_boundary()

    def request_pause(self) -> None:
        if self.pending_action != "stop":
            self.pending_action = "pause"
        if self.active is None:
            self._settle_boundary()

    def request_stop(self) -> None:
        self.pending_action = "stop"
        if self.active is None:
            self._settle_boundary()

    def _settle_boundary(self) -> None:
        if not self.waiting:
            self.status = "Complete"
        elif self.pending_action == "stop":
            self.status = "Stopped"
        elif self.pending_action == "pause":
            self.status = "Paused"
        else:
            self.status = "Running"
        self.pending_action = None


def _exact_fields(value: Any, names: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != names:
        raise ValueError(f"Invalid queue state: {label} has missing or unknown fields.")


def _optional_text(value: Any, label: str, *, timestamp: bool = False) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value:
        raise ValueError(f"Invalid queue state: {label} must be nonempty text or null.")
    if label == "run_dir" and _has_controls(value):
        raise ValueError("Invalid queue state: run_dir contains control characters.")
    if timestamp:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        except ValueError:
            raise ValueError(f"Invalid queue state: {label} is not a timezone-aware timestamp.") from None


def _state_from_payload(payload: Any, *, recover: bool) -> QueueState:
    _exact_fields(payload, {"version", "items", "settings", "status", "pending_action"}, "document")
    if type(payload["version"]) is not int or payload["version"] not in (1, STATE_VERSION):
        raise ValueError("Invalid queue state: unsupported version.")
    if payload["version"] == 1:
        # V1 used one global configuration; copy its exact historical values into
        # every row before validating as V2. Never drop or restart previous runs.
        old = payload["settings"]
        _exact_fields(old, set(BenchmarkSettings.__dataclass_fields__) - {"benchmark", "through", "allow_host_execution"}, "legacy settings")
        legacy_settings = dict(old, benchmark="roles", through=None, allow_host_execution=False)
        payload = {**payload, "version": STATE_VERSION, "settings": legacy_settings,
                   "items": [dict(row, settings=dict(legacy_settings)) for row in payload["items"]]}
    _exact_fields(payload["settings"], set(BenchmarkSettings.__dataclass_fields__), "settings")
    settings = BenchmarkSettings(**payload["settings"])
    if not isinstance(payload["status"], str) or payload["status"] not in QUEUE_STATUSES:
        raise ValueError("Invalid queue state: unknown queue status.")
    if payload["pending_action"] not in (None, "pause", "stop"):
        raise ValueError("Invalid queue state: unknown pending action.")
    if not isinstance(payload["items"], list):
        raise ValueError("Invalid queue state: items must be a list.")
    items = []
    ids: set[str] = set()
    for raw in payload["items"]:
        _exact_fields(raw, set(QueueItem.__dataclass_fields__), "item")
        validate_model(raw["model"])
        _exact_fields(raw["settings"], set(BenchmarkSettings.__dataclass_fields__), "item settings")
        row_settings = BenchmarkSettings(**raw["settings"])
        try:
            if not isinstance(raw["id"], str) or str(UUID(raw["id"])) != raw["id"]:
                raise ValueError
        except ValueError:
            raise ValueError("Invalid queue state: item ID must be a UUID.") from None
        if raw["id"] in ids:
            raise ValueError("Invalid queue state: duplicate item ID.")
        ids.add(raw["id"])
        if not isinstance(raw["status"], str) or raw["status"] not in ITEM_STATUSES:
            raise ValueError("Invalid queue state: unknown item status.")
        for name in ("run_dir", "error", "started_at", "finished_at"):
            _optional_text(raw[name], name, timestamp=name.endswith("_at"))
        if raw["pid"] is not None and (type(raw["pid"]) is not int or raw["pid"] <= 0):
            raise ValueError("Invalid queue state: PID must be a positive integer or null.")
        if raw["exit_code"] is not None and type(raw["exit_code"]) is not int:
            raise ValueError("Invalid queue state: exit code must be an integer or null.")
        if raw["status"] == "Waiting":
            if any(raw[name] is not None for name in
                   ("started_at", "finished_at", "exit_code", "run_dir", "pid", "error")):
                raise ValueError("Invalid queue state: waiting item already has run evidence.")
        elif raw["status"] == "Running":
            if raw["started_at"] is None or any(raw[name] is not None for name in
                                              ("finished_at", "exit_code", "error")):
                raise ValueError("Invalid queue state: running item has inconsistent results.")
        else:
            if raw["started_at"] is None or raw["finished_at"] is None:
                raise ValueError("Invalid queue state: finished item needs start and finish timestamps.")
            if raw["status"] == "Complete" and (raw["exit_code"] != 0 or raw["error"] is not None):
                raise ValueError("Invalid queue state: complete item needs exit code zero and no error.")
            if raw["status"] == "Failed" and raw["exit_code"] == 0 and raw["error"] is None:
                raise ValueError("Invalid queue state: failed item needs a failure result.")
        items.append(QueueItem(**{**raw, "settings": row_settings}))
    state = QueueState(items=items, settings=settings, status=payload["status"],
                       pending_action=payload["pending_action"])
    running = [item for item in items if item.status == "Running"]
    if len(running) > 1 or running and state.status != "Running":
        raise ValueError("Invalid queue state: inconsistent active process state.")
    if state.pending_action is not None and not running:
        raise ValueError("Invalid queue state: pending action requires a running item.")
    if state.status == "Complete" and (running or state.waiting):
        raise ValueError("Invalid queue state: complete queue still has pending work.")
    if state.status == "Running" and not (running or state.waiting):
        raise ValueError("Invalid queue state: running queue has no pending work.")
    if recover and state.status == "Running":
        state.status = "Paused"
        state.pending_action = None
        for item in running:
            item.status = "Interrupted"
            item.finished_at = _utc_now()
            item.error = (
                "The previous GUI session ended during this run. "
                "Verify that its process has stopped before resuming the queue."
            )
    return state


def save_state(path: Path, state: QueueState) -> None:
    """Validate and atomically replace the local JSON state without saving logs/env."""
    path = Path(path)
    payload = {"version": STATE_VERSION, **asdict(state)}
    _state_from_payload(payload, recover=False)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
        ) as stream:
            temporary = stream.name
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def read_state_snapshot(path: Path, *, maximum_bytes=1_048_576) -> dict:
    """Passive bounded observation; never applies owner crash recovery or writes."""
    if type(maximum_bytes) is not int or maximum_bytes < 1:
        raise ValueError('Snapshot bound must be positive')
    with Path(path).open('rb') as stream:
        data = stream.read(maximum_bytes + 1)
    if len(data) > maximum_bytes:
        raise ValueError('Queue snapshot exceeds read bound')
    payload = json.loads(data)
    state = _state_from_payload(payload, recover=False)
    from hashlib import sha256
    return {'native_schema_version': payload['version'], 'content_sha256': sha256(data).hexdigest(),
            'native': {'version': STATE_VERSION, **asdict(state)}}


def load_state(path: Path) -> QueueState:
    """Load local state without starting work; crash-interrupted runs are not retried."""
    path = Path(path)
    if not path.exists():
        return QueueState()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Invalid queue state in {path.name}: {exc}") from exc
    return _state_from_payload(payload, recover=True)
