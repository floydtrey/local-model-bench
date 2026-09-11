# Benchmark Lab V2 Construction Plan

**Status:** approved construction plan; no V2 implementation started

**Repository:** `floydtrey/local-model-bench`

**Construction branch:** `architecture/benchmark-lab-v2`

**Purpose:** evolve the existing Local Model Bench into a reproducible qualification lab that can distinguish intrinsic model capability, standardized tool-harness fitness, ACL system fitness, and role-specific fitness without coupling the lab to ACL runtime authority or to one provider/model family.

## Governing objective

Benchmark Lab V2 must answer four different questions without collapsing them into one score:

1. **Model capability** — what can the model/runtime combination do intrinsically under a controlled prompt benchmark?
2. **Lab harness fitness** — how much of that capability survives a standardized, lab-owned bounded tool harness?
3. **ACL fitness** — how well does the same model/configuration perform through the actual ACL architecture once ACL reconstruction permits controlled execution?
4. **Role fitness** — which kinds of work is the model/configuration best suited to perform, such as Foreman/planning, coding, verification, observation, or content/video generation?

Benchmark Lab must be able to explain *why* performance changes between those layers. A final score without evidence about where capability was lost is insufficient.

## Relationship to ACL

Benchmark Lab remains an independent system.

It must not import ACL runtime authority, alter ACL execution state, or rely on ACL being operational in order to run model and harness benchmarks. It may later consume versioned ACL contracts, sanitized ACL-derived fixtures, and supervised ACL vertical-slice results as benchmark inputs/evidence.

ACL reconstruction currently requires provider/model/runtime settings to be sealed before authorization and prohibits real provider/model execution until its deterministic reconstruction acceptance gate passes. Benchmark Lab may be constructed and exercised independently in parallel. The same model cohort should later cross into the ACL supervised vertical slice so the lab and ACL results can be compared directly.

## Existing V1 assets to preserve

The current repository already contains useful engineering that should be retained unless a concrete V2 requirement demands a bounded change:

- provider separation for Ollama, OpenAI-compatible endpoints, and managed llama.cpp;
- deterministic model/suite/case ordering;
- exact config and suite hashing;
- normalized stored suite inputs;
- atomic case writes and resumable runs;
- retry-attempt capture;
- provider/runtime/model metadata capture;
- request/response/token/timing evidence;
- transport-vs-evaluation separation;
- deterministic evaluation reports;
- real-task validation packets using archived baselines and hidden assessor material;
- public regression tests for runner/provider/evaluator behavior;
- historical August 2026 benchmark results and planning experiments.

These assets are historical evidence and working foundations. They must not be silently rewritten so that old results appear to have been produced under V2 semantics.

## Historical-baseline rule

Existing V1 suites, configs, results, and experiments remain historically valid for what they measured at the time.

They may be clearly labeled as V1/historical, but they should not be mutated merely to fit new terminology or contracts. New V2 schemas, suites, evaluators, run manifests, and qualification records must be versioned separately.

Old Mine Tracker/Vera-specific paths, 4K laptop assumptions, and planning-contract experiments may remain as historical artifacts where they are needed to reproduce prior runs, but they must not define V2 architecture or current qualification policy.

## Core experimental model

V2 uses three primary execution layers followed by role qualification.

### Layer A — intrinsic capability

```text
Benchmark Lab
    -> inference runtime/provider
    -> model
```

Purpose: measure reasoning, coding, instruction following, structured output, context use, refusal, diagnosis, repair, and similar capabilities without a complex agent harness.

### Layer B — standardized bounded-tool capability

```text
Benchmark Lab
    -> lab-owned bounded tool harness
    -> inference runtime/provider
    -> model
    -> controlled lab tools
```

Purpose: determine whether the model can reliably operate through a neutral tool loop and how much raw capability is retained once tool schemas, multi-turn execution, limits, and tool-result handling are introduced.

### Layer C — ACL system fitness

```text
ACL supervised vertical slice
    -> ACL authority + context + provider binding + dispatch
    -> actual qualified ACL harness
    -> same model/runtime candidate
    -> bounded ACL tools
    -> independent verification
```

