from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from ..util import atomic_write_json
from .contracts import SealedEvidence
from .records import host_profile


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], float], CommandResult]


def _run_command(args: Sequence[str], timeout_seconds: float) -> CommandResult:
    try:
        completed = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CommandResult(-1, "", str(exc))
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_json_objects(text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _parse_nvidia_gpu_csv(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in csv.reader(line for line in text.splitlines() if line.strip()):
        if len(row) != 4:
            continue
        name, memory_mib, driver, pci_bus = [item.strip() for item in row]
        try:
            vram_bytes = int(memory_mib) * 1024 * 1024
        except ValueError:
            vram_bytes = None
        rows.append(
            {
                "name": name or None,
                "vram_bytes": vram_bytes,
                "driver_version": driver or None,
                "pci_bus_id": pci_bus or None,
                "probe_source": "nvidia-smi",
            }
        )
    return rows


def _parse_cuda_version(text: str) -> str | None:
    match = re.search(r"CUDA(?:\s+UMD)?\s+Version:\s*([0-9.]+)", text, re.IGNORECASE)
    return match.group(1) if match else None


def _parse_nvcc_version(text: str) -> str | None:
    match = re.search(r"release\s+([0-9.]+)", text, re.IGNORECASE)
    return match.group(1) if match else None


def _parse_power_scheme(text: str) -> dict[str, Any] | None:
    match = re.search(
        r"Power Scheme GUID:\s*([0-9A-Fa-f-]+)\s*\((.*?)\)", text
    )
    if not match:
        return None
    return {
        "active_power_scheme_guid": match.group(1).lower(),
        "active_power_scheme_name": match.group(2).strip() or None,
        "thermal_state": None,
    }


class HostProbe(Protocol):
    def os_info(self) -> dict[str, Any]: ...

    def cpu_info(self) -> dict[str, Any]: ...

    def memory_info(self) -> dict[str, Any]: ...

    def gpu_info(self) -> list[dict[str, Any]]: ...

    def storage_info(self) -> list[dict[str, Any]]: ...

    def python_info(self) -> dict[str, Any]: ...

    def compute_runtime_info(self) -> list[dict[str, Any]]: ...

    def power_thermal_info(self) -> dict[str, Any] | None: ...


class SystemHostProbe:
    """Best-effort host observation using only the Python standard library.

    Missing tools or unsupported metrics are represented as null/empty evidence;
    probe failures do not get replaced with guessed hardware facts.
    """

    def __init__(
        self,
        *,
        target_path: Path | None = None,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.target_path = (target_path or Path.cwd()).resolve()
        self._command = command_runner or _run_command

    def _powershell_json(self, script: str) -> list[dict[str, Any]]:
        if os.name != "nt":
            return []
        result = self._command(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            10,
        )
        if result.returncode != 0:
            return []
        return _coerce_json_objects(result.stdout)

    def os_info(self) -> dict[str, Any]:
        edition = None
        version = None
        if os.name == "nt":
            try:
                edition = platform.win32_edition()
            except (AttributeError, OSError):
                edition = None
            try:
                version = platform.win32_ver()[1] or None
            except OSError:
                version = None
        return {
            "system": platform.system() or None,
            "release": platform.release() or None,
            "version": platform.version() or version,
            "edition": edition,
            "machine": platform.machine() or None,
        }

    def cpu_info(self) -> dict[str, Any]:
        base = {
            "model": platform.processor() or None,
            "physical_cores": None,
            "logical_cores": os.cpu_count(),
        }
        records = self._powershell_json(
            "$p = @(Get-CimInstance Win32_Processor); "
            "[pscustomobject]@{"
            "Model = (($p | ForEach-Object {$_.Name}) -join ' + '); "
            "PhysicalCores = (($p | Measure-Object -Property NumberOfCores -Sum).Sum); "
            "LogicalCores = (($p | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum)"
            "} | ConvertTo-Json -Compress"
        )
        if records:
            record = records[0]
            model = record.get("Model")
            physical = record.get("PhysicalCores")
            logical = record.get("LogicalCores")
            if isinstance(model, str) and model.strip():
                base["model"] = model.strip()
            if isinstance(physical, int) and physical > 0:
                base["physical_cores"] = physical
            if isinstance(logical, int) and logical > 0:
                base["logical_cores"] = logical
        return base

    def memory_info(self) -> dict[str, Any]:
        if os.name == "nt":
            class MemoryStatusEx(ctypes.Structure):
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

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(MemoryStatusEx)
            try:
                success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            except (AttributeError, OSError):
                success = 0
            if success:
                return {
                    "installed_bytes": int(status.ullTotalPhys),
                    "available_bytes": int(status.ullAvailPhys),
                }

        if hasattr(os, "sysconf"):
            try:
                page_size = int(os.sysconf("SC_PAGE_SIZE"))
                pages = int(os.sysconf("SC_PHYS_PAGES"))
                available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
                return {
                    "installed_bytes": page_size * pages,
                    "available_bytes": page_size * available_pages,
                }
            except (OSError, ValueError, TypeError):
                pass
        return {"installed_bytes": None, "available_bytes": None}

    def gpu_info(self) -> list[dict[str, Any]]:
        result = self._command(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version,pci.bus_id",
                "--format=csv,noheader,nounits",
            ],
            10,
        )
        if result.returncode == 0:
            parsed = _parse_nvidia_gpu_csv(result.stdout)
            if parsed:
                return parsed

        records = self._powershell_json(
            "@(Get-CimInstance Win32_VideoController | "
            "Select-Object Name, DriverVersion, AdapterRAM, PNPDeviceID) | "
            "ConvertTo-Json -Compress"
        )
        gpus: list[dict[str, Any]] = []
        for record in records:
            adapter_ram = record.get("AdapterRAM")
            gpus.append(
                {
                    "name": record.get("Name") if isinstance(record.get("Name"), str) else None,
                    "vram_bytes": adapter_ram if isinstance(adapter_ram, int) and adapter_ram >= 0 else None,
                    "driver_version": record.get("DriverVersion")
                    if isinstance(record.get("DriverVersion"), str)
                    else None,
                    "pnp_device_id": record.get("PNPDeviceID")
                    if isinstance(record.get("PNPDeviceID"), str)
                    else None,
                    "probe_source": "windows-cim",
                }
            )
        return gpus

    def storage_info(self) -> list[dict[str, Any]]:
        anchor = self.target_path.anchor or os.path.sep
        try:
            usage = shutil.disk_usage(anchor)
        except OSError:
            return [
                {
                    "volume": anchor,
                    "total_bytes": None,
                    "free_bytes": None,
                }
            ]
        return [
            {
                "volume": anchor,
                "total_bytes": int(usage.total),
                "free_bytes": int(usage.free),
            }
        ]

    def python_info(self) -> dict[str, Any]:
        return {
            "implementation": platform.python_implementation() or None,
            "version": platform.python_version() or None,
            "compiler": platform.python_compiler() or None,
            "architecture": platform.architecture()[0] or None,
        }

    def compute_runtime_info(self) -> list[dict[str, Any]]:
        runtimes: list[dict[str, Any]] = []
        nvidia = self._command(["nvidia-smi"], 10)
        if nvidia.returncode == 0:
            runtimes.append(
                {
                    "kind": "nvidia-driver-cuda-capability",
                    "version": _parse_cuda_version(nvidia.stdout),
                    "probe_source": "nvidia-smi",
                }
            )
        nvcc = self._command(["nvcc", "--version"], 10)
        if nvcc.returncode == 0:
            runtimes.append(
                {
                    "kind": "cuda-toolkit",
                    "version": _parse_nvcc_version(nvcc.stdout + nvcc.stderr),
                    "probe_source": "nvcc",
                }
            )
        return runtimes

    def power_thermal_info(self) -> dict[str, Any] | None:
        if os.name != "nt":
            return None
        result = self._command(["powercfg", "/GETACTIVESCHEME"], 10)
        if result.returncode != 0:
            return {
                "active_power_scheme_guid": None,
                "active_power_scheme_name": None,
                "thermal_state": None,
            }
        parsed = _parse_power_scheme(result.stdout)
        return parsed or {
            "active_power_scheme_guid": None,
            "active_power_scheme_name": None,
            "thermal_state": None,
        }


def collect_host_profile(
    logical_id: str,
    *,
    probe: HostProbe | None = None,
    captured_at: str | None = None,
) -> SealedEvidence:
    source = probe or SystemHostProbe()
    return host_profile(
        logical_id,
        captured_at=captured_at or _utc_now(),
        os_info=source.os_info(),
        cpu=source.cpu_info(),
        memory=source.memory_info(),
        gpus=source.gpu_info(),
        storage=source.storage_info(),
        python=source.python_info(),
        compute_runtimes=source.compute_runtime_info(),
        power_thermal=source.power_thermal_info(),
    )


def _default_output(logical_id: str) -> Path:
    return Path("local-state") / "host-profiles" / f"{logical_id}.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m localbench.v2.host",
        description="Capture a Benchmark Lab V2 host profile without contacting a model.",
    )
    parser.add_argument("--id", required=True, help="safe logical host ID")
    parser.add_argument(
        "--output",
        type=Path,
        help="output JSON path; defaults to local-state/host-profiles/<id>.json",
    )
    parser.add_argument(
        "--target-path",
        type=Path,
        help="path whose storage volume should be measured; defaults to the current directory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        profile = collect_host_profile(
            args.id,
            probe=SystemHostProbe(target_path=args.target_path),
        )
        output = (args.output or _default_output(args.id)).resolve()
        atomic_write_json(output, profile.to_dict())
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(str(output))
    print(f"facts_sha256={profile.payload['facts_sha256']}")
    print(f"evidence_sha256={profile.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
