"""Read-only legacy run adapter for T13/T16. No new state store or scoring.

Preserves the original result fields and evidence pointers. It intentionally
does not infer suite versions, human verdicts, or model configurations.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


SUPPORTED = frozenset(("flashnext-role-review-package:v1",
                       "assistant-001-v1", "assistant-002-v1"))


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError(f"invalid run report: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("run report must be an object")
    return data


def normalize_legacy_report(path: Path) -> dict[str, Any]:
    """Preserve observed evidence without inventing missing scores or versions."""
    path = Path(path)
    raw = _read(path)
    if raw.get("schema_version") == "flashnext-role-review-package:v1":
        kind = "historical-role-review"
        rows = raw.get("case_results")
        metadata = raw.get("metadata") or {}
        if not isinstance(rows, list) or not isinstance(metadata, dict):
            raise ValueError("invalid historical role report shape")
    elif raw.get("campaign") in ("assistant-001-v1", "assistant-002-v1"):
        kind = "assistant-worker-project"
        rows = raw.get("results")
        metadata = {"campaign": raw["campaign"], "track": raw.get("track")}
        if not isinstance(rows, list):
            raise ValueError("invalid Assistant summary shape")
    else:
        raise ValueError("unsupported legacy report schema")
    result_rows = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str):
            raise ValueError("invalid case row in legacy report")
        result_rows.append({
            "case_id": row["case_id"],
            "role": row.get("role"),
            "ordinal": row.get("ordinal"),
            "execution_status": row.get("execution_status") or row.get("status"),
            "assessed_outcome": row.get("assessed_outcome"),
            "human_adjudication": row.get("human_adjudication"),
            "human_review_status": row.get("human_review_status"),
            "deterministic_passed": row.get("deterministic_passed"),
            "first_pass_passed": row.get("first_pass_passed"),
            "repair_attempted": row.get("repair_attempted"),
            "repair_passed": row.get("repair_passed"),
            "suite_id": row.get("suite_id"),
            "suite_version": row.get("suite_version"),
            "rubric_id": row.get("rubric_id"),
            "rubric_version": row.get("rubric_version"),
            "model_identity": row.get("model_identity"),
            "runtime_identity": row.get("runtime_identity"),
            "worker_mode": row.get("worker_mode"),
            "evidence_directory": row.get("evidence_directory"),
            "assessment_file": row.get("assessment_file"),
            "artifact_sha256": row.get("artifact_sha256"),
            "source_report": str(path),
        })
    return {"schema_version": "qualification-v2/legacy-read-adapter:v1",
            "source_kind": kind, "source_path": str(path),
            "metadata": metadata, "cases": result_rows,
            "legacy_fields_unknown": True, "role_qualification": None}