Purpose: measure the model as it would actually operate inside ACL and identify ACL-specific gains or losses relative to Layers A and B.

### Layer D — role qualification

After cross-layer comparison, the strongest candidates receive provisional role assignments and then run role-specific qualification suites. Role assignments are evidence-based and temporary; they are not embedded architectural identities.

## Candidate-retention policy

Benchmark Lab is intended to diagnose systems, not merely eliminate models quickly.

A low score alone is not normally grounds for early elimination. Plausible and intentionally unlikely candidates should continue from Layer A through Layer C when practical so that their performance deltas can reveal model limits, neutral-harness limits, or ACL-harness limits.

Early elimination is reserved for severe conditions such as:

- persistent inability to obey the required response/tool protocol;
- repeated authority or scope violations;
- inability to complete basic required capability tests;
- catastrophic instability or repeated runtime failure;
- resource demands that make the candidate unusable on the target host;
- absence of a mandatory capability such as required tool calling;
- security behavior that makes continued execution inappropriate.

Any elimination must be recorded with evidence and a specific reason.

## V2 identity and evidence principles

A result is not comparable merely because two runs use the same model name.

Every qualification-grade result must bind, as applicable:

- host profile identity;
- CPU and system-memory facts;
- GPU identity and VRAM;
- GPU driver and compute/runtime versions;
- operating system/build;
- Python/runtime versions;
- storage facts relevant to the run;
- inference backend/provider identity and version;
- model family/name;
- exact model artifact/digest when obtainable;
- quantization or precision;
- effective context configuration;
- generation/sampling settings;
- tool mode/tool-surface identity;
- benchmark harness source/version identity;
- exact suite/case bytes or digests;
- evaluator version/identity;
- sandbox/process-containment policy;
- repetition/trial identity.

Unknown facts must remain unknown. V2 must not estimate unavailable provider metadata and then present the estimate as measured evidence.

## Effective runtime configuration

Before a qualification run starts, Benchmark Lab must materialize the behavior-bearing effective configuration that will actually be used.

The effective configuration must make provider/runtime defaults visible rather than relying on hidden defaults when they can materially affect behavior. At minimum it should account for applicable settings such as:

- model artifact/tag/digest;
- provider/runtime;
- context window target;
- output/token limit;
- temperature;
- seed;
- top-p/top-k or equivalent sampling controls when set;
- structured-output mode;
- tool-calling mode;
- quantization/precision;
- concurrency;
- retry behavior;
- timeout limits;
- keep-alive/model-load behavior where relevant.

The effective configuration must be stored and hashed as evidence before scored work begins.

## Host qualification requirements

The current V1 host metadata is not sufficient for hardware/runtime comparison. V2 must introduce a host-qualification profile that captures enough evidence to explain performance and capacity.

At minimum, where measurable and applicable, capture:

- host profile ID;
- OS edition/version/build;
- CPU model and logical/physical core information;
- installed and available system RAM;
- GPU model(s);
- dedicated VRAM;
- GPU driver version;
- CUDA/ROCm/other applicable compute runtime versions;
- relevant inference backend version/build;
- Python version;
- storage device/volume and available space for model/result workloads;
- power/thermal mode when it can materially affect comparison;
- host-profile digest.

Host qualification should include non-destructive smoke checks proving that the recorded runtime can load and execute the intended class of workload before large benchmark campaigns begin.

## Telemetry requirements

V2 should collect enough telemetry to compare both quality and operational cost.

Desired measurements include, when available:

- wall-clock duration;
- prompt and output tokens;
- prompt-evaluation time;
- generation time;
- tokens/second;
- load time;
- retry count;
- tool-call count;
- tool failures;
- peak system RAM;
- peak VRAM;
- GPU utilization samples or summary;
- relevant CPU utilization summary;
- timeout/resource-limit events.

Telemetry must not contaminate the result by changing execution behavior unnecessarily. Unsupported metrics remain null/unknown rather than fabricated.

