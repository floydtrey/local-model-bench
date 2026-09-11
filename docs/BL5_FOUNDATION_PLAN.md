# Benchmark Lab V2 — BL-5 Foundation Split

**Status:** approved refinement of `docs/BENCHMARK_LAB_V2_PLAN.md`

**Applies to:** `architecture/benchmark-lab-v2`

## Purpose

The original V2 construction plan described BL-5 as building the shared L0/L1 capability battery. Before authoring real benchmark cases, the lab needs two smaller construction gates so the measuring instrument is defined before test content is created.

This document refines BL-5 without changing the later architectural intent.

## BL-5A — Benchmark Pack / Case Definition contract

BL-5A defines the portable, versioned container used by future benchmark content.

It must establish:

- an explicit Benchmark Pack schema version;
- pack ID and pack version;
- one explicit capability level per pack (`L0` through `L4`);
- exact source-byte SHA-256 identity;
- a semantic SHA-256 projection that does not treat file locators or reporting labels as behavioral identity;
- unique case IDs;
- candidate-visible messages and referenced context fixtures;
- context fixture content digests separate from locators;
- provider-neutral configuration-profile requirements;
- provider-neutral response contracts;
- provider-neutral tool-surface requirements;
- evaluator contract references without embedding evaluator implementation;
- explicit hard-failure rule references;
- declarative screening and qualification repetition counts;
- support for packs and fixtures stored outside the public repository;
- fail-closed handling of unknown contract fields.

BL-5A does **not** create the shared capability battery itself. Synthetic fixtures used to test the contract are engineering tests, not scored benchmark cases.

**Stop gate:** a future benchmark case can be represented, hashed, validated, loaded from an arbitrary location, and converted into V2 `benchmark_input` evidence without provider-specific settings or evaluator implementation being embedded in the case.

## BL-5B — Evaluator framework

After BL-5A is accepted, BL-5B defines the versioned evaluator registry and normalized deterministic evaluation contract.

It should establish:

- evaluator ID and contract version;
- evaluator implementation identity;
- declared input/result contracts;
- deterministic check output;
- weighted score output where applicable;
- hard failures separate from score;
- consumed-evidence declarations;
- optional human-review requirement;
- fail-closed evaluator resolution;
- synthetic evaluator tests independent of real models.

BL-5B still does **not** author the real shared capability battery.

**Stop gate:** a synthetic case result can be evaluated through a versioned deterministic evaluator and produce normalized `EvaluationResult` evidence without special-case logic in the runner.

## After BL-5B

Only after BL-5A and BL-5B are accepted should the project author the real L0/L1 shared capability battery described by the original BL-5 section of `BENCHMARK_LAB_V2_PLAN.md`.

The intended order is therefore:

```text
BL-5A Benchmark Pack contract
    -> BL-5B evaluator framework
    -> BL-6 neutral bounded-tool harness
    -> BL-7 containment/enforcement
    -> V2 orchestration/aggregation construction
    -> construction acceptance fixture
    -> actual benchmark battery design
```

The later numbering in the original plan remains authoritative for cross-harness campaigns and role qualification unless separately refined and documented.

## Construction-only rule

During BL-5A and BL-5B:

- no Ollama/model call is required;
- no provider qualification is implied;
- no ACL authority is changed;
- no real benchmark score is produced;
- deterministic fake/synthetic fixtures are allowed only to validate the lab machinery.
