"""Pure, non-executable validation for the qualification-v2 DESIGN registry.

The registry is not wired to any runner, does not approve a release and does not
authorize source access. Actual prompt, workspace, symlink and tool disclosures
must be checked by a trusted adapter in T05 before inference.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "qualification-v2/evaluation-modes-v1"
CONTROLLED = "controlled_role_qualification"
INTEGRATION = "native_pipeline_integration"
TRACK_ROLES = {
    CONTROLLED: ("planner", "governor", "worker", "tester", "reviewer"),
    INTEGRATION: ("pipeline",),
}
TRACK_TRANSPORTS = {
    CONTROLLED: ("direct_ollama", "native_dsh"),
    INTEGRATION: ("native_dsh",),
}
WORKER_MODES = ("isolated_task", "cumulative_project")
_REQUIRED_PLANNER_SECRETS = frozenset(
    ("fixed_worker_tasks", "reference_plan", "governor_expected_decision",
     "governor_case_oracle", "assessor_checks", "assessor_reference",
     "reference_solution", "hidden_tests")
)
_REQUIRED_AUTHORITY_FALSE = (
    "model_governor_verdict_is_authority",
    "governor_simulation_is_real_owner_approval",
    "candidate_python_os_sandboxed",
    "production_services_authorized",
    "automatic_role_promotion",
    "private_governance_source_belongs_in_public_repo",
)


def _root(repo_root: Path | None) -> Path:
    return Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]


def load_registry(repo_root: Path | None = None) -> dict[str, Any]:
    """Load and validate static metadata; no execution or owner authentication."""
    path = _root(repo_root) / "docs" / "qualification-v2" / "EVALUATION_MODES_V1.json"
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"Invalid qualification mode registry: {exc}") from exc
    if not isinstance(registry, dict) or registry.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported qualification mode registry version")
    if registry.get("implementation_status") != "CONTRACT_ONLY_NOT_CONNECTED_TO_LAUNCHERS":
        raise ValueError("Registry cannot claim execution or release authority")
    if registry.get("candidate_response_policy") != "NATURAL_LANGUAGE_NO_NEW_JSON_HANDOFF_REQUIREMENT":
        raise ValueError("Registry cannot impose new model response formats")

    tracks = registry.get("tracks")
    if not isinstance(tracks, dict) or set(tracks) != set(TRACK_ROLES):
        raise ValueError("Unknown or missing qualification tracks")
    for track, roles in TRACK_ROLES.items():
        entry = tracks.get(track)
        if (not isinstance(entry, dict)
                or entry.get("roles") != list(roles)
                or entry.get("transports") != list(TRACK_TRANSPORTS[track])
                or entry.get("worker_modes") != (list(WORKER_MODES) if track == CONTROLLED else [])
                or entry.get("upstream_candidate_output_as_authority") is not False
                or entry.get("reference_substitution_on_failure") is not False):
            raise ValueError(f"Unsupported or unsafe {track} configuration")
    modes = registry.get("worker_modes")
    if not isinstance(modes, dict) or set(modes) != set(WORKER_MODES):
        raise ValueError("Unknown Worker submodes")
    for key in WORKER_MODES:
        if not isinstance(modes[key], dict) or not modes[key].get("predecessor_policy"):
            raise ValueError(f"Missing {key} prerequisite rule")

    roles = registry.get("role_inputs")
    if not isinstance(roles, dict) or set(roles) != set(TRACK_ROLES[CONTROLLED]):
        raise ValueError("Unknown role-disclosure policy")
    for role, spec in roles.items():
        if not isinstance(spec, dict) or set(spec) != {"required", "optional", "prohibited"}:
            raise ValueError(f"Invalid {role} source-disclosure policy")
        lists = [spec[k] for k in ("required", "optional", "prohibited")]
        if (any(not isinstance(x, list) or any(type(y) is not str or not y for y in x)
                for x in lists)
                or not spec["required"]
                or len(set(y for x in lists for y in x)) != sum(len(x) for x in lists)):
            raise ValueError(f"Duplicate, overlapping or malformed {role} source categories")
    planner = roles["planner"]
    if not _REQUIRED_PLANNER_SECRETS.issubset(planner["prohibited"]):
        raise ValueError("Planner source policy does not hide reference answers")
    if ("project_intent" not in planner["required"]
            or "candidate_contract" not in planner["required"]
            or "starter_readonly" not in planner["required"]):
        raise ValueError("Planner is missing original problem/context sources")

    safety = registry.get("safety")
    if not isinstance(safety, dict) or any(safety.get(x) is not False for x in _REQUIRED_AUTHORITY_FALSE):
        raise ValueError("Mode registry weakens authority/sandbox safeguards")
    if safety.get("native_execution_requires_installed_provenance") is not True:
        raise ValueError("Native DSH runtime provenance must be checked before execution")
    if registry.get("authority_origins") != [
        "approved_benchmark_fixture", "native_owner_release_receipt"
    ]:
        raise ValueError("Unknown authority origin")
    if registry.get("human_verdicts") != ["PASS", "FAIL", "BLOCKED", "NOT_ASSESSED"]:
        raise ValueError("Unexpected human review verdicts")
    return registry


def validate_selection(
    track: str, role: str, transport: str, worker_mode: str | None = None,
    *, repo_root: Path | None = None,
) -> dict[str, str | None]:
    """Validate *metadata only*. Success never authorizes launching a model."""
    spec = load_registry(repo_root)
    if (type(track) is not str or track not in TRACK_ROLES
            or type(role) is not str or role not in TRACK_ROLES[track]
            or type(transport) is not str or transport not in TRACK_TRANSPORTS[track]):
        raise ValueError("Unknown or incompatible qualification track, role or transport")
    if track == CONTROLLED and role == "worker":
        if type(worker_mode) is not str or worker_mode not in WORKER_MODES:
            raise ValueError("Controlled Worker qualification requires a known submode")
    elif worker_mode is not None:
        raise ValueError("Worker mode is invalid outside controlled Worker qualification")
    # Check against the reviewed registry even if passed explicitly by the caller.
    expected = spec.get("tracks", {}).get(track)
    if (not isinstance(expected, dict)
            or role not in expected.get("roles", ())
            or transport not in expected.get("transports", ())
            or (worker_mode is not None and worker_mode not in expected.get("worker_modes", ()))):
        raise ValueError("Selection is not declared in the reviewed registry")
    return {"track": track, "role": role, "transport": transport, "worker_mode": worker_mode}


def validate_disclosure(
    role: str, source_categories: Iterable[str], *,
    repo_root: Path | None = None,
) -> frozenset[str]:
    """Validate *declared category labels*, NOT the actual visible file contents."""
    spec = load_registry(repo_root)
    if type(role) is not str or role not in TRACK_ROLES[CONTROLLED]:
        raise ValueError("Unsupported role disclosure")
    policy = spec["role_inputs"][role]
    if isinstance(source_categories, (str, bytes)):
        raise ValueError("Source categories must be a collection, not a text string")
    try:
        items = list(source_categories)
        if any(type(x) is not str for x in items) or len(set(items)) != len(items):
            raise ValueError("Invalid or duplicate source categories")
        supplied = frozenset(items)
    except TypeError as exc:
        raise ValueError("Invalid source categories collection") from exc
    required = set(policy["required"])
    allowed = required | set(policy["optional"])
    if not required.issubset(supplied):
        raise ValueError("Missing required role input source categories")
    if not supplied.issubset(allowed):
        raise ValueError("Undeclared or prohibited role input source category")
    return supplied