## Benchmark levels

V2 formalizes the capability ladder as follows.

### L0 — prompt-only model behavior

No external tools or reference files. Measures base instruction following, structured output, reasoning, coding knowledge, refusal, and similar intrinsic behavior.

### L1 — controlled context/evidence use

The candidate receives explicit controlled files, passages, or evidence and must reason over them. It cannot edit a workspace.

### L2 — bounded worker tools

The candidate operates through the lab-owned standardized bounded tool harness. Initial tool surface should emphasize exact authorized file read/write behavior and deterministic fixtures rather than a broad autonomous tool set.

### L3 — explicit development operations

Tests capabilities such as controlled Git/version-control operations only where a role actually requires them. L3 authority must never be inferred from L2 success.

### L4 — full system/harness qualification

A candidate is tested through the complete target harness/system contract, including resource limits, tool policy, validation, and exact runtime configuration. ACL system fitness is one important L4 implementation after ACL permits execution.

## Shared capability battery

All serious candidates should run a common core battery before role specialization.

The battery should include cases covering at least:

- instruction adherence;
- exact structured output;
- missing-context recognition;
- contradiction detection;
- correct ready-vs-blocked behavior;
- bounded planning/decomposition;
- code diagnosis;
- evidence-led repair reasoning;
- scope/authority boundaries;
- refusal of under-authorized destructive work;
- context use and traceability;
- malformed/ambiguous input handling;
- resource/output discipline.

Existing V1 cases may be retained as historical regression probes, but the V2 shared battery should use generic current contracts and versioned evaluators.

## Standardized bounded-tool harness

V2 requires a lab-owned tool harness that is deliberately smaller and simpler than ACL.

Its purpose is diagnostic isolation: if a model succeeds at L0/L1 but fails through this minimal harness, the failure is likely related to tool protocol or harness interaction rather than ACL-specific complexity.

Initial standardized tool surface should be narrow and deterministic. A recommended first version exposes only exact authorized file operations needed by disposable benchmark workspaces.

The harness must record a normalized event stream containing, as applicable:

- model request;
- model response;
- requested tool call;
- normalized tool arguments;
- tool authorization decision;
- tool result/error;
- retry/continuation events;
- terminal model output;
- limits reached;
- final workspace evidence.

The existing V1 text-oriented `ProviderResponse`/single-chat contract must not be stretched ambiguously to represent this. Introduce a versioned tool-capable execution/result contract.

## Real-task isolation and enforcement

The V1 real-task packet design is a strong foundation and should be preserved:

- exact archived baseline;
- fresh workspace per model/attempt;
- candidate-visible scope separated from assessor-only material;
- hidden assessor tests where appropriate;
- captured diff/transcript/test evidence;
- explicit authorized scope;
- hard-failure conditions.

V2 must strengthen enforcement. Policy declarations such as `network: disabled`, wall-time limits, attempt limits, and workspace scope are not sufficient unless the executing environment enforces them.

Qualification-grade execution must therefore enforce, as applicable:

- wall-clock limit;
- maximum attempts/retries;
- allowed workspace root;
- write scope;
- network policy;
- process custody/cleanup;
- tool-call limit;
- output/resource limits;
- assessor isolation.

## Evaluation architecture

V2 must move from one evaluator shaped around planning/task-set contracts to versioned evaluator types.

Each evaluator should declare:

- evaluator ID/version;
- expected result contract;
- deterministic checks;
- scored criteria;
- hard-failure conditions;
- whether human review is still required;
- evidence consumed.

Hard failures must be represented separately from weighted score. A high weighted score must never erase a disqualifying safety, scope, protocol, or assessor-test failure.

## Repetition and variance policy

Single runs are useful for broad screening but insufficient for final role qualification.

Recommended policy:

- broad candidate screen: one run per case, with a second run where results are suspicious or near a decision boundary;
- serious cross-harness comparison: repeat selected diagnostic cases;
- final role qualification: approximately 10-15 role tests, with important tests repeated three times where practical.

