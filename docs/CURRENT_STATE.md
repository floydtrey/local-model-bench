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
- `docs/V2_ORCHESTRATOR.md` — BL-8A pre-run closure, execution-binding, dispatch, and evidence-persistence contract.

## Accepted construction checkpoints

### BL-1 — V1 historical baseline

V1 is frozen at `4a023c8230365c3098a6dff71fa9623cac059cdd`. Historical configs, suites, results, validation packets, and runtime assumptions remain historical evidence and are not silently reinterpreted as V2 qualification artifacts.

### BL-2 — V2 identity/evidence contracts

Complete. V2 uses content-addressed immutable evidence with separate logical IDs and exact SHA-256 identities. Host, runtime, model, effective config, benchmark input, evaluator, trial, manifest, case result, evaluation result, tool/intrinsic traces, execution bindings, and containment executions are distinct record types.

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

Construction contract is complete in:

- `src/localbench/v2/containment.py`;
- `src/localbench/v2/process_custody.py`;
- `src/localbench/v2/validation_adapter.py`;
- `schemas/v2/containment-policy.schema.json`;
- `schemas/v2/containment-execution.schema.json`;
- `tests/test_v2_containment.py`;
- `tests/test_v2_process_custody.py`;
- `docs/CONTAINMENT_ENFORCEMENT.md`.

Accepted properties:

- containment policy has a deterministic SHA-256 and includes wall time, max attempts, network policy, process-custody strength, workspace/assessor isolation requirements, exact write-scope overlay, and optional output/memory limits;
- backends separately advertise only the containment capabilities they can prove;
- preflight blocks execution when any required capability is absent or weaker than policy, with no warning-only downgrade path;
- max attempts are enforced before another backend execution;
- containment executions are first-class V2 evidence and omit disposable absolute workspace paths from command identity;
- historical `real-tasks-v1` packets are adapted by exact source SHA-256 rather than rewritten, and remain unresolved until an explicit V2 writable-path overlay is supplied;
- `NativeSubprocessBackend` remains deliberately weak and does not claim security-boundary properties it lacks;
- `StrictProcessBackend` provides a disposable workspace, authorized-change promotion, output limiting, wall-time enforcement, and process cleanup/custody mechanics;
- `workspace_write_scope=true` for that backend means only declared changed paths are promoted into the governed original workspace;
- `workspace_isolation=false` because the subprocess can still access host paths outside its disposable workspace; a deterministic regression test proves this limitation using a temporary external path;
- `network=disabled` / `provider_only` are not enforced by this backend and therefore fail preflight;
- memory limiting is not enforced and therefore fails preflight when required;
- Windows Job Objects support the backend's `strict` process-custody claim on Windows; POSIX process groups are advertised only as `best_effort` rather than an inescapable security boundary;
- `StrictAssessorBackend` validates assessor staging order but advertises `assessor_isolation=false`, because staging order alone is not OS-level isolation.

BL-7 construction acceptance means **unenforced policy declarations cannot become qualification claims**. It does not mean the current laptop or new tower already has the network/filesystem/assessor isolation backend required by strict real-task policies. Those policies remain blocked until the intended host has a backend whose measured capabilities satisfy them.

### BL-8A — V2 runner / orchestrator

Construction complete in:

- `src/localbench/v2/orchestrator.py`;
- BL-8A additions to `src/localbench/v2/contracts.py`, `records.py`, and `__init__.py`;
- `schemas/v2/execution-binding.schema.json`;
- `schemas/v2/intrinsic-execution-trace.schema.json`;
- BL-8A additions to V2 evidence/qualification schemas;
- `tests/test_v2_orchestrator.py`;
- `docs/V2_ORCHESTRATOR.md`.

Accepted properties:

- one engineering trial per case is planned for BL-8A; repetition/aggregation remains BL-8B work;
- Benchmark Pack, exact EffectiveRuntimeConfig, evaluator identities, TrialIdentity, ExecutionBinding, and RunManifest are all sealed and persisted before any driver call;
- ExecutionBinding records the driver implementation identity, execution mode, exact L2 workspace scope, digest-verified context delivery, concrete tool mapping, and containment preflight identity when applicable;
- context asset bytes are verified against declared SHA-256 before execution and private source locators are not exposed to the candidate;
- L0/L1 use a normalized tool-free intrinsic execution trace;
- L2 preserves portable Benchmark Pack capability `bounded-files-v1` while explicitly sealing its mapping to concrete BL-6 surface `lab-bounded-files:v1` and exact tool-schema SHA-256;
- the original Benchmark Pack is not rewritten to contain the concrete harness ID; the concrete case projection exists only at the BL-6 call boundary;
- L2 exact readable/writable paths are sealed before bounded-tool execution and absolute disposable workspace location is not durable behavioral identity;
- CaseResult references immutable execution evidence and the pre-run ExecutionBinding;
- evaluators are resolved through the independent EvaluatorRegistry and receive only declared supplemental evidence types;
- `EvidenceStore` is content-addressed and append-only: identical re-persistence is idempotent while conflicting bytes are rejected;
- failed subprocess containment preflight blocks before manifest/driver execution;
- successful subprocess preflight may be sealed as a plan, but the runner still refuses a direct in-process driver fallback because BL-8A does not yet have a model-driver adapter that routes actual model turns through BL-7.

No real model/provider call occurred during BL-8A construction.

## Deterministic regression gate

`.github/workflows/deterministic-tests.yml` runs the complete repository unittest suite on Python 3.12 for both `windows-latest` and `ubuntu-latest`.

BL-7 capability-boundary checkpoint `89f7b136d539619a26cd3398b0a5023c8c432142` passed in GitHub Actions run `34578249312` on both platforms.

BL-8A hardened implementation/test checkpoint `f6798b833ccc3cd0bcfeaa3025583737d6de2848` passed in GitHub Actions run `34580157055` on both Windows and Ubuntu. This includes pre-run manifest closure, context-asset privacy/digest checks, portable-to-concrete L2 tool mapping, bounded read/write execution, append-only evidence storage, containment-preflight refusal, and the regression proving successful subprocess preflight cannot fall back to a direct in-process driver call.

The regression gate does not start Ollama, load a model, execute ACL, or make scored model requests.

## Current implementation position

- BL-1: **COMPLETE**
- BL-2: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**
- BL-3: **IMPLEMENTED; NEW-TOWER CAPTURE/REPEATABILITY PENDING**
- BL-4: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**
- BL-5A: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**
- BL-5B: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**
- BL-6: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**
- BL-7: **CONSTRUCTION COMPLETE; STRICT HOST ISOLATION BACKEND QUALIFICATION/IMPLEMENTATION STILL PENDING FOR POLICIES THAT REQUIRE IT**
- BL-8A: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**
- BL-8B: **NEXT — REPETITION, AGGREGATION, AND REPORTING**

No V2 real-model run, real scored benchmark case, broad candidate campaign, or ACL cross-harness execution has occurred.

## Stop boundary for this checkpoint

This checkpoint stops after BL-8A construction acceptance.

Do not create the real benchmark battery or run candidate models yet. Per `docs/POST_BL7_CONSTRUCTION_SEQUENCE.md`, the next bounded task is **BL-8B repetition, aggregation, and reporting using synthetic deterministic evidence only**, followed by the synthetic end-to-end construction acceptance gate.
