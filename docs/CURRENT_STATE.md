# Benchmark Lab Current State

**Last updated:** 2026-09-11

**Repository:** `floydtrey/local-model-bench`

**Active construction branch:** `architecture/benchmark-lab-v2`

**Model execution:** `DISABLED FOR V2 CONSTRUCTION`

## Current purpose

Benchmark Lab V2 is an independent qualification system intended to distinguish:

1. intrinsic model/runtime capability;
2. capability retained through a lab-owned bounded tool harness;
3. fitness through the actual ACL harness after ACL separately permits supervised execution; and
4. role-specific fitness for planning, coding, verification, observation, content/video generation, and future specialized work.

Benchmark Lab does not grant ACL authority.

## Authoritative construction documents

- `docs/BENCHMARK_LAB_V2_PLAN.md` — original V2 architecture and evidence goals.
- `docs/BL5_FOUNDATION_PLAN.md` — BL-5A/BL-5B measuring-instrument split.
- `docs/BOUNDED_TOOL_HARNESS.md` — BL-6 neutral tool boundary.
- `docs/CONTAINMENT_ENFORCEMENT.md` — BL-7 containment and fail-closed enforcement semantics.
- `docs/POST_BL7_CONSTRUCTION_SEQUENCE.md` — accepted refinement that completes the measuring instrument before real benchmark design/model runs.

## Accepted construction checkpoints

### BL-1 — V1 historical baseline

V1 is frozen at:

`4a023c8230365c3098a6dff71fa9623cac059cdd`

Historical configs, suites, results, validation packets, and runtime assumptions remain historical evidence and are not silently reinterpreted as V2 qualification artifacts.

### BL-2 — V2 identity/evidence contracts

Complete. V2 uses content-addressed immutable evidence with separate logical IDs and exact SHA-256 identities. Host, runtime, model, effective config, benchmark input, evaluator, trial, manifest, case result, evaluation result, BL-6 tool traces, and BL-7 containment executions are distinct record types.

### BL-3 — host qualification

Implementation complete. Intended-host acceptance remains pending until the new tower is configured and two captures confirm the same stable host-facts fingerprint.

### BL-4 — effective runtime configuration

Complete. Behavior-bearing settings are resolved and sealed before execution; strict comparisons fail closed on unresolved/degraded mappings or incompatible context/tool requirements.

### BL-5A — Benchmark Pack / Case Definition contract

Complete. Benchmark Packs are versioned/content-addressed, provider-neutral, support private external fixtures by digest, bind required tool/evaluator contracts, and declare repetition policy before execution.

### BL-5B — evaluator framework

Complete. Evaluators are versioned/content-addressed, declare consumed evidence, return normalized deterministic checks, keep hard failures separate from weighted score, and fail closed on undeclared or incoherent output.

### BL-6 — neutral bounded-tool harness V1

Complete. `lab-bounded-files:v1` exposes only exact-scope `read_file` and `write_file`, enforces traversal/link/hardlink/stale-write/tool-call protections, and produces deterministic content-addressed tool execution traces. BL-6 does not claim OS sandbox containment.

### BL-7 — containment and execution-limit enforcement

Construction contract complete in:

- `src/localbench/v2/containment.py`;
- `src/localbench/v2/validation_adapter.py`;
- `schemas/v2/containment-execution.schema.json`;
- `tests/test_v2_containment.py`;
- `docs/CONTAINMENT_ENFORCEMENT.md`.

Accepted properties:

- containment policy has a deterministic SHA-256 and includes wall time, max attempts, network policy, process-custody strength, workspace/assessor isolation, exact write-scope overlay, and optional output/memory limits;
- backends separately advertise the containment capabilities they can prove;
- preflight blocks execution when any required capability is absent or weaker than the policy;
- there is no warning-only or silent downgrade from strict qualification semantics;
- max attempts are enforced before a backend receives another execution;
- containment executions are first-class V2 evidence and omit the disposable absolute workspace path from command identity;
- assessor staging fails closed if assessment material was included in the candidate workspace or the candidate has not reached a terminal state;
- the historical `real-tasks-v1` packet is adapted by exact source SHA-256 rather than rewritten;
- because the old packet lacks an exact machine-readable write allowlist, its V2 projection remains unresolved until an explicit V2 write-scope overlay is supplied;
- the built-in native subprocess backend intentionally advertises only wall timeout, best-effort process-tree cleanup, and task-allowed network behavior;
- native execution does **not** claim disabled-network isolation, strict process custody, filesystem/write confinement, assessor isolation, output limiting, or memory limiting;
- therefore historical tasks requiring `network=disabled` correctly fail containment preflight on the native backend rather than being mislabeled as qualification-grade.

BL-7 construction acceptance means **unenforced policy declarations cannot become qualification claims**. It does not mean the current laptop/new tower already has a strict network/filesystem sandbox backend. Before real-task qualification, the intended host must provide and qualify a backend whose measured capabilities satisfy the selected containment policy.

No real model/provider call occurred during BL-7 construction.

## Deterministic regression gate

`.github/workflows/deterministic-tests.yml` runs the complete repository unittest suite on Python 3.12 for both `windows-latest` and `ubuntu-latest`.

At post-BL-7 construction-sequence commit:

`1247f1495b218ee338b37514496e06eadd10542f`

GitHub Actions run `34577763460` passed the complete deterministic suite on both Windows and Ubuntu, including BL-7 containment, legacy-packet adaptation, BL-6 harness, evaluator, configuration, host, and historical V1 regression tests.

The regression gate does not start Ollama, load a model, execute ACL, or make scored model requests.

## Current implementation position

- BL-1: **COMPLETE**
- BL-2: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**
- BL-3: **IMPLEMENTED; NEW-TOWER CAPTURE/REPEATABILITY PENDING**
- BL-4: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**
- BL-5A: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**
- BL-5B: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**
- BL-6: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**
- BL-7: **CONSTRUCTION COMPLETE; STRICT INTENDED-HOST CONTAINMENT BACKEND QUALIFICATION PENDING**
- BL-8A: **NEXT — V2 RUNNER/ORCHESTRATOR**

No V2 real-model run, real scored benchmark case, broad candidate campaign, or ACL cross-harness execution has occurred.

## Stop boundary for this checkpoint

This checkpoint stops after BL-7 construction acceptance.

Do not create the real benchmark battery or run candidate models yet. Per `docs/POST_BL7_CONSTRUCTION_SEQUENCE.md`, the next bounded task is **BL-8A V2 runner/orchestrator using deterministic fake drivers only**, followed by BL-8B aggregation/reporting and a synthetic end-to-end construction acceptance gate.