A typical final role campaign may therefore produce roughly 30-45 observations per model/role candidate.

V2 scoring/reporting should expose consistency and variance, not merely average score. A model that alternates between excellent and poor behavior may be less useful for unattended work than a slightly lower-scoring but highly stable model.

## Cross-layer comparison

Every serious candidate should eventually have comparable evidence across Layers A, B, and C.

Example conceptual record:

```text
Model/configuration X
  intrinsic capability:      84/100
  lab bounded-tool score:    79/100
  ACL supervised slice:      55/100
```

This pattern suggests a likely ACL/system integration loss.

Another model may show:

```text
Model/configuration Y
  intrinsic capability:      56/100
  lab bounded-tool score:    55/100
  ACL supervised slice:      57/100
```

This suggests the model itself is near its capability ceiling rather than the harness causing a major regression.

V2 should calculate and display diagnostic retention/delta metrics, but those metrics must not become simplistic automatic winner selection.

Recommended diagnostics:

- **Lab retention** — tool-harness performance relative to intrinsic baseline;
- **ACL retention** — ACL performance relative to intrinsic baseline;
- absolute score change between each layer;
- hard-failure changes between layers;
- retry/tool-call/resource changes between layers.

## Provisional role assignment

Role assignment happens only after enough cross-layer evidence exists.

Possible roles include:

- Foreman/planner;
- coding worker;
- verifier/reviewer;
- observer/monitor;
- content/video generation;
- future specialized roles.

Assignments should record both primary and secondary candidates where useful, for example:

```text
coding-worker-primary
coding-worker-secondary
verifier-primary
observer-primary
```

Role assignments are operational recommendations based on current evidence. They must not become permanent model dependencies in ACL or Benchmark Lab architecture.

## Role qualification suites

Role qualification should use a shared behavioral core plus role-specific tests rather than giving every role exactly the same battery.

Recommended structure:

- approximately 5 shared behavioral tests;
- approximately 10 role-specific tests;
- important cases repeated three times for final candidates.

### Coding worker

Emphasize:

- bug repair;
- bounded feature implementation;
- multi-file consistency;
- exact authorized scope;
- regression-test behavior;
- stale-write/conflict handling;
- debugging from evidence;
- completion evidence quality.

### Foreman/planner

Emphasize:

- requirement extraction;
- decomposition;
- dependency ordering;
- ready-vs-blocked decisions;
- missing-context recognition;
- context selection;
- bounded task creation;
- escalation discipline;
- refusal to invent absent requirements.

### Verifier/reviewer

Emphasize:

- defect detection;
- incomplete-test detection;
- unauthorized-change detection;
- evidence sufficiency;
- safety regression detection;
- correct acceptance/rejection;
- false-positive control.

### Observer/monitor

Emphasize:

- anomaly recognition;
- state-change detection;
- correlation;
- concise summarization;
- useful escalation;
- false-positive control;
- strict separation between observation and action authority.

### Content/video generation

Emphasize:

- factual fidelity;
- narrative coherence;
- hook/attention structure;
- audience adaptation;
- script organization;
- storyboard/shot/visual planning;
- consistency across a series;
- revision responsiveness;
- adherence to supplied facts and source material.

## Role scoring

Maintain both:

1. a shared capability score for cross-model comparison; and
2. role-specific scores with weights appropriate to the actual job.

Do not use one universal leaderboard to choose all roles.

For example, a coding-worker score may heavily weight implementation correctness, scope discipline, tests, and tool reliability, while an observer score may emphasize detection accuracy, concise reporting, and false-positive control.

## Operational trial phase

After role qualification, provisional winners may perform supervised real work.

Operational tasks produce additional evidence. Where useful and safe, sanitized reproducible versions of real tasks should be frozen into new Benchmark Lab regression cases so future challenger models can be evaluated against hard-won project experience.

Operational success does not bypass qualification evidence; it supplements it.

## Continuous challenger policy

No model permanently wins a role.

A new model, runtime version, quantization, provider adapter, or harness revision may enter the same qualification pipeline and challenge the incumbent.

