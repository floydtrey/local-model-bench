# Benchmark Lab Current State

**Last updated:** 2026-09-11

**Repository:** `floydtrey/local-model-bench`

**Active construction branch:** `architecture/benchmark-lab-v2`

**Model execution:** `DISABLED FOR V2 CONSTRUCTION`

## Current purpose

Benchmark Lab V2 is being constructed as an independent qualification system that can distinguish:

1. intrinsic model/runtime capability;
2. capability retained through a lab-owned bounded tool harness;
3. fitness through the actual ACL harness once ACL permits supervised execution; and
4. role-specific fitness for work such as planning, coding, verification, observation, and content/video generation.

Benchmark Lab does not grant ACL authority and must not depend on ACL being operational to run its own model or harness tests.

## Accepted construction checkpoints

### Construction plan

`docs/BENCHMARK_LAB_V2_PLAN.md` defines the approved architecture, evidence requirements, capability levels, cross-layer comparison model, role qualification policy, and ordered construction sequence.

### BL-1 — V1 historical baseline

Local Model Bench V1 is frozen at:

`4a023c8230365c3098a6dff71fa9623cac059cdd`

`docs/V1_BASELINE.md` governs preservation of historical V1 configs, suites, results, experiments, validation packets, and runtime assumptions.

Historical V1 artifacts are not current V2 contracts and must not be silently rewritten into V2 semantics.

### BL-2 — V2 identity and evidence contracts

The V2 evidence foundation is defined in:

- `src/localbench/v2/contracts.py`;
- `src/localbench/v2/records.py`;
- `schemas/v2/evidence-record.schema.json`;
- `schemas/v2/qualification-record.schema.json`;
- `docs/V2_EVIDENCE_CONTRACTS.md`.

Accepted design properties:

- logical/operator IDs are separate from cryptographic evidence identity;
- canonical JSON preserves explicit nulls and rejects NaN/Infinity;
- sealed evidence payloads are recursively immutable in memory;
- references fail closed on record-type mismatch;
- HostProfile, RuntimeProfile, ModelIdentity, EffectiveRuntimeConfig, BenchmarkInput, EvaluatorIdentity, TrialIdentity, RunManifest, CaseResult, and EvaluationResult are separate versioned records;
- RunManifest is an immutable pre-run experiment definition rather than mutable progress state;
- hard failures remain separate from weighted evaluation score;
- host observations include an exact observation digest and a stable `facts_sha256` projection.

Direct canonicalization/immutability and record-chain smoke checks were exercised in an isolated Python runtime during construction. The full repository regression suite has **not** been claimed from this environment because its sandbox could not resolve GitHub to clone the branch; run that deterministic suite from a local checkout before treating the construction branch as fully regression-qualified.

### BL-3 — host qualification implementation

The host collector is implemented at `src/localbench/v2/host.py` with deterministic fake-probe coverage in `tests/test_v2_host.py`.

It does not contact a model or model provider. It captures OS, CPU, RAM, GPU/VRAM/driver, storage, Python, available NVIDIA/CUDA runtime evidence, and Windows power-scheme information while leaving unsupported measurements unknown/null.

Raw host qualification defaults to ignored `local-state/` storage. The public repository does not require host profiles to be committed.

`docs/HOST_QUALIFICATION.md` defines the capture and repeatability gate.

**BL-3 intended-host acceptance remains pending** until the new tower is set up, the collector is run twice there, and the stable host facts fingerprint is confirmed.

## Construction rules

- No local-model/provider calls are required to design or implement V2 contracts.
- No Ollama chat/completion requests are part of construction-only tasks.
- No ACL execution or authority state is changed by Benchmark Lab work.
- New semantics use versioned V2 artifacts rather than changing V1 evidence in place.
- Unknown hardware/provider facts remain unknown until measured on the intended host.
- Qualification-grade results must bind exact host, runtime, model, effective settings, benchmark inputs, evaluator, and trial identity.
- Tool-capable V2 execution will use a new versioned execution/event contract rather than stretching V1 `ProviderResponse` semantics.
- Real-task policy declarations become qualification-grade only when the execution environment actually enforces the declared limits.
- Observation evidence is not itself a qualification/approval decision.

## Current implementation position

BL-1 — freeze and govern V1 baseline: **COMPLETE**.

BL-2 — define V2 identity and evidence contracts: **IMPLEMENTED; LOCAL FULL-SUITE REGRESSION PENDING**.

BL-3 — implement host qualification: **IMPLEMENTED; NEW-TOWER CAPTURE/REPEATABILITY GATE PENDING**.

BL-4 — materialize and seal effective runtime configuration: **NEXT CONSTRUCTION TASK**.

No V2 model run or tool-harness execution has occurred.

## Immediate next construction gate

BL-4 may be designed and tested on the laptop because it resolves configuration without contacting a model. It must:

- resolve behavior-bearing runtime/model settings before execution;
- make provider defaults explicit where they materially affect behavior;
- bind the exact RuntimeProfile and ModelIdentity references;
- bind the intended tool surface and execution limits;
- reject ambiguous/incomplete scored configurations rather than silently inheriting unknown provider behavior;
- preserve V1 configuration semantics only for historical V1 reproduction.

No scored V2 execution may begin until the host/runtime/model/config evidence required by the selected benchmark level is actually qualified.
