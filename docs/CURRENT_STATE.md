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

## Accepted checkpoints

### Construction plan

`docs/BENCHMARK_LAB_V2_PLAN.md` defines the approved architecture, evidence requirements, capability levels, cross-layer comparison model, role qualification policy, and ordered construction sequence.

### V1 historical baseline

Local Model Bench V1 is frozen at:

`4a023c8230365c3098a6dff71fa9623cac059cdd`

`docs/V1_BASELINE.md` governs preservation of historical V1 configs, suites, results, experiments, validation packets, and runtime assumptions.

Historical V1 artifacts are not current V2 contracts and must not be silently rewritten into V2 semantics.

## Construction rules

- No local-model/provider calls are required to design or implement V2 contracts.
- No Ollama chat/completion requests are part of construction-only tasks.
- No ACL execution or authority state is changed by Benchmark Lab work.
- New semantics use versioned V2 artifacts rather than changing V1 evidence in place.
- Unknown hardware/provider facts remain unknown until measured on the intended host.
- Qualification-grade results must eventually bind exact host, runtime, model, effective settings, benchmark inputs, evaluator, and trial identity.
- Tool-capable V2 execution will use a new versioned execution/event contract rather than stretching V1 `ProviderResponse` semantics.
- Real-task policy declarations become qualification-grade only when the execution environment actually enforces the declared limits.

## Current implementation position

BL-1 — freeze and govern the V1 baseline: **COMPLETE**.

BL-2 — define V2 identity and evidence contracts: **NEXT**.

No V2 model run, host qualification run, or tool-harness execution has occurred.

## Immediate next gate

Define the provider-neutral V2 evidence identities and canonical digest rules before modifying the runner:

- host profile;
- runtime profile;
- model identity;
- effective runtime configuration;
- benchmark input identity;
- evaluator identity;
- trial identity;
- run manifest identity.

The contracts must support unknown/null measured facts without inventing values, distinguish logical IDs from cryptographic digests, and remain independent of ACL-specific authority contracts.
