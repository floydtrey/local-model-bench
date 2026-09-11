from __future__ import annotations

import unittest

from localbench.v2.host import (
    _coerce_json_objects,
    _parse_cuda_version,
    _parse_nvidia_gpu_csv,
    _parse_nvcc_version,
    _parse_power_scheme,
    collect_host_profile,
)


class FakeProbe:
    def __init__(self, *, available_bytes: int = 32, free_bytes: int = 400):
        self.available_bytes = available_bytes
        self.free_bytes = free_bytes

    def os_info(self):
        return {
            "system": "Windows",
            "release": "11",
            "version": "test-build",
            "edition": "Professional",
            "machine": "AMD64",
        }

    def cpu_info(self):
        return {"model": "Test CPU", "physical_cores": 8, "logical_cores": 16}

    def memory_info(self):
        return {"installed_bytes": 64, "available_bytes": self.available_bytes}

    def gpu_info(self):
        return [
            {
                "name": "Test GPU",
                "vram_bytes": 16,
                "driver_version": "1.2.3",
                "pci_bus_id": "00000000:01:00.0",
                "probe_source": "fake",
            }
        ]

    def storage_info(self):
        return [{"volume": "C:", "total_bytes": 1000, "free_bytes": self.free_bytes}]

    def python_info(self):
        return {
            "implementation": "CPython",
            "version": "3.12.0",
            "compiler": "test",
            "architecture": "64bit",
        }

    def compute_runtime_info(self):
        return [
            {
                "kind": "nvidia-driver-cuda-capability",
                "version": "12.8",
                "probe_source": "fake",
            }
        ]

    def power_thermal_info(self):
        return {
            "active_power_scheme_guid": "00000000-0000-0000-0000-000000000000",
            "active_power_scheme_name": "Balanced",
            "thermal_state": None,
        }


class HostCollectorTests(unittest.TestCase):
    def test_injected_probe_builds_sealed_profile_without_runtime_or_model(self):
        profile = collect_host_profile(
            "test-host",
            probe=FakeProbe(),
            captured_at="2026-09-11T00:00:00Z",
        )

        self.assertEqual(profile.record_type, "host_profile")
        self.assertEqual(profile.payload["cpu"]["model"], "Test CPU")
        self.assertEqual(profile.payload["gpus"][0]["vram_bytes"], 16)
        self.assertEqual(
            profile.payload["compute_runtimes"][0]["kind"],
            "nvidia-driver-cuda-capability",
        )
        self.assertEqual(len(profile.payload["facts_sha256"]), 64)

    def test_volatile_capacity_changes_observation_but_not_host_fingerprint(self):
        first = collect_host_profile(
            "test-host",
            probe=FakeProbe(available_bytes=40, free_bytes=400),
            captured_at="2026-09-11T00:00:00Z",
        )
        second = collect_host_profile(
            "test-host",
            probe=FakeProbe(available_bytes=10, free_bytes=200),
            captured_at="2026-09-11T01:00:00Z",
        )

        self.assertEqual(first.payload["facts_sha256"], second.payload["facts_sha256"])
        self.assertNotEqual(first.sha256, second.sha256)
        self.assertNotEqual(
            first.payload["memory"]["available_bytes"],
            second.payload["memory"]["available_bytes"],
        )

    def test_nvidia_csv_parser_converts_mib_to_bytes(self):
        parsed = _parse_nvidia_gpu_csv(
            "NVIDIA Test GPU, 16384, 999.1, 00000000:01:00.0\n"
        )

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], "NVIDIA Test GPU")
        self.assertEqual(parsed[0]["vram_bytes"], 16384 * 1024 * 1024)
        self.assertEqual(parsed[0]["driver_version"], "999.1")

    def test_malformed_nvidia_rows_are_bounded_unknowns(self):
        parsed = _parse_nvidia_gpu_csv(
            "bad-row\nNVIDIA Test GPU, unknown, 999.1, 00000000:01:00.0\n"
        )

        self.assertEqual(len(parsed), 1)
        self.assertIsNone(parsed[0]["vram_bytes"])

    def test_compute_runtime_parsers_do_not_guess(self):
        self.assertEqual(_parse_cuda_version("CUDA Version: 12.8"), "12.8")
        self.assertEqual(_parse_cuda_version("CUDA UMD Version: 13.4"), "13.4")
        self.assertEqual(_parse_nvcc_version("Cuda compilation tools, release 12.6, V12.6.85"), "12.6")
        self.assertIsNone(_parse_cuda_version("driver present but version omitted"))
        self.assertIsNone(_parse_nvcc_version("nvcc information unavailable"))

    def test_power_scheme_parser(self):
        parsed = _parse_power_scheme(
            "Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)"
        )

        self.assertEqual(parsed["active_power_scheme_name"], "Balanced")
        self.assertEqual(
            parsed["active_power_scheme_guid"],
            "381b4222-f694-41f0-9685-ff5bb260df2e",
        )
        self.assertIsNone(parsed["thermal_state"])
        self.assertIsNone(_parse_power_scheme("unrecognized output"))

    def test_powershell_json_normalizer_accepts_single_or_array(self):
        self.assertEqual(_coerce_json_objects('{"Name":"A"}'), [{"Name": "A"}])
        self.assertEqual(
            _coerce_json_objects('[{"Name":"A"},{"Name":"B"}]'),
            [{"Name": "A"}, {"Name": "B"}],
        )
        self.assertEqual(_coerce_json_objects("not-json"), [])


if __name__ == "__main__":
    unittest.main()
