from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import traceback
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from localbench.v2 import (
    ConfigurationBinding,
    DriverBinding,
    EvidenceRef,
    EvidenceStore,
    OllamaChatDriver,
    SealedEvidence,
    aggregate_repeated_run,
    parse_benchmark_pack,
    persist_aggregate_report,
    resolve_effective_configuration,
    run_v2_repetitions,
    sha256_json,
)
from localbench.v2.evaluators import EvaluatorRegistry
from localbench.v2.shared_battery import register_shared_battery_evaluators


EXPECTED_BRANCH = "architecture/benchmark-lab-v2"
EXPECTED_COMMIT = "a415e286365a6086f3ccec3f717d4c106e3be170"
CAMPAIGN_FILE = "sealed-shared-screen-campaign-plan-v2.json"
EXPECTED_CAMPAIGN_FILE_SHA256 = (
    "a9adda6c29654df638ac370089abf2b12dc4d62f3ecd8914e28f9b47cfd67fdf"
)
EXPECTED_CAMPAIGN_RECORD_SHA256 = (
    "3035c45b25cbb967cb9a6e0a8e2058b0ecfdb84add488d8d3d8090516bca726e"
)
EXPECTED_BATCH_ID = "intrinsic-neutral-candidate-qwen3.5-9b"
EXPECTED_CANDIDATE_ID = "candidate-qwen3.5-9b"
EXPECTED_MODEL_NAME = "qwen3.5:9b"
EXPECTED_OBSERVATION_COUNT = 14
ROUTER_ID = "sealed-campaign-profile-router-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(bench: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=bench, text=True).strip()


