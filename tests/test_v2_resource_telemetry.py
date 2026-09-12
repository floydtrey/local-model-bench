from __future__ import annotations

import unittest

from localbench.v2.contracts import EvidenceRef, SealedEvidence
from localbench.v2.resource_telemetry import (
    RESOURCE_TELEMETRY_VERSION,
    ResourceTelemetryBinding,
    parse_nvidia_telemetry_csv,
    resource_telemetry_trace,
    summarize_resource_samples,
)


TRIAL = EvidenceRef("trial_identity", "trial-test", "a" * 64)


def sample(
    *,
    sequence: int,
    offset_ms: float,
    cpu: float | None,
    memory_used: int | None,
    memory_available: int | None,
    gpu_utilization: float | None,
    gpu_memory: int | None,
    temperature: float | None,
    power: float | None,
    status: str = "ok",
):
    return {
        "sequence": sequence,
        "captured_at": f"2026-09-12T00:00:0{sequence}Z",
        "offset_ms": offset_ms,
        "probe_duration_ms": 5.0 + sequence,
        "probe_status": status,
        "probe_errors": [] if status == "ok" else ["synthetic"],
        "cpu": {"utilization_percent": cpu},
        "memory": {
            "total_bytes": 16_000,
            "available_bytes": memory_available,
            "used_bytes": memory_used,
        },
        "gpus": [
            {
                "index": 0,
                "uuid": "GPU-test",
                "name": "Synthetic GPU",
                "utilization_percent": gpu_utilization,
                "memory_used_bytes": gpu_memory,
                "memory_total_bytes": 12_000,
                "temperature_c": temperature,
                "power_watts": power,
                "power_limit_watts": 250.0,
            }
        ],
    }


class ResourceTelemetryTests(unittest.TestCase):
    def test_parse_nvidia_csv_preserves_unknown_values(self):
        parsed = parse_nvidia_telemetry_csv(
            "0, GPU-abc, Test GPU, 91, 1024, 12288, 67, 201.5, 250.0\n"
            "1, GPU-def, Other GPU, N/A, 512, 8192, N/A, N/A, 200.0\n"
        )

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["index"], 0)
        self.assertEqual(parsed[0]["memory_used_bytes"], 1024 * 1024 * 1024)
        self.assertEqual(parsed[0]["power_watts"], 201.5)
        self.assertIsNone(parsed[1]["utilization_percent"])
        self.assertIsNone(parsed[1]["temperature_c"])
        self.assertIsNone(parsed[1]["power_watts"])

    def test_summary_reports_capacity_and_integrates_observed_gpu_energy(self):
        samples = [
            sample(
                sequence=1,
                offset_ms=0.0,
                cpu=25.0,
                memory_used=4_000,
                memory_available=12_000,
                gpu_utilization=50.0,
                gpu_memory=2_000,
                temperature=60.0,
                power=100.0,
            ),
            sample(
                sequence=2,
                offset_ms=1000.0,
                cpu=75.0,
                memory_used=6_000,
                memory_available=10_000,
                gpu_utilization=100.0,
                gpu_memory=5_000,
                temperature=70.0,
                power=200.0,
                status="partial",
            ),
        ]

        summary = summarize_resource_samples(samples, sampling_interval_ms=1000)

        self.assertEqual(summary["sample_count"], 2)
        self.assertEqual(summary["probe_non_ok_samples"], 1)
        self.assertEqual(summary["cpu"]["average_utilization_percent"], 50.0)
        self.assertEqual(summary["cpu"]["peak_utilization_percent"], 75.0)
        self.assertEqual(summary["memory"]["peak_used_bytes"], 6_000)
        self.assertEqual(summary["memory"]["minimum_available_bytes"], 10_000)
        gpu = summary["gpus"][0]
        self.assertEqual(gpu["average_utilization_percent"], 75.0)
        self.assertEqual(gpu["peak_utilization_percent"], 100.0)
        self.assertEqual(gpu["peak_memory_used_bytes"], 5_000)
        self.assertEqual(gpu["peak_temperature_c"], 70.0)
        self.assertEqual(gpu["average_power_watts"], 150.0)
        self.assertEqual(gpu["peak_power_watts"], 200.0)
        self.assertEqual(gpu["estimated_energy_joules"], 150.0)
        self.assertEqual(gpu["observed_energy_duration_ms"], 1000.0)

    def test_trace_is_sealed_and_binds_trial_and_summary(self):
        samples = [
            sample(
                sequence=1,
                offset_ms=0.0,
                cpu=None,
                memory_used=4_000,
                memory_available=12_000,
                gpu_utilization=90.0,
                gpu_memory=2_000,
                temperature=61.0,
                power=125.0,
            )
        ]

        trace = resource_telemetry_trace(
            "telemetry-trial-test",
            probe_id="fake-probe:v1",
            sampling_interval_ms=1000,
            case_id="case-a",
            trial=TRIAL,
            started_at="2026-09-12T00:00:00Z",
            finished_at="2026-09-12T00:00:01Z",
            samples=samples,
        )

        self.assertEqual(trace.record_type, "resource_telemetry_trace")
        self.assertEqual(trace.payload["telemetry_version"], RESOURCE_TELEMETRY_VERSION)
        self.assertEqual(trace.payload["trial"], TRIAL.to_dict())
        self.assertEqual(trace.payload["summary"]["sample_count"], 1)
        self.assertEqual(SealedEvidence.from_dict(trace.to_dict()), trace)

    def test_binding_descriptor_is_data_only_and_stable(self):
        class FakeSession:
            def start(self):
                pass

            def stop(self):
                raise AssertionError("not used")

        binding = ResourceTelemetryBinding(
            probe_id="fake-probe:v1",
            sampling_interval_ms=500,
            session_factory=lambda logical_id, case_id, trial: FakeSession(),
        )

        self.assertEqual(
            binding.descriptor(),
            {
                "telemetry_version": RESOURCE_TELEMETRY_VERSION,
                "probe_id": "fake-probe:v1",
                "sampling_interval_ms": 500,
            },
        )
        self.assertIsInstance(
            binding.create_session("telemetry-a", "case-a", TRIAL), FakeSession
        )

    def test_invalid_trial_type_is_rejected(self):
        bad = EvidenceRef("host_profile", "host-a", "b" * 64)
        with self.assertRaisesRegex(ValueError, "trial_identity"):
            resource_telemetry_trace(
                "telemetry-bad",
                probe_id="fake-probe:v1",
                sampling_interval_ms=1000,
                case_id="case-a",
                trial=bad,
                started_at="2026-09-12T00:00:00Z",
                finished_at="2026-09-12T00:00:01Z",
                samples=[],
            )


if __name__ == "__main__":
    unittest.main()
