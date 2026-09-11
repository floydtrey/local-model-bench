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

`docs/BL5_FOUNDATION_PLAN.md` refines the original BL-5 construction task into BL-5A Benchmark Pack/Case Definition contracts followed by BL-5B evaluator infrastructure. Real scored benchmark content remains after those measuring-instrument gates.

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
- each TrialIdentity binds an exact benchmark case and exact EffectiveRuntimeConfig before execution;
- hard failures remain separate from weighted evaluation score;
- host observations include an exact observation digest and a stable `facts_sha256` projection.

### BL-3 — host qualification implementation

The host collector is implemented at `src/localbench/v2/host.py` with deterministic fake-probe coverage in `tests/test_v2_host.py`.

It does not contact a model or model provider. It captures OS, CPU, RAM, GPU/VRAM/driver, storage, Python, available NVIDIA/CUDA runtime evidence, and Windows power-scheme information while leaving unsupported measurements unknown/null.

Raw host qualification defaults to ignored `local-state/` storage. The public repository does not require host profiles to be committed.

`docs/HOST_QUALIFICATION.md` defines the capture and repeatability gate.

**BL-3 intended-host acceptance remains pending** until the new tower is set up, the collector is run twice there, and the stable host facts fingerprint is confirmed.

### BL-4 — effective runtime configuration sealing

The provider-neutral effective configuration resolver is implemented in:

- `src/localbench/v2/configuration.py`;
- `schemas/v2/effective-config-spec.schema.json`;
- `docs/EFFECTIVE_CONFIGURATION.md`;
- `tests/test_v2_configuration.py`.

Accepted design properties:

- behavior-bearing configuration is materialized before scored execution;
- context target, output limit, response format, sampling controls, timeout, retries, concurrency, model residency, network policy, and tool surface are explicit or resolved to recorded lab defaults;
- defaults applied by the lab are recorded in the sealed evidence rather than remaining hidden;
- RuntimeProfile and ModelIdentity are bound by typed evidence references;
- provider/backend adapters must supply the effective provider request that was resolved from the canonical configuration;
- strict comparison rejects degraded adapter mappings, unresolved tool schemas, and requested context beyond a known declared model limit;
- exploratory configuration may retain explicit deviations without being misrepresented as strict apples-to-apples evidence;
- case-specific configuration cannot be merged silently at request time because TrialIdentity binds the exact EffectiveRuntimeConfig before execution.

No provider call is made by the configuration resolver.

### BL-5A — Benchmark Pack / Case Definition contract

The portable benchmark-definition contract is implemented in:

- `src/localbench/v2/benchmark_pack.py`;
- `schemas/v2/benchmark-pack.schema.json`;
- `docs/BENCHMARK_PACK_CONTRACT.md`;
- `tests/test_v2_benchmark_pack.py`.

Accepted design properties:

- Benchmark Packs have explicit schema, pack ID, pack version, and one capability level;
- exact source bytes receive `source_sha256` for reproduction identity;
- normalized behavior-bearing content receives `semantic_sha256` so reporting labels and file locators do not masquerade as behavioral identity;
- external context fixtures are content-addressed by SHA-256 while locators remain operational metadata;
- L0 forbids external context and tools; L1 may use controlled context but remains tool-free; L2-L4 may declare provider-neutral tool-surface requirements;
- case requirements reference provider-neutral configuration profiles, response contracts, minimum context requirements, and tool surfaces rather than provider-specific request options;
- evaluator contracts and hard-failure rules are references only; evaluator implementation remains BL-5B work;
- screening and qualification repetition counts are declarative case semantics;
- unknown contract fields fail closed;
- loaded packs can become existing V2 `benchmark_input` evidence without automatically persisting a private local source path;
- synthetic contract fixtures are engineering tests only and are not scored benchmark content.

BL-5A does not implement evaluator logic, execute a model, or create the real shared capability battery.

## Deterministic regression gate

`.github/workflows/deterministic-tests.yml` runs the complete repository unittest suite on Python 3.12 for both `windows-latest` and `ubuntu-latest` and retains the unittest transcript as a short-lived workflow artifact.

The first cross-platform run exposed an existing V1 portability defect: the Markdown suite heading parser did not accept CRLF line endings produced by Windows checkout. The parser was changed narrowly to accept the optional carriage return and `tests/test_markdown_crlf.py` now preserves that behavior as a regression case.

At BL-5A code/schema commit:

`8722e413e2ee14645d898187be52e6c7ead5a887`

GitHub Actions run `34573915749` passed the complete deterministic suite on both Windows and Ubuntu, including the Benchmark Pack V2 contract tests.

This regression gate does not start Ollama, load a model, execute ACL, or make scored model requests.

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
- Engineering tests for Benchmark Lab itself may be added during construction; scored model benchmark content remains outside the current bounded step.

## Current implementation position

BL-1 — freeze and govern V1 baseline: **COMPLETE**.

BL-2 — define V2 identity and evidence contracts: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**.

BL-3 — implement host qualification: **IMPLEMENTED; NEW-TOWER CAPTURE/REPEATABILITY GATE PENDING**.

BL-4 — materialize and seal effective runtime configuration: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**.

BL-5A — Benchmark Pack / Case Definition contract: **COMPLETE; CROSS-PLATFORM REGRESSION PASSING**.

BL-5B — versioned evaluator framework: **NEXT CONSTRUCTION TASK**.

No V2 model run, scored benchmark case, or tool-harness execution has occurred.

## Stop boundary for this checkpoint

This checkpoint stops after BL-5A acceptance.

Do not create the real shared capability battery, implement the bounded tool harness, download/run candidate models, or begin ACL cross-harness testing as part of this checkpoint.

The next construction session must start from this document, `docs/BENCHMARK_LAB_V2_PLAN.md`, and `docs/BL5_FOUNDATION_PLAN.md`, verify branch/HEAD, and perform **BL-5B evaluator framework only** unless the plan is explicitly revised again.
