"""Explicit V2 role trace contract; distinct from accepted L0/L1/L2 traces."""
from __future__ import annotations

import re
from typing import Any, Mapping

from .contracts import EvidenceRef, SealedEvidence, sha256_json
from .flashnext_role_harness import ROLE_SURFACE_ID, ROLE_TOOL_DEFINITIONS, ROLE_TOOL_SCHEMA_SHA256

ROLE_TRACE_VERSION = "benchmark-lab-role-execution-trace:v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FIELDS = {
    "trace_version", "campaign_only_surface", "case_id", "role", "trial",
    "execution_interface", "source_refs", "tool_surface", "scope",
    "initial_workspace", "events", "final_workspace", "summary", "preflight", "assessments",
}


def _nonnegative(value: Any, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be an integer >= 0")


def validate_role_execution_trace(record: SealedEvidence) -> None:
    """Validate shape, interface identity, exact tool contract and event digests."""
    if not isinstance(record, SealedEvidence) or record.record_type != "role_execution_trace":
        raise ValueError("expected role_execution_trace evidence")
    value = record.payload
    if set(value) != _FIELDS:
        raise ValueError("role trace fields do not match the versioned schema")
    if value["trace_version"] != ROLE_TRACE_VERSION or value["campaign_only_surface"] is not True:
        raise ValueError("unsupported role trace version or surface declaration")
    if not isinstance(value["case_id"], str) or not _ID.fullmatch(value["case_id"]):
        raise ValueError("invalid role case ID")
    if value["role"] not in {"planner", "governor", "worker", "tester", "reviewer"}:
        raise ValueError("unsupported role name")
    for key, expected in (("trial", "trial_identity"), ("execution_interface", "execution_interface_identity")):
        if EvidenceRef.from_dict(value[key]).record_type != expected:
            raise ValueError(f"role trace {key} reference type mismatch")
    for key in ("source_refs", "assessments"):
        if not isinstance(value[key], (tuple, list)) or any(not isinstance(x, Mapping) for x in value[key]):
            raise ValueError(f"role trace {key} must contain objects")
    if value["preflight"] is not None and not isinstance(value["preflight"], Mapping):
        raise ValueError("role preflight must be an object or null")
    for key in ("initial_workspace", "final_workspace"):
        if not isinstance(value[key], Mapping) or any(not isinstance(p, str) or not p or not isinstance(d, str) or not (_SHA.fullmatch(d) or d.startswith("symlink:")) for p, d in value[key].items()):
            raise ValueError("role workspace snapshots must map paths to hashes or observed symlinks")
    surface = value["tool_surface"]
    if not isinstance(surface, Mapping) or set(surface) != {"id", "tools", "max_tool_calls", "schema_sha256"}:
        raise ValueError("role tool surface is malformed")
    _nonnegative(surface["max_tool_calls"], "max_tool_calls")
    if surface["id"] == "none":
        if surface["tools"] or surface["max_tool_calls"] != 0 or surface["schema_sha256"] is not None:
            raise ValueError("tool-free role trace exposes tools")
    elif surface["id"] != ROLE_SURFACE_ID or list(surface["tools"]) != [x["name"] for x in ROLE_TOOL_DEFINITIONS] or surface["schema_sha256"] != ROLE_TOOL_SCHEMA_SHA256 or surface["max_tool_calls"] < 1:
        raise ValueError("role file/test surface contract mismatch")
    scope = value["scope"]
    if scope is not None:
        if not isinstance(scope, Mapping) or set(scope) != {"readable_paths", "writable_paths"}:
            raise ValueError("role workspace scope is malformed")
        for paths in scope.values():
            if not isinstance(paths, (tuple, list)) or any(not isinstance(p, str) or not p for p in paths) or len(paths) != len(set(paths)):
                raise ValueError("role scope paths must be unique nonempty strings")
    events = value["events"]
    if not isinstance(events, (tuple, list)):
        raise ValueError("role events must be an array")
    for sequence, event in enumerate(events, 1):
        if not isinstance(event, Mapping) or set(event) != {"sequence", "event_type", "phase", "payload", "event_sha256"}:
            raise ValueError("role event shape mismatch")
        if event["sequence"] != sequence or isinstance(event["sequence"], bool):
            raise ValueError("role events are not contiguous")
        if event["phase"] not in {"setup", "dispatch", "repair"}:
            raise ValueError("role event phase is invalid")
        if not isinstance(event["event_type"], str) or not _ID.fullmatch(event["event_type"]) or not isinstance(event["payload"], Mapping):
            raise ValueError("role event type or payload is invalid")
        if event["event_sha256"] != sha256_json({k: v for k, v in event.items() if k != "event_sha256"}):
            raise ValueError("role event digest mismatch")
    summary = value["summary"]
    if not isinstance(summary, Mapping) or not {"status", "stop_reason", "compatibility", "correctness", "model_turns", "tool_calls"}.issubset(summary):
        raise ValueError("role summary is incomplete")
    if summary["status"] not in {"success", "error", "blocked", "resource_limit", "protocol_failure"}:
        raise ValueError("role summary status is invalid")
    for key in ("stop_reason", "compatibility", "correctness"):
        if not isinstance(summary[key], str) or not summary[key]:
            raise ValueError(f"role summary {key} must be nonempty")
    for key in ("model_turns", "tool_calls"):
        _nonnegative(summary[key], key)
