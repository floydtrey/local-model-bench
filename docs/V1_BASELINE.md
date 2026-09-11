# Local Model Bench V1 Baseline

**Status:** frozen historical baseline

**Repository:** `floydtrey/local-model-bench`

**Canonical V1 commit:** `4a023c8230365c3098a6dff71fa9623cac059cdd`

**V2 construction branch:** `architecture/benchmark-lab-v2`

## Purpose

This document freezes the repository state immediately before Benchmark Lab V2 construction began.

The V1 baseline remains valid historical evidence for the experiments it performed. Benchmark Lab V2 must not silently reinterpret, rewrite, migrate, or normalize V1 artifacts in a way that makes prior runs appear to have been produced under V2 contracts.

## Frozen V1 surface

The canonical V1 commit includes the existing:

- `src/localbench/` prompt benchmark runner and provider adapters;
- `configs/` model/runtime configurations;
- `suites/` prompt benchmark suites;
- `schemas/` V1 JSON schemas;
- `validation-packets/real-tasks-v1/` disposable real-task fixtures and assessor material;
- `results/` committed historical results;
- `experiments/` exploratory material;
- PowerShell bootstrap, run, watcher, model-pull, and validation-workspace scripts;
- V1 unit/integration tests.

## Preservation rules

1. V1 results remain attributable to the exact V1 code/config/suite bytes that produced them.
2. Existing V1 result files must not be rewritten into a V2 shape in place.
3. Existing V1 suites/configs may be reused as historical regression inputs, but any changed semantics require a new V2 artifact rather than mutation of the V1 source.
4. Mine Tracker/Vera paths and laptop-era assumptions in historical configs are historical facts. They may be documented as obsolete for current V2 use, but they are not deleted merely to make the old experiment look current.
5. New qualification-grade schemas, manifests, host profiles, effective runtime configurations, tool execution records, evaluators, and role scorecards must be versioned as V2 artifacts.
6. A comparison between V1 and V2 must identify both contract generations explicitly.

## V1 capabilities worth preserving in V2

The V1 code already demonstrates useful patterns that V2 should retain where appropriate:

- deterministic model/suite/case ordering;
- config and suite hashing;
- normalized stored inputs;
- atomic result writes;
- crash-safe resume checks;
- captured retry attempts;
- provider/runtime/model metadata;
- raw request/response/token/timing evidence;
- deterministic evaluation separated from provider transport success;
- fresh archived real-task workspaces;
- hidden assessor material and hard-failure scoring.

Preserving these behaviors does not require preserving their V1 schemas or treating their old assumptions as current architecture.

## V2 boundary

The first V2-only commit is the Benchmark Lab V2 construction plan at:

`cdeb15d9fa25559e5f806eb417bc2adb4f782163`

Everything after the canonical V1 commit on `architecture/benchmark-lab-v2` is V2 construction work unless explicitly identified as a correction to historical documentation.
