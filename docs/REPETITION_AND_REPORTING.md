# Benchmark Lab V2 Repetition and Reporting

**Construction task:** BL-8B

**Status:** construction contract

## Purpose

BL-8B turns the BL-8A single-trial execution path into a governed repeated-observation and reporting layer without changing the meaning of the raw evidence underneath it.

The governing rule is:

> Raw TrialIdentity, execution trace, CaseResult, and EvaluationResult records remain the source of truth. Aggregate reports are derived evidence only.

BL-8B does not create benchmark questions, select candidate models, start Ollama, invoke ACL, or grant new execution authority.

## Repetition phases

A Benchmark Pack already declares two repetition counts for every case:

- `screen_trials`;
- `qualification_trials`.

BL-8B exposes exactly two named campaign phases:

- `screen` -> use `screen_trials`;
- `qualification` -> use `qualification_trials`.

The runner never accepts an ad-hoc numeric repeat count. Changing repetition policy requires changing the Benchmark Pack, which changes benchmark semantic identity before the run begins.

Every repeated trial receives:

- an ordinal from 1 through the declared count;
- one deterministic `repeat_group` identity for its case, pack version, and phase;
- the same exact BenchmarkInput reference;
- an exact EffectiveRuntimeConfig reference;
- a distinct TrialIdentity and ExecutionBinding.

All planned trials and bindings are sealed into the RunManifest before any driver execution.

The in-memory `RepeatedRun.planned_counts` mapping and the phase mapping are immutable after construction.

## L0 and L1 repetitions

L0 and L1 repetitions use the accepted intrinsic BL-8A execution path.

They remain tool-free. Each observation produces its own intrinsic execution trace, CaseResult, and EvaluationResult.

## L2 repeated-workspace rule

A repeated L2 case must not let one trial's file changes become the next trial's starting state.

When an L2 case has more than one observation, BL-8B therefore requires a workspace factory that supplies a distinct workspace root for each ordinal.

Before the RunManifest is sealed, BL-8B:

1. resolves the exact readable/writable scope;
2. materializes governed read-only fixture bytes where required;
3. captures the BL-6 root-independent workspace snapshot SHA-256;
4. requires every repeated workspace for the same case to have the same initial snapshot SHA-256;
5. records that initial-state SHA-256 in the ExecutionBinding;
6. rejects workspace-root reuse.

Immediately before each driver invocation, BL-8B recomputes the workspace snapshot and compares it with the sealed initial identity. Any post-manifest change blocks execution for that trial rather than silently changing the experiment.

Absolute disposable workspace roots are not added to durable experiment identity.

## Subprocess boundary

BL-8B preserves the BL-8A fail-closed subprocess rule.

A subprocess driver binding may be containment-preflighted and included in the sealed pre-run evidence, but the model driver is not invoked until a real adapter routes the model invocation through BL-7 containment. Direct Python-call fallback is forbidden.

## AggregateReport

`aggregate_report` is a content-addressed V2 evidence record with report contract:

`benchmark-lab-aggregate-report:v1`

It references the exact RunManifest, BenchmarkInput, repeated trials, execution evidence, CaseResults, and EvaluationResults that support the calculations.

The aggregator validates evidence closure before calculating statistics. It rejects, among other things:

- trials outside the run;
- missing or duplicate trial outcomes;
- trial ordinals that do not match the declared repetition count;
- multiple repeat groups for one repeated case;
- CaseResults bound to another manifest or benchmark;
- CaseResults whose primary execution evidence is outside the run;
- EvaluationResults bound to CaseResults outside the run.

The aggregate cannot replace or repair raw evidence.

## Evaluation statistics

BL-8B records both per-case and overall evaluation summaries.

Current derived fields include:

- evaluation observation count;
- verdict counts;
- pass rate;
- verdict consistency rate;
- raw score statistics;
- normalized score statistics;
- hard-failure counts and affected evaluations;
- hard-failure counts by rule;
- per-evaluator summaries for each case.

### Pass rate

Pass rate is:

