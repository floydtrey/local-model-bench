from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .contracts import EvidenceRef, SealedEvidence
from .resource_telemetry import ResourceTelemetryBinding, resource_telemetry_trace


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _unavailable_sample(error_code: str) -> dict:
    return {
        "sequence": 1,
        "captured_at": _utc_now(),
        "offset_ms": 0.0,
        "probe_duration_ms": 0.0,
        "probe_status": "unavailable",
        "probe_errors": [error_code],
        "cpu": {"utilization_percent": None},
        "memory": {
            "total_bytes": None,
            "available_bytes": None,
            "used_bytes": None,
        },
        "gpus": [],
    }


@dataclass
class SafeResourceTelemetryCapture:
    """Keep observational telemetry failures from changing benchmark execution.

    ``start`` and ``stop`` intentionally absorb telemetry implementation failures.
    A failed telemetry session becomes sealed unavailable telemetry evidence instead
    of a model/harness failure.
    """

    binding: ResourceTelemetryBinding
    logical_id: str
    case_id: str
    trial: EvidenceRef

    def __post_init__(self) -> None:
        self._session = None
        self._start_error: str | None = None
        self._started_at = _utc_now()

    def start(self) -> None:
        try:
            self._session = self.binding.create_session(
                self.logical_id, self.case_id, self.trial
            )
            self._session.start()
        except Exception as exc:  # telemetry must remain observational
            self._session = None
            self._start_error = f"telemetry_start:{type(exc).__name__}"

    def stop(self) -> SealedEvidence:
        if self._session is not None:
            try:
                record = self._session.stop()
                if (
                    not isinstance(record, SealedEvidence)
                    or record.record_type != "resource_telemetry_trace"
                ):
                    raise TypeError("telemetry session returned invalid evidence")
                if record.payload.get("trial") != self.trial.to_dict():
                    raise ValueError("telemetry trial binding mismatch")
                return record
            except Exception as exc:  # telemetry must remain observational
                error_code = f"telemetry_stop:{type(exc).__name__}"
        else:
            error_code = self._start_error or "telemetry_start:unknown"

        finished_at = _utc_now()
        return resource_telemetry_trace(
            self.logical_id,
            probe_id=self.binding.probe_id,
            sampling_interval_ms=self.binding.sampling_interval_ms,
            case_id=self.case_id,
            trial=self.trial,
            started_at=self._started_at,
            finished_at=finished_at,
            samples=[_unavailable_sample(error_code)],
        )