Existing role assignments remain until evidence shows a challenger is materially better for the intended workload or the incumbent is no longer operationally acceptable.

## Public/private artifact policy

The repository is currently public, so V2 must explicitly distinguish publishable benchmark assets from potentially sensitive qualification evidence.

### Public by default when sanitized

- Benchmark Lab engine/source;
- schemas;
- generic benchmark suites;
- synthetic fixtures;
- sanitized validation packets;
- intentionally published aggregate results.

### Non-public by default

- ACL project snapshots;
- Knowledge Core material;
- private project prompts/context;
- raw transcripts containing private source material;
- production-derived fixtures not explicitly sanitized;
- private operational trial results;
- credentials/secrets of any kind.

V2 should support a result destination outside the public repository so safety does not depend on remembering not to `git add results`.

## Scorecard requirements

A final qualification report should be capable of presenting, where applicable:

- shared capability score;
- bounded-tool score;
- ACL/system score;
- hard-failure count;
- pass rate;
- repeated-run consistency/variance;
- retry rate;
- tool-call count/failure rate;
- authority/scope violations;
- execution duration;
- token usage;
- peak RAM/VRAM;
- role-specific scores;
- diagnostic layer deltas/retention;
- exact evidence identities supporting the result.

## Ordered construction tasks

Complete these one bounded task at a time. Do not collapse the reconstruction into one broad rewrite.

### BL-1 — freeze and govern the V1 baseline

- inventory current V1 configs, suites, historical results, experiments, validation packets, schemas, and active runner behavior;
- identify which artifacts are historical/reproducibility assets versus current reusable foundations;
- add current-state documentation for Benchmark Lab V2 without changing V1 result semantics;
- define explicit historical-baseline rules;
- add focused documentation/tests only if needed to prove no V1 evidence is silently reinterpreted.

**Stop gate:** V1 historical evidence is clearly separated from V2 construction, and no existing result can be mistaken for a V2 qualification result.

### BL-2 — define V2 identity and evidence schemas

Introduce versioned schemas/contracts for at least:

- HostProfile;
- RuntimeProfile;
- ModelIdentity;
- EffectiveBenchmarkConfiguration;
- RunManifest V2;
- CaseResult V2;
- EvaluationResult V2.

Define digest/canonicalization rules where identity matters.

**Stop gate:** a future V2 result can unambiguously identify the host, runtime, model, effective settings, benchmark inputs, and evaluator that produced it.

### BL-3 — implement host qualification

- collect the required host/hardware/runtime evidence;
- handle unsupported metrics as unknown/null;
- produce a stable host-profile identity/digest;
- add deterministic tests using injected/fake host probes where practical;
- add non-destructive intended-host smoke qualification.

**Stop gate:** the new PC can produce a repeatable host qualification record adequate for later performance comparison.

### BL-4 — materialize and seal effective runtime configuration

- resolve behavior-bearing provider/model/runtime settings before execution;
- record defaults that materially affect behavior;
- hash the effective configuration;
- reject ambiguous or incomplete qualification configurations where comparison would be misleading;
- preserve V1 config compatibility separately where necessary for old runs.

**Stop gate:** no scored V2 case begins without a stored effective configuration identity.

### BL-5 — build the V2 shared capability battery

- define versioned L0/L1 suites;
- create generic current evaluator contracts;
- reuse strong historical scenarios only when their semantics remain appropriate;
- cover instruction, structured output, context use, diagnosis, repair, blocked decisions, authority boundaries, and evidence discipline;
- add deterministic assessor coverage.

**Stop gate:** all candidate models can be scored against one stable shared core without ACL-specific harness behavior.

### BL-6 — build standardized bounded-tool harness V1

- introduce normalized tool-call/tool-result execution records;
- expose a minimal lab-owned bounded tool surface;
- enforce exact test workspace/scope;
- record every tool request, authorization, result, failure, and terminal output;
- add deterministic fake-model/provider tests;
- do not import ACL runtime authority.