`number of pass verdicts / number of EvaluationResult observations`

`fail`, `review`, and `not_scored` therefore remain visible in the denominator. BL-8B does not silently discard non-pass observations to improve the rate.

### Scores

For a scored EvaluationResult:

`normalized score = score / maximum_score`

BL-8B reports minimum, maximum, arithmetic mean, median, and population variance for measured raw and normalized scores.

Raw point statistics are descriptive. When different evaluator contracts use different maxima, normalized score and the per-evaluator breakdown are the appropriate cross-observation comparison surfaces.

Unscored observations do not receive invented numeric scores. Each numeric-statistics block records both `measured` and `expected` counts.

### Consistency

Current consistency rates are deterministic dominant-outcome fractions:

- status consistency = most common CaseResult status / CaseResult count;
- verdict consistency = most common evaluator verdict / EvaluationResult count.

These are descriptive stability signals, not qualification decisions by themselves.

## Execution statistics

Per-case and overall execution summaries can include:

- terminal-status counts;
- duration;
- attempts;
- retries;
- model turns;
- tool calls;
- authorized tool calls;
- denied tool calls;
- successful tool calls;
- failed tool calls.

Duration is derived only when the stored `started_at` and `finished_at` timestamps parse to a non-negative interval.

Attempts and retries are aggregated only when the CaseResult explicitly records them. BL-8B does not infer `attempts=1` or `retries=0` merely because a run completed.

## Resource and telemetry rule

BL-8B aggregates resource/telemetry measurements only when a CaseResult explicitly carries numeric values under `metrics.telemetry`.

Examples of future measured fields may include:

- peak RAM bytes;
- peak VRAM bytes;
- GPU utilization;
- load time;
- prompt-evaluation time;
- generation time;
- throughput.

A null measurement is unmeasured and is excluded from numeric statistics. A non-null nonnumeric telemetry value fails aggregation rather than being guessed or coerced.

If a metric was never measured, its numeric-statistics block remains explicit with `measured=0` and null statistical values, or the telemetry key is absent when no observation measured it.

## Report views

BL-8B can render deterministic Markdown and CSV views from an AggregateReport.

These are human/operator convenience views. They do not become independent sources of truth and do not replace the content-addressed AggregateReport or its referenced raw evidence.

The Markdown output explicitly identifies the aggregate evidence digest and states that raw records remain authoritative.

## Append-only evidence

Persisting an AggregateReport uses the existing append-only EvidenceStore.

Generating or persisting a report does not rewrite TrialIdentity, execution trace, CaseResult, or EvaluationResult bytes. A conflicting record at the same content-addressed destination fails closed.

## BL-8B construction tests

Synthetic deterministic tests cover:

- per-case screen repetition counts;
- qualification repetition counts;
- immutable phase/count planning;
- unique trial ordinals and repeat-group identities;
- fresh L2 workspaces;
- workspace-root reuse rejection;
- identical initial L2 snapshot requirements;
- pre-driver blocking when L2 baselines differ;
- pass-rate, mean, median, population variance, and hard-failure aggregation;
- explicit measured attempts/retries/telemetry aggregation;
- unmeasured metric preservation without estimates;
- exact supporting-evidence references;
- report persistence without raw-evidence mutation;
- deterministic Markdown and CSV rendering.

All BL-8B construction tests use injected deterministic fake drivers. They are engineering tests, not model benchmarks.

## Non-goals

BL-8B does not:

- design the real shared capability battery;
- choose or eliminate models;
- run a provider or local model;
- implement the pending BL-7-routed subprocess model-driver adapter;
- implement missing strict host network/filesystem/assessor isolation;
- run ACL;
- assign workforce roles;
- declare qualification from an aggregate alone.

## Next gate

After BL-8B is accepted, the next bounded task is the **synthetic deterministic end-to-end construction acceptance gate** described in `docs/POST_BL7_CONSTRUCTION_SEQUENCE.md`.

That gate proves the measuring instrument as a whole before real benchmark content or candidate-model campaigns begin.
