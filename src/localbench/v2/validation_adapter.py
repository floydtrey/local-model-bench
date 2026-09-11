from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..util import validate_id
from .containment import ContainmentPolicy


LEGACY_PACKET_ADAPTER_VERSION = "benchmark-lab-legacy-validation-adapter:v1"


@dataclass(frozen=True)
class AdaptedValidationTask:
    adapter_version: str
    packet_id: str
    packet_sha256: str
    task_id: str
    title: str
    category: str
    source_commit: str
    materialization: str
    policy: ContainmentPolicy
    unresolved_requirements: tuple[str, ...]
    assessor_files: tuple[str, ...]

    @property
    def qualification_ready(self) -> bool:
        return not self.unresolved_requirements

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_version": self.adapter_version,
            "packet_id": self.packet_id,
            "packet_sha256": self.packet_sha256,
            "task_id": self.task_id,
            "title": self.title,
            "category": self.category,
            "source_commit": self.source_commit,
            "materialization": self.materialization,
            "policy": self.policy.to_dict(),
            "unresolved_requirements": list(self.unresolved_requirements),
            "assessor_files": list(self.assessor_files),
        }


def _packet_sha256(source_bytes: bytes) -> str:
    return hashlib.sha256(source_bytes).hexdigest()


def _parse_packet(source_bytes: bytes) -> Mapping[str, Any]:
    try:
        parsed = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"legacy validation packet is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError("legacy validation packet must be an object")
    if parsed.get("schema_version") != 1:
        raise ValueError("only legacy validation packet schema_version=1 is supported")
    return parsed


def _normalized_writable_paths(paths: Sequence[str] | None) -> tuple[str, ...] | None:
    if paths is None:
        return None
    return tuple(paths)


def adapt_legacy_validation_task(
    source_bytes: bytes,
    *,
    task_id: str,
    writable_paths: Sequence[str] | None = None,
    max_output_bytes: int | None = None,
    max_memory_bytes: int | None = None,
) -> AdaptedValidationTask:
    """Project one V1 packet task into V2 containment semantics.

    The source bytes are never rewritten. The adapter records their exact SHA-256
    and creates a new V2 policy overlay. Machine-readable write scope did not
    exist in real-tasks-v1, so qualification remains blocked until the caller
    supplies an explicit V2 writable-path overlay.
    """

    validate_id(task_id, "task_id")
    packet = _parse_packet(source_bytes)
    packet_id = packet.get("packet_id")
    validate_id(packet_id, "packet_id")
    tasks = packet.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("legacy validation packet tasks must be an array")
    matches = [task for task in tasks if isinstance(task, Mapping) and task.get("id") == task_id]
    if len(matches) != 1:
        raise ValueError(f"task_id must match exactly one task: {task_id}")
    task = matches[0]
    source = task.get("source")
    limits = task.get("limits")
    if not isinstance(source, Mapping) or not isinstance(limits, Mapping):
        raise ValueError("legacy task must define source and limits objects")
    if source.get("materialization") != "git archive":
        raise ValueError("unsupported legacy task materialization")
    network = limits.get("network")
    if network != "disabled":
        raise ValueError("legacy adapter currently supports only network=disabled tasks")
    wall_seconds = limits.get("wall_seconds")
    max_attempts = limits.get("max_attempts")
    explicit_paths = _normalized_writable_paths(writable_paths)
    unresolved: list[str] = []
    if explicit_paths is None:
        unresolved.append("explicit_workspace_write_scope_required")
    policy = ContainmentPolicy(
        wall_seconds=wall_seconds,
        max_attempts=max_attempts,
        network_policy="disabled",
        process_custody="strict",
        require_workspace_isolation=True,
        require_assessor_isolation=True,
        writable_paths=explicit_paths,
        max_output_bytes=max_output_bytes,
        max_memory_bytes=max_memory_bytes,
    )
    assessor_files: list[str] = []
    assessment = task.get("assessment")
    if isinstance(assessment, str) and assessment:
        assessor_files.append(assessment)
    tests = task.get("assessor_tests", [])
    if tests is not None:
        if not isinstance(tests, list) or any(not isinstance(item, str) or not item for item in tests):
            raise ValueError("assessor_tests must be an array of non-empty strings")
        assessor_files.extend(tests)
    return AdaptedValidationTask(
        adapter_version=LEGACY_PACKET_ADAPTER_VERSION,
        packet_id=packet_id,
        packet_sha256=_packet_sha256(source_bytes),
        task_id=task_id,
        title=str(task.get("title", "")),
        category=str(task.get("category", "")),
        source_commit=str(source.get("baseline_commit", "")),
        materialization="git archive",
        policy=policy,
        unresolved_requirements=tuple(unresolved),
        assessor_files=tuple(sorted(set(assessor_files))),
    )