**Stop gate:** a model can complete a disposable bounded file task through the neutral lab harness with complete replayable evidence.

### BL-7 — enforce real-task sandbox and execution limits

- enforce wall time;
- enforce attempt/tool-call limits;
- enforce workspace/write scope;
- enforce configured network policy;
- implement process cleanup/custody adequate for lab execution;
- preserve assessor isolation;
- convert existing validation packets to V2 execution semantics without rewriting their historical evidence.

**Stop gate:** qualification claims no longer rely on unenforced policy declarations.

### BL-8 — run broad candidate campaign

- select several plausible candidates and several intentionally unlikely candidates;
- capture exact model/runtime/config identity;
- run the same shared tests wherever technically possible;
- do not eliminate candidates for mediocre score alone;
- record severe-elimination decisions explicitly;
- capture quality, reliability, telemetry, and resource evidence.

**Stop gate:** each retained candidate has an intrinsic/shared capability baseline and standardized tool-harness evidence.

### BL-9 — ACL cross-harness campaign

**Precondition:** ACL has passed its deterministic reconstruction acceptance gate and separately authorizes supervised model execution.

- run the same candidate cohort through the supervised ACL vertical slice;
- preserve equivalent objective/start-state/scope/validation conditions;
- capture ACL provider binding/harness evidence;
- do not change Benchmark Lab scores to hide ACL-specific losses.

**Stop gate:** every serious candidate has enough comparable evidence to distinguish intrinsic, neutral-harness, and ACL-system performance.

### BL-10 — differential diagnosis and provisional role assignment

- calculate layer deltas/retention;
- identify likely model limitations versus lab-harness limitations versus ACL-harness/context limitations;
- document anomalies requiring retest;
- rank role candidates;
- assign provisional primary/secondary role candidates without creating architectural model dependencies.

**Stop gate:** role assignments are traceable to cross-layer evidence rather than one benchmark score.

### BL-11 — role qualification suites

- build approximately 5 shared behavioral tests plus approximately 10 role-specific tests per important role;
- repeat important tests for final candidates;
- define role-specific hard failures and weights;
- preserve raw trial evidence and variance.

**Stop gate:** each provisional role candidate has a repeatable role-specific qualification score with consistency evidence.

### BL-12 — operational trial and regression capture

- use qualified candidates for supervised real work;
- record operational performance;
- sanitize and freeze valuable representative tasks into future regression fixtures where appropriate;
- update role assignments only from recorded evidence.

**Stop gate:** Benchmark Lab begins accumulating reusable evidence from real workloads without coupling its architecture to one current model.

### BL-13 — continuous challenger workflow

- define how new models/runtimes/configurations challenge incumbents;
- require comparable test/evidence versions;
- distinguish improvements caused by model changes from harness/config changes;
- retain historical incumbents/results for trend analysis.

**Stop gate:** replacing a role model is a qualification decision, not a source-code redesign.

## Immediate construction boundary

The next implementation session should perform **BL-1 only**.

Before changing code, it should:

1. read this document;
2. verify branch/HEAD and working tree;
3. inventory the current repository tree and V1 artifacts;
4. classify V1 historical evidence versus reusable V2 foundations;
5. add only the governance/current-state documentation needed to establish the boundary;
6. run existing deterministic tests if practical;
7. stop before introducing V2 schemas, host probes, tool harnesses, model runs, or new benchmark campaigns.

Do not start BL-2 in the same bounded task unless BL-1 is explicitly reviewed and accepted first.

## Immediate host setup boundary

When the new PC is set up, do not begin the broad model campaign immediately.

The intended sequence is:

```text
Benchmark Lab V2 foundation
    -> host qualification
    -> runtime/model identity
    -> effective configuration sealing
    -> shared L0/L1 capability battery
    -> standardized bounded-tool harness
    -> broad candidate campaign
    -> ACL cross-harness comparison after ACL permits execution
    -> role qualification
```

This sequencing is intentionally test-heavy. The goal is to spend evidence-gathering effort early so later ACL and role decisions are based on measured behavior rather than repeated guesswork.