def sealed_plain(facts: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(facts)
    record["record_sha256"] = sha256_json(record)
    return record


def validate_plain(record: Mapping[str, Any], label: str) -> None:
    facts = dict(record)
    claimed = facts.pop("record_sha256", None)
    if not isinstance(claimed, str) or sha256_json(facts) != claimed:
        raise RuntimeError(f"{label} record hash validation failed")


def write_exclusive(path: Path, record: Mapping[str, Any]) -> None:
    data = (
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()


def api_json(base_uri: str, path: str) -> Mapping[str, Any]:
    with urllib.request.urlopen(base_uri.rstrip("/") + path, timeout=20) as response:
        value = json.loads(response.read())
    if not isinstance(value, Mapping):
        raise RuntimeError(f"Ollama {path} response was not an object")
    return value


def load_ref(store: EvidenceStore, value: Mapping[str, Any]) -> SealedEvidence:
    return store.load(EvidenceRef.from_dict(value))


def asset_loader(bench: Path):
    allowed_root = (bench / "benchmark-packs" / "v2" / "fixtures").resolve()

    def load(asset: Mapping[str, Any]) -> bytes:
        locator = asset.get("source_locator")
        if not isinstance(locator, str) or "\\" in locator:
            raise RuntimeError("Context asset locator is not canonical")
        relative = PurePosixPath(locator)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("Context asset locator escapes the repository")
        target = bench.joinpath(*relative.parts).resolve(strict=True)
        try:
            target.relative_to(allowed_root)
        except ValueError as exc:
            raise RuntimeError("Context asset is outside the fixture root") from exc
        if not target.is_file():
            raise RuntimeError(f"Context asset is not a file: {locator}")
        return target.read_bytes()

    return load


def configuration_binding(
    profile_id: str,
    config: SealedEvidence,
    runtime: SealedEvidence,
    model: SealedEvidence,
) -> ConfigurationBinding:
    settings = config.payload["settings"]
    spec = {
        "schema_version": settings["schema_version"],
        "comparison_mode": settings["comparison_mode"],
        "generation": settings["generation"],
        "execution": config.payload["limits"],
        "tool_surface": config.payload["tool_surface"],
    }
    restored = resolve_effective_configuration(
        config.logical_id,
        runtime=runtime,
        model=model,
        spec=spec,
        adapter_resolution=settings["adapter_resolution"],
    )
    if restored.reference != config.reference:
        raise RuntimeError(f"Configuration does not reconstruct: {profile_id}")
    return ConfigurationBinding(
        profile_id=profile_id,
        spec=spec,
        adapter_resolution=settings["adapter_resolution"],
        effective_logical_id=config.logical_id,
        expected_effective_config=config.reference,
    )


class ProfileRouter:
    def __init__(
        self,
        case_profiles: Mapping[str, str],
        drivers: Mapping[str, OllamaChatDriver],
    ) -> None:
        self.case_profiles = dict(case_profiles)
        self.drivers = dict(drivers)

    def __call__(self, request):
        profile_id = self.case_profiles.get(request.case_id)
        if profile_id is None:
            raise RuntimeError(f"No released route for case {request.case_id}")
        driver = self.drivers.get(profile_id)
        if driver is None:
            raise RuntimeError(f"No released driver for profile {profile_id}")
        return driver(request)


def prepare(bench: Path) -> dict[str, Any]:
    root = bench / "local-state" / "candidate-qualification-1"
    campaign_path = root / CAMPAIGN_FILE
    evidence_root = root / "sealed-evidence"
    release_path = root / "releases" / f"{EXPECTED_BATCH_ID}-v2.json"
    execution_root = root / "executions" / f"{EXPECTED_BATCH_ID}-v2"
    start_path = execution_root / "start.json"
    completion_path = execution_root / "completion.json"
    failure_path = execution_root / "failure.json"

    if git(bench, "branch", "--show-current") != EXPECTED_BRANCH:
        raise RuntimeError("Unexpected benchmark branch")
    if git(bench, "rev-parse", "HEAD") != EXPECTED_COMMIT:
        raise RuntimeError("Unexpected benchmark HEAD")
    if git(bench, "status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("Tracked benchmark working tree is not clean")
    if file_sha256(campaign_path) != EXPECTED_CAMPAIGN_FILE_SHA256:
        raise RuntimeError("V2 campaign file hash changed")

    campaign = read_json(campaign_path)
    campaign_record = dict(campaign)
    claimed_record = campaign_record.pop("record_sha256", None)
    if claimed_record != EXPECTED_CAMPAIGN_RECORD_SHA256:
        raise RuntimeError("Unexpected V2 campaign record identity")
    if sha256_json(campaign_record) != claimed_record:
        raise RuntimeError("V2 campaign record hash validation failed")
    campaign_facts = dict(campaign_record)
    claimed_facts = campaign_facts.pop("campaign_facts_sha256", None)
    if sha256_json(campaign_facts) != claimed_facts:
        raise RuntimeError("V2 campaign facts hash validation failed")
    if campaign.get("execution_state") != "sealed-awaiting-release":
        raise RuntimeError("Campaign is not awaiting release")
    if any(campaign.get("authorization", {}).values()):
        raise RuntimeError("Campaign unexpectedly contains execution authority")

    batches = [
        item
        for item in campaign["batch_plan"]
        if item.get("batch_id") == EXPECTED_BATCH_ID
    ]
    if len(batches) != 1:
        raise RuntimeError("First batch is missing or duplicated")
    batch = batches[0]
    if (
        batch.get("phase") != "intrinsic-neutral"
        or batch.get("candidate_logical_id") != EXPECTED_CANDIDATE_ID
        or batch.get("release") != "supervised-first"
        or batch.get("observation_count") != EXPECTED_OBSERVATION_COUNT
        or len(batch.get("observation_ids", ())) != EXPECTED_OBSERVATION_COUNT
    ):
        raise RuntimeError("First batch scope changed")

    observations = {
        item["observation_id"]: item for item in campaign["observations"]
    }
    selected = [observations[item] for item in batch["observation_ids"]]
    if any(
        item["candidate_logical_id"] != EXPECTED_CANDIDATE_ID
        or item["phase"] != "intrinsic-neutral"
        or item["repetition_phase"] != "screen"
        or item["trial_ordinal"] != 1
        or item["level"] not in {"L0", "L1"}
        for item in selected
    ):
        raise RuntimeError("Released observations exceed the first-batch boundary")

    store = EvidenceStore(evidence_root)
    host = load_ref(store, campaign["host"]["execution_observation"])
    runtime = load_ref(store, campaign["runtime"])
    model_ref = selected[0]["model"]
    if any(item["model"] != model_ref for item in selected):
        raise RuntimeError("Released observations do not bind one model")
    model = load_ref(store, model_ref)
    if (
        model.logical_id != EXPECTED_CANDIDATE_ID
        or model.payload["name"] != EXPECTED_MODEL_NAME
    ):
        raise RuntimeError("Released model identity changed")

    source_by_pack = {
        item["pack_id"]: item for item in campaign["pack_source_identities"]
    }
    benchmark_refs = {
        item["logical_id"]: item for item in campaign["benchmark_inputs"]
    }
    packs: dict[str, dict[str, Any]] = {}
    configs: dict[str, SealedEvidence] = {}
    case_profiles: dict[str, str] = {}

    for pack_id in ("shared-l0-core", "shared-l1-core"):
        source_identity = source_by_pack[pack_id]
        locator = source_identity["source_locator"]
        source_path = bench.joinpath(*PurePosixPath(locator).parts)
        source = source_path.read_bytes()
        pack = parse_benchmark_pack(source)
        if pack.pack_id != pack_id:
            raise RuntimeError(f"Pack ID changed: {pack_id}")
        if pack.source_sha256 != source_identity["source_sha256"]:
            raise RuntimeError(f"Pack source changed: {pack_id}")
        if pack.semantic_sha256 != source_identity["semantic_sha256"]:
            raise RuntimeError(f"Pack semantics changed: {pack_id}")
        benchmark = pack.to_benchmark_input(source_locator=locator)
        expected_benchmark = benchmark_refs.get(benchmark.logical_id)
        if (
            expected_benchmark is None
            or benchmark.reference.to_dict() != expected_benchmark
            or load_ref(store, expected_benchmark).reference != benchmark.reference
        ):
            raise RuntimeError(f"Benchmark evidence changed: {pack_id}")
        expected_cases = [
            item["case_id"] for item in selected if item["level"] == pack.level
        ]
        if [item["case_id"] for item in pack.cases] != expected_cases:
            raise RuntimeError(f"Released case order changed: {pack_id}")

        for case in pack.cases:
            case_id = str(case["case_id"])
            profile_id = str(case["requirements"]["configuration_profile"])
            observation = next(
                item
                for item in selected
                if item["level"] == pack.level and item["case_id"] == case_id
            )
            config = load_ref(store, observation["effective_config"])
            prior = configs.setdefault(profile_id, config)
            if prior.reference != config.reference:
                raise RuntimeError(f"Profile has multiple configs: {profile_id}")
            case_profiles[case_id] = profile_id

        packs[pack_id] = {
            "pack": pack,
            "source": source,
            "source_locator": locator,
        }

    bindings = {
        profile_id: configuration_binding(
            profile_id, config, runtime, model
        )
        for profile_id, config in configs.items()
    }
    drivers = {
        profile_id: OllamaChatDriver(config)
        for profile_id, config in configs.items()
    }

    transport = runtime.payload["transport"]
    base_uri = transport.get("base_uri") or transport.get("endpoint")
    if not isinstance(base_uri, str):
        raise RuntimeError("Sealed runtime has no provider URI")
    version = api_json(base_uri, "/api/version")
    tags = api_json(base_uri, "/api/tags")
    loaded = api_json(base_uri, "/api/ps")
    installed = [
        item
        for item in tags.get("models", ())
        if item.get("name") == EXPECTED_MODEL_NAME
        or item.get("model") == EXPECTED_MODEL_NAME
    ]
    if version.get("version") != runtime.payload["version"]:
        raise RuntimeError("Live runtime version changed")
    if len(installed) != 1:
        raise RuntimeError("Released model is not uniquely installed")
    if installed[0].get("digest") != model.payload["provider_digest"]:
        raise RuntimeError("Live model digest changed")
    if loaded.get("models"):
        raise RuntimeError("Preflight requires no loaded models")

    return {
        "bench": bench,
        "campaign": campaign,
        "batch": batch,
        "store": store,
        "host": host,
        "runtime": runtime,
        "model": model,
        "packs": packs,
        "bindings": bindings,
        "drivers": drivers,
        "case_profiles": case_profiles,
        "base_uri": base_uri,
        "provider_version": version["version"],
        "release_path": release_path,
        "start_path": start_path,
        "completion_path": completion_path,
        "failure_path": failure_path,
    }


def load_or_create_release(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    path: Path = ctx["release_path"]
    if path.exists():
        release = read_json(path)
        validate_plain(release, "Release")
    else:
        release = sealed_plain({
            "schema_version": "benchmark-lab-batch-release:v1",
            "release_id": "shared-screen-qwen3.5-9b-intrinsic-v2",
            "authorized_at_utc": utc_now(),
            "campaign_record_sha256": EXPECTED_CAMPAIGN_RECORD_SHA256,
            "campaign_file_sha256": EXPECTED_CAMPAIGN_FILE_SHA256,
            "batch_id": EXPECTED_BATCH_ID,
            "candidate_logical_id": EXPECTED_CANDIDATE_ID,
            "phase": "intrinsic-neutral",
            "repetition_phase": "screen",
            "observation_count": EXPECTED_OBSERVATION_COUNT,
            "observation_ids": list(ctx["batch"]["observation_ids"]),
            "runner_script_sha256": file_sha256(Path(__file__)),
            "authorization": {
                "scored_screen_execution": True,
                "qualification_execution": False,
                "bounded_tool_execution": False,
                "pydantic_ai_execution": False,
                "acl_execution": False,
                "automatic_retry": False,
            },
        })
        write_exclusive(path, release)

    if (
        release.get("campaign_record_sha256")
        != EXPECTED_CAMPAIGN_RECORD_SHA256
        or release.get("batch_id") != EXPECTED_BATCH_ID
        or release.get("observation_ids")
        != list(ctx["batch"]["observation_ids"])
        or release.get("runner_script_sha256")
        != file_sha256(Path(__file__))
        or release.get("authorization", {}).get("scored_screen_execution")
        is not True
        or any(
            release.get("authorization", {}).get(key) is not False
            for key in (
                "qualification_execution",
                "bounded_tool_execution",
                "pydantic_ai_execution",
                "acl_execution",
                "automatic_retry",
            )
        )
    ):
        raise RuntimeError("Release scope or authorization changed")
    return release


def preflight_result(ctx: Mapping[str, Any], release: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "gate": "first-batch-release-preflight",
        "campaign_record_sha256": EXPECTED_CAMPAIGN_RECORD_SHA256,
        "release_record_sha256": release["record_sha256"],
        "release_file_sha256": file_sha256(ctx["release_path"]),
        "runner_script_sha256": file_sha256(Path(__file__)),
        "batch_id": EXPECTED_BATCH_ID,
        "candidate": EXPECTED_MODEL_NAME,
        "provider_version": ctx["provider_version"],
        "provider_digest": ctx["model"].payload["provider_digest"],
        "observations": EXPECTED_OBSERVATION_COUNT,
        "levels": {"L0": 9, "L1": 5},
        "authorization": release["authorization"],
        "inference_performed": False,
        "loaded_models": [],
    }


def execute(ctx: Mapping[str, Any], release: Mapping[str, Any]) -> dict[str, Any]:
    if ctx["completion_path"].exists():
        raise RuntimeError("This batch already completed")
    if ctx["failure_path"].exists() or ctx["start_path"].exists():
        raise RuntimeError("This batch already started; automatic replay is forbidden")

    start = sealed_plain({
        "schema_version": "benchmark-lab-batch-start:v1",
        "started_at_utc": utc_now(),
        "campaign_record_sha256": EXPECTED_CAMPAIGN_RECORD_SHA256,
        "release_record_sha256": release["record_sha256"],
        "runner_script_sha256": file_sha256(Path(__file__)),
        "batch_id": EXPECTED_BATCH_ID,
    })
    write_exclusive(ctx["start_path"], start)

    try:
        registry = EvaluatorRegistry()
        register_shared_battery_evaluators(registry)
        router = ProfileRouter(ctx["case_profiles"], ctx["drivers"])
        driver_binding = DriverBinding(
            ROUTER_ID,
            file_sha256(Path(__file__)),
            router,
        )
        harness_source = {
            "campaign_record_sha256": EXPECTED_CAMPAIGN_RECORD_SHA256,
            "campaign_file_sha256": EXPECTED_CAMPAIGN_FILE_SHA256,
            "release_record_sha256": release["record_sha256"],
            "runner_script_sha256": file_sha256(Path(__file__)),
            "profile_routes": dict(sorted(ctx["case_profiles"].items())),
            "accepted_harness_sources": ctx["campaign"]["harness_sources"],
        }
        runs = []
        for pack_id, run_id in (
            ("shared-l0-core", "screen-qwen35-9b-l0-v2"),
            ("shared-l1-core", "screen-qwen35-9b-l1-v2"),
        ):
            item = ctx["packs"][pack_id]
            profiles = {
                str(case["requirements"]["configuration_profile"])
                for case in item["pack"].cases
            }
            run = run_v2_repetitions(
                run_id=run_id,
                repetition_phase="screen",
                pack_source=item["source"],
                pack_source_locator=item["source_locator"],
                host=ctx["host"],
                runtime=ctx["runtime"],
                model=ctx["model"],
                configuration_bindings={
                    profile: ctx["bindings"][profile]
                    for profile in profiles
                },
                evaluator_registry=registry,
                driver_binding=driver_binding,
                evidence_store=ctx["store"],
                harness_source=harness_source,
                asset_loader=asset_loader(ctx["bench"]),
            )
            report = aggregate_repeated_run(f"aggregate-{run_id}", run)
            persist_aggregate_report(report, ctx["store"])
            runs.append((item["pack"].level, run, report))

        cases = [record for _, run, _ in runs for record in run.case_results]
        evaluations = [
            record for _, run, _ in runs for record in run.evaluation_results
        ]
        if len(cases) != EXPECTED_OBSERVATION_COUNT:
            raise RuntimeError("Observed case count differs from release")
        loaded = api_json(ctx["base_uri"], "/api/ps").get("models", [])
        if loaded:
            raise RuntimeError("Ollama retained a model after the released batch")

        score = sum(float(record.payload["score"]) for record in evaluations)
        maximum = sum(
            float(record.payload["maximum_score"]) for record in evaluations
        )
        verdicts = {
            verdict: sum(
                record.payload["verdict"] == verdict for record in evaluations
            )
            for verdict in ("pass", "fail", "review")
        }
        hard_failures = sorted({
            failure
            for record in evaluations
            for failure in record.payload["hard_failures"]
        })
        completion = sealed_plain({
            "schema_version": "benchmark-lab-batch-completion:v1",
            "completed_at_utc": utc_now(),
            "campaign_record_sha256": EXPECTED_CAMPAIGN_RECORD_SHA256,
            "release_record_sha256": release["record_sha256"],
            "start_record_sha256": start["record_sha256"],
            "batch_id": EXPECTED_BATCH_ID,
            "candidate": ctx["model"].reference.to_dict(),
            "observed_cases": len(cases),
            "evaluation_count": len(evaluations),
            "verdict_counts": verdicts,
            "hard_failures": hard_failures,
            "score": score,
            "maximum_score": maximum,
            "score_fraction": score / maximum if maximum else None,
            "runs": [
                {
                    "level": level,
                    "manifest": run.manifest.reference.to_dict(),
                    "aggregate_report": report.reference.to_dict(),
                    "case_results": [
                        record.reference.to_dict() for record in run.case_results
                    ],
                    "evaluation_results": [
                        record.reference.to_dict()
                        for record in run.evaluation_results
                    ],
                }
                for level, run, report in runs
            ],
            "loaded_models_after": [],
            "automatic_retry_used": False,
        })
        write_exclusive(ctx["completion_path"], completion)
        return {
            "status": "PASS",
            "gate": "first-supervised-scored-batch",
            "batch_id": EXPECTED_BATCH_ID,
            "candidate": EXPECTED_MODEL_NAME,
            "observed_cases": len(cases),
            "verdict_counts": verdicts,
            "hard_failures": hard_failures,
            "score": score,
            "maximum_score": maximum,
            "score_fraction": completion["score_fraction"],
            "completion_record_sha256": completion["record_sha256"],
            "completion_file_sha256": file_sha256(ctx["completion_path"]),
            "loaded_models": [],
        }
    except Exception as exc:
        try:
            loaded = api_json(ctx["base_uri"], "/api/ps").get("models", [])
        except Exception as provider_exc:
            loaded = [{"inspection_error": str(provider_exc)}]
        failure = sealed_plain({
            "schema_version": "benchmark-lab-batch-failure:v1",
            "failed_at_utc": utc_now(),
            "campaign_record_sha256": EXPECTED_CAMPAIGN_RECORD_SHA256,
            "release_record_sha256": release["record_sha256"],
            "start_record_sha256": start["record_sha256"],
            "batch_id": EXPECTED_BATCH_ID,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "loaded_models_observed": loaded,
            "automatic_retry_used": False,
        })
        write_exclusive(ctx["failure_path"], failure)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("seal-release", "execute"))
    parser.add_argument("benchmark_root", type=Path)
    args = parser.parse_args()
    ctx = prepare(args.benchmark_root.resolve(strict=True))
    release = load_or_create_release(ctx)
    result = (
        preflight_result(ctx, release)
        if args.mode == "seal-release"
        else execute(ctx, release)
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
