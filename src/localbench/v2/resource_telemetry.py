from __future__ import annotations

import csv
import ctypes
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from ..util import validate_id
from .contracts import EvidenceRef, SealedEvidence, seal_evidence


RESOURCE_TELEMETRY_VERSION = "benchmark-lab-resource-telemetry:v1"
SYSTEM_RESOURCE_PROBE_ID = "system-resource-probe:v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _nullable_float(value: str) -> float | None:
    text = value.strip()
    if not text or text.casefold() in {"n/a", "na", "[n/a]", "not supported"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _nullable_int(value: str) -> int | None:
    number = _nullable_float(value)
    if number is None:
        return None
    return int(number)


def _mib_to_bytes(value: str) -> int | None:
    amount = _nullable_float(value)
    if amount is None:
        return None
    return int(amount * 1024 * 1024)


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _maximum(values: Sequence[float]) -> float | None:
    return None if not values else max(values)


def _minimum(values: Sequence[float]) -> float | None:
    return None if not values else min(values)


def _round_metric(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def parse_nvidia_telemetry_csv(text: str) -> list[dict[str, Any]]:
    """Parse the stable no-header/nounits NVIDIA telemetry query used by the sampler."""

    gpus: list[dict[str, Any]] = []
    for row in csv.reader(line for line in text.splitlines() if line.strip()):
        if len(row) != 9:
            continue
        (
            index,
            uuid,
            name,
            utilization,
            memory_used,
            memory_total,
            temperature,
            power_draw,
            power_limit,
        ) = [item.strip() for item in row]
        parsed_index = _nullable_int(index)
        gpus.append(
            {
                "index": parsed_index,
                "uuid": uuid or None,
                "name": name or None,
                "utilization_percent": _nullable_float(utilization),
                "memory_used_bytes": _mib_to_bytes(memory_used),
                "memory_total_bytes": _mib_to_bytes(memory_total),
                "temperature_c": _nullable_float(temperature),
                "power_watts": _nullable_float(power_draw),
                "power_limit_watts": _nullable_float(power_limit),
            }
        )
    return gpus


class ResourceProbe(Protocol):
    probe_id: str

    def sample(self) -> Mapping[str, Any]: ...


class TelemetrySession(Protocol):
    def start(self) -> None: ...

    def stop(self) -> SealedEvidence: ...


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class SystemResourceProbe:
    """Best-effort dependency-free CPU/RAM/NVIDIA telemetry probe.

    Unsupported or unavailable measurements remain explicit null/empty evidence.
    Probe failures are observations only and never alter benchmark execution status.
    """

    probe_id = SYSTEM_RESOURCE_PROBE_ID

    def __init__(self, *, gpu_timeout_seconds: float = 2.0) -> None:
        if gpu_timeout_seconds <= 0:
            raise ValueError("gpu_timeout_seconds must be greater than zero")
        self.gpu_timeout_seconds = float(gpu_timeout_seconds)
        self._previous_cpu: tuple[int, int, int] | None = None

    def _windows_cpu_ticks(self) -> tuple[int, int, int] | None:
        if os.name != "nt":
            return None

        class FileTime(ctypes.Structure):
            _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

            def value(self) -> int:
                return (int(self.high) << 32) | int(self.low)

        idle = FileTime()
        kernel = FileTime()
        user = FileTime()
        try:
            ok = ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            )
        except (AttributeError, OSError):
            return None
        if not ok:
            return None
        return idle.value(), kernel.value(), user.value()

    def _linux_cpu_ticks(self) -> tuple[int, int, int] | None:
        if os.name == "nt":
            return None
        try:
            first = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError):
            return None
        fields = first.split()
        if not fields or fields[0] != "cpu" or len(fields) < 5:
            return None
        try:
            values = [int(item) for item in fields[1:]]
        except ValueError:
            return None
        user = values[0] + (values[1] if len(values) > 1 else 0)
        kernel = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return idle, kernel - user, user

    def _cpu(self) -> dict[str, Any]:
        current = self._windows_cpu_ticks() or self._linux_cpu_ticks()
        utilization: float | None = None
        if current is not None and self._previous_cpu is not None:
            idle_delta = current[0] - self._previous_cpu[0]
            kernel_delta = current[1] - self._previous_cpu[1]
            user_delta = current[2] - self._previous_cpu[2]
            total_delta = kernel_delta + user_delta
            if total_delta > 0 and 0 <= idle_delta <= total_delta:
                utilization = 100.0 * (total_delta - idle_delta) / total_delta
        if current is not None:
            self._previous_cpu = current
        return {"utilization_percent": _round_metric(utilization)}

    def _memory(self) -> dict[str, Any]:
        if os.name == "nt":
            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            try:
                ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            except (AttributeError, OSError):
                ok = 0
            if ok:
                total = int(status.ullTotalPhys)
                available = int(status.ullAvailPhys)
                return {
                    "total_bytes": total,
                    "available_bytes": available,
                    "used_bytes": max(0, total - available),
                }
        else:
            try:
                values: dict[str, int] = {}
                for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                    if ":" not in line:
                        continue
                    key, remainder = line.split(":", 1)
                    number = remainder.strip().split()[0]
                    values[key] = int(number) * 1024
                total = values.get("MemTotal")
                available = values.get("MemAvailable")
                if total is not None and available is not None:
                    return {
                        "total_bytes": total,
                        "available_bytes": available,
                        "used_bytes": max(0, total - available),
                    }
            except (OSError, ValueError, IndexError):
                pass
        return {"total_bytes": None, "available_bytes": None, "used_bytes": None}

    def _gpus(self) -> tuple[list[dict[str, Any]], str | None]:
        command = [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit",
            "--format=csv,noheader,nounits",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.gpu_timeout_seconds,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except FileNotFoundError:
            return [], "nvidia_smi_not_found"
        except subprocess.TimeoutExpired:
            return [], "nvidia_smi_timeout"
        except OSError as exc:
            return [], f"nvidia_smi_os_error:{type(exc).__name__}"
        if completed.returncode != 0:
            return [], f"nvidia_smi_exit:{completed.returncode}"
        gpus = parse_nvidia_telemetry_csv(completed.stdout)
        if not gpus:
            return [], "nvidia_smi_no_rows"
        return gpus, None

    def sample(self) -> Mapping[str, Any]:
        cpu = self._cpu()
        memory = self._memory()
        gpus, gpu_error = self._gpus()
        errors: list[str] = []
        if cpu["utilization_percent"] is None and self._previous_cpu is None:
            errors.append("cpu_unavailable")
        if memory["total_bytes"] is None:
            errors.append("memory_unavailable")
        if gpu_error is not None:
            errors.append(gpu_error)
        available_groups = int(self._previous_cpu is not None) + int(memory["total_bytes"] is not None) + int(bool(gpus))
        status = "ok" if not errors else ("partial" if available_groups else "unavailable")
        return {
            "probe_status": status,
            "probe_errors": errors,
            "cpu": cpu,
            "memory": memory,
            "gpus": gpus,
        }


def summarize_resource_samples(
    samples: Sequence[Mapping[str, Any]], *, sampling_interval_ms: int
) -> dict[str, Any]:
    cpu_values: list[float] = []
    used_values: list[float] = []
    available_values: list[float] = []
    probe_durations: list[float] = []
    failure_count = 0
    gpu_series: dict[str, list[tuple[float, Mapping[str, Any]]]] = {}

    for sample in samples:
        offset = sample.get("offset_ms")
        if not isinstance(offset, (int, float)):
            continue
        duration = sample.get("probe_duration_ms")
        if isinstance(duration, (int, float)):
            probe_durations.append(float(duration))
        if sample.get("probe_status") != "ok":
            failure_count += 1
        cpu = sample.get("cpu")
        if isinstance(cpu, Mapping) and isinstance(cpu.get("utilization_percent"), (int, float)):
            cpu_values.append(float(cpu["utilization_percent"]))
        memory = sample.get("memory")
        if isinstance(memory, Mapping):
            if isinstance(memory.get("used_bytes"), (int, float)):
                used_values.append(float(memory["used_bytes"]))
            if isinstance(memory.get("available_bytes"), (int, float)):
                available_values.append(float(memory["available_bytes"]))
        gpus = sample.get("gpus")
        if not isinstance(gpus, Sequence) or isinstance(gpus, (str, bytes, bytearray)):
            continue
        for gpu in gpus:
            if not isinstance(gpu, Mapping):
                continue
            identity = gpu.get("uuid") or f"index:{gpu.get('index')}"
            gpu_series.setdefault(str(identity), []).append((float(offset), gpu))

    gpu_summaries: list[dict[str, Any]] = []
    for identity, series in sorted(gpu_series.items()):
        utilization = [float(g["utilization_percent"]) for _, g in series if isinstance(g.get("utilization_percent"), (int, float))]
        memory_used = [float(g["memory_used_bytes"]) for _, g in series if isinstance(g.get("memory_used_bytes"), (int, float))]
        temperatures = [float(g["temperature_c"]) for _, g in series if isinstance(g.get("temperature_c"), (int, float))]
        powers = [(offset, float(g["power_watts"])) for offset, g in series if isinstance(g.get("power_watts"), (int, float))]
        energy_joules = 0.0
        energy_duration_ms = 0.0
        for (left_ms, left_w), (right_ms, right_w) in zip(powers, powers[1:]):
            delta_ms = max(0.0, right_ms - left_ms)
            energy_joules += ((left_w + right_w) / 2.0) * (delta_ms / 1000.0)
            energy_duration_ms += delta_ms
        first_gpu = series[0][1]
        gpu_summaries.append(
            {
                "identity": identity,
                "index": first_gpu.get("index"),
                "uuid": first_gpu.get("uuid"),
                "name": first_gpu.get("name"),
                "average_utilization_percent": _round_metric(_mean(utilization)),
                "peak_utilization_percent": _round_metric(_maximum(utilization)),
                "peak_memory_used_bytes": None if not memory_used else int(max(memory_used)),
                "peak_temperature_c": _round_metric(_maximum(temperatures)),
                "average_power_watts": _round_metric(_mean([value for _, value in powers])),
                "peak_power_watts": _round_metric(_maximum([value for _, value in powers])),
                "estimated_energy_joules": _round_metric(energy_joules) if len(powers) >= 2 else None,
                "observed_energy_duration_ms": _round_metric(energy_duration_ms) if len(powers) >= 2 else 0.0,
            }
        )

    offsets = [float(item["offset_ms"]) for item in samples if isinstance(item.get("offset_ms"), (int, float))]
    return {
        "sample_count": len(samples),
        "sampling_interval_ms": sampling_interval_ms,
        "observed_span_ms": _round_metric(max(offsets) - min(offsets)) if len(offsets) >= 2 else 0.0,
        "probe_non_ok_samples": failure_count,
        "average_probe_duration_ms": _round_metric(_mean(probe_durations)),
        "peak_probe_duration_ms": _round_metric(_maximum(probe_durations)),
        "cpu": {
            "average_utilization_percent": _round_metric(_mean(cpu_values)),
            "peak_utilization_percent": _round_metric(_maximum(cpu_values)),
        },
        "memory": {
            "peak_used_bytes": None if not used_values else int(max(used_values)),
            "minimum_available_bytes": None if not available_values else int(min(available_values)),
        },
        "gpus": gpu_summaries,
    }


def resource_telemetry_trace(
    logical_id: str,
    *,
    probe_id: str,
    sampling_interval_ms: int,
    case_id: str,
    trial: EvidenceRef,
    started_at: str,
    finished_at: str,
    samples: Sequence[Mapping[str, Any]],
) -> SealedEvidence:
    validate_id(logical_id, "logical_id")
    validate_id(case_id, "case_id")
    validate_id(probe_id.replace(":", "-"), "probe_id")
    if trial.record_type != "trial_identity":
        raise ValueError("trial must reference trial_identity")
    if not isinstance(sampling_interval_ms, int) or isinstance(sampling_interval_ms, bool) or sampling_interval_ms < 100:
        raise ValueError("sampling_interval_ms must be an integer >= 100")
    if not isinstance(started_at, str) or not started_at or not isinstance(finished_at, str) or not finished_at:
        raise ValueError("started_at and finished_at must be non-empty strings")
    normalized_samples = [dict(item) for item in samples]
    return seal_evidence(
        "resource_telemetry_trace",
        logical_id,
        {
            "telemetry_version": RESOURCE_TELEMETRY_VERSION,
            "probe_id": probe_id,
            "sampling_interval_ms": sampling_interval_ms,
            "case_id": case_id,
            "trial": trial.to_dict(),
            "started_at": started_at,
            "finished_at": finished_at,
            "samples": normalized_samples,
            "summary": summarize_resource_samples(
                normalized_samples, sampling_interval_ms=sampling_interval_ms
            ),
        },
    )


class ThreadedResourceTelemetrySession:
    def __init__(
        self,
        *,
        logical_id: str,
        case_id: str,
        trial: EvidenceRef,
        probe: ResourceProbe,
        sampling_interval_ms: int,
        wall_clock: Callable[[], str] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if sampling_interval_ms < 100:
            raise ValueError("sampling_interval_ms must be >= 100")
        self.logical_id = validate_id(logical_id, "logical_id")
        self.case_id = validate_id(case_id, "case_id")
        self.trial = trial
        self.probe = probe
        self.sampling_interval_ms = int(sampling_interval_ms)
        self.wall_clock = wall_clock
        self.monotonic = monotonic
        self._samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at: str | None = None
        self._start_monotonic: float | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("telemetry session already started")
        self._started_at = self.wall_clock()
        self._start_monotonic = self.monotonic()
        self._thread = threading.Thread(
            target=self._run,
            name=f"telemetry-{self.case_id}",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        assert self._start_monotonic is not None
        sequence = 0
        while not self._stop.is_set():
            sequence += 1
            probe_start = self.monotonic()
            captured_at = self.wall_clock()
            try:
                measured = dict(self.probe.sample())
            except Exception as exc:  # telemetry is observational and must not fail the run
                measured = {
                    "probe_status": "unavailable",
                    "probe_errors": [f"probe_exception:{type(exc).__name__}"],
                    "cpu": {"utilization_percent": None},
                    "memory": {"total_bytes": None, "available_bytes": None, "used_bytes": None},
                    "gpus": [],
                }
            probe_end = self.monotonic()
            self._samples.append(
                {
                    "sequence": sequence,
                    "captured_at": captured_at,
                    "offset_ms": round((probe_start - self._start_monotonic) * 1000.0, 3),
                    "probe_duration_ms": round((probe_end - probe_start) * 1000.0, 3),
                    **measured,
                }
            )
            elapsed = probe_end - probe_start
            remaining = max(0.0, self.sampling_interval_ms / 1000.0 - elapsed)
            if self._stop.wait(remaining):
                break

    def stop(self) -> SealedEvidence:
        if self._thread is None or self._started_at is None:
            raise RuntimeError("telemetry session was not started")
        self._stop.set()
        self._thread.join(timeout=max(3.0, self.sampling_interval_ms / 1000.0 + 2.5))
        finished_at = self.wall_clock()
        if self._thread.is_alive():
            self._samples.append(
                {
                    "sequence": len(self._samples) + 1,
                    "captured_at": finished_at,
                    "offset_ms": round((self.monotonic() - (self._start_monotonic or self.monotonic())) * 1000.0, 3),
                    "probe_duration_ms": 0.0,
                    "probe_status": "unavailable",
                    "probe_errors": ["sampler_thread_stop_timeout"],
                    "cpu": {"utilization_percent": None},
                    "memory": {"total_bytes": None, "available_bytes": None, "used_bytes": None},
                    "gpus": [],
                }
            )
        return resource_telemetry_trace(
            self.logical_id,
            probe_id=self.probe.probe_id,
            sampling_interval_ms=self.sampling_interval_ms,
            case_id=self.case_id,
            trial=self.trial,
            started_at=self._started_at,
            finished_at=finished_at,
            samples=self._samples,
        )


@dataclass(frozen=True)
class ResourceTelemetryBinding:
    probe_id: str
    sampling_interval_ms: int
    session_factory: Callable[[str, str, EvidenceRef], TelemetrySession]

    def __post_init__(self) -> None:
        if not isinstance(self.probe_id, str) or not self.probe_id:
            raise ValueError("probe_id must be a non-empty string")
        if not isinstance(self.sampling_interval_ms, int) or isinstance(self.sampling_interval_ms, bool) or self.sampling_interval_ms < 100:
            raise ValueError("sampling_interval_ms must be an integer >= 100")
        if not callable(self.session_factory):
            raise ValueError("session_factory must be callable")

    def descriptor(self) -> dict[str, Any]:
        return {
            "telemetry_version": RESOURCE_TELEMETRY_VERSION,
            "probe_id": self.probe_id,
            "sampling_interval_ms": self.sampling_interval_ms,
        }

    def create_session(
        self, logical_id: str, case_id: str, trial: EvidenceRef
    ) -> TelemetrySession:
        return self.session_factory(logical_id, case_id, trial)


def system_resource_telemetry_binding(
    *,
    sampling_interval_ms: int = 1000,
    gpu_timeout_seconds: float = 2.0,
) -> ResourceTelemetryBinding:
    if sampling_interval_ms < 100:
        raise ValueError("sampling_interval_ms must be >= 100")

    def factory(logical_id: str, case_id: str, trial: EvidenceRef) -> TelemetrySession:
        return ThreadedResourceTelemetrySession(
            logical_id=logical_id,
            case_id=case_id,
            trial=trial,
            probe=SystemResourceProbe(gpu_timeout_seconds=gpu_timeout_seconds),
            sampling_interval_ms=sampling_interval_ms,
        )

    return ResourceTelemetryBinding(
        probe_id=SYSTEM_RESOURCE_PROBE_ID,
        sampling_interval_ms=sampling_interval_ms,
        session_factory=factory,
    )
