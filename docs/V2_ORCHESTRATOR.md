# BL-8A V2 Runner / Orchestrator

## Purpose

BL-8A connects the accepted Benchmark Lab V2 components into one deterministic
pre-run planning and execution path without creating real model benchmark content.
Construction and validation use injected fake drivers only.

The orchestrator is intentionally not an authority source for ACL and does not grant
model execution permission outside Benchmark Lab.

## Implementation

Primary implementation:

- `src/localbench/v2/orchestrator.py`
- `src/localbench/v2/records.py`
- `src/localbench/v2/contracts.py`
- `schemas/v2/execution-binding.schema.json`
- `schemas/v2/intrinsic-execution-trace.schema.json`
- `schemas/v2/qualification-record.schema.json`
- `tests/test_v2_orchestrator.py`

The public entry point is `run_v2_pack()`.

## Construction scope

BL-8A executes exactly one engineering trial per Benchmark Pack case.

Repetition planning, statistical aggregation, comparative reporting, and role
leaderboards belong to BL-8B or later work. BL-8A therefore does not reinterpret a
case's `screen_trials` / `qualification_trials` as an instruction to perform repeated
runs yet.

Supported execution levels are:

- L0 — intrinsic prompt/response;
- L1 — intrinsic prompt/response with digest-verified supplied context;
- L2 — lab-owned bounded `read_file` / `write_file` tool loop.

L3/L4 execution remains outside this runner version.

## Pre-run closure

Before any driver is invoked, BL-8A resolves and seals:

1. exact Benchmark Pack evidence;
2. exact EffectiveRuntimeConfig records;
3. evaluator identities required by the cases;
4. one TrialIdentity per planned case;
5. one ExecutionBinding per planned trial;
6. the complete RunManifest.

Those records are persisted before execution. A driver therefore cannot be called and
then have its workspace scope, tool mapping, configuration, evaluator set, or
execution identity selected retroactively.

## ExecutionBinding

`execution_binding` is the behavior-bearing bridge between the portable benchmark
case and the concrete execution mechanism. It binds:

- the exact TrialIdentity;
- intrinsic vs lab-tool execution mode;
- driver logical ID and implementation SHA-256;
- driver execution kind (`in_process` or `subprocess`);
- exact readable/writable workspace scope for L2;
- digest-verified context-asset delivery targets;
- portable-to-concrete tool-surface mapping where applicable;
- containment policy/backend evidence when subprocess execution is requested.

Absolute disposable workspace locations are not durable behavioral identity.

## Portable L2 capability mapping

Benchmark Pack cases remain provider/harness-neutral. An L2 case requires the portable
capability:

`bounded-files-v1`

with the canonical tools:

- `read_file`
- `write_file`

The current lab implementation maps that requirement to the concrete BL-6 surface:

`lab-bounded-files:v1`

and binds the exact BL-6 tool-schema SHA-256 into the ExecutionBinding.

The original Benchmark Pack is never rewritten to contain the concrete harness ID.
At the final BL-6 call boundary, BL-8A derives an execution-only case view containing
the concrete surface required by BL-6. This preserves portable benchmark identity
while making the actual adapter choice explicit and content-addressed.

## Context assets

Context assets are loaded only through an explicit `asset_loader` supplied by the
caller.

Before a candidate receives the asset:

- the exact bytes are hashed;
- the digest must match the Benchmark Pack declaration;
- unsupported/non-UTF-8 delivery modes fail closed;
- `source_locator` is removed from candidate-visible data;
- the ExecutionBinding records asset ID, digest, media type, declared delivery mode,
  and delivery target rather than the private source locator.

For L2 `readonly_reference` assets, the derived reference path is staged read-only into
the governed workspace and cannot overlap writable scope.

## Intrinsic execution evidence

L0/L1 execution produces `intrinsic_execution_trace` evidence containing:

- one normalized tool-free request;
- normalized response or protocol/error evidence;
- terminal output when successful;
- status and stop reason;
- orchestrator/trace contract versions.

A tool request during intrinsic execution is a protocol failure rather than a hidden
upgrade to tool-capable execution.

## L2 execution evidence

L2 delegates execution to the accepted BL-6 neutral bounded-tool harness. The resulting
`tool_execution_trace` remains the authoritative event-level evidence for model/tool
interaction.

BL-8A wraps that trace in a CaseResult that also references the sealed pre-run
ExecutionBinding, TrialIdentity, Benchmark input, and RunManifest.

## Evaluator boundary

After a CaseResult is sealed, each evaluator named by the immutable case definition is
resolved through `EvaluatorRegistry` and invoked independently.

The orchestrator supplies only evidence record types declared by that evaluator's
consumption contract. It does not add evaluator-specific scoring logic to the runner.

## Append-only evidence storage

`EvidenceStore` persists records at content-addressed paths:

`records/<record_type>/<sha256>.json`

Persistence is create-only:

- writing an identical already-present record is idempotent;
- conflicting bytes at the same content address are an error;
- raw records are never rewritten to attach later status or aggregate data.

BL-8B reports must therefore be derived evidence rather than mutations of BL-8A raw
records.

## Subprocess containment boundary

A `DriverBinding` may declare `execution_kind="subprocess"` together with a BL-7
containment policy/backend. BL-8A performs containment preflight before sealing the
plan. Failed preflight blocks before the manifest or driver execution.

A successful preflight does **not** authorize the Python driver to be called directly.
The current runner has no model-driver adapter that serializes a model turn through a
BL-7-contained subprocess boundary. Therefore, after the successful preflight and
pre-run manifest are sealed, BL-8A fails closed before invoking that driver.

This protects the evidence claim:

> a sealed subprocess containment binding must never be followed by an in-process
> direct-call fallback.

A future containment-backed model-driver adapter must route the actual invocation
through BL-7 before subprocess-bound scored execution can be enabled.

## Synthetic engineering coverage

The BL-8A test suite proves at minimum:

- pre-run manifest and execution binding exist before an intrinsic driver is called;
- intrinsic execution is tool-free;
- context-asset bytes are digest verified and source locators are not candidate visible;
- asset mismatch blocks before driver execution;
- portable L2 capability maps explicitly to the exact BL-6 concrete surface;
- exact L2 workspace scope is sealed before read/write execution;
- CaseResult and evaluator evidence are produced independently;
- containment preflight failure blocks before execution;
- successful subprocess preflight still cannot fall back to an in-process driver call;
- the evidence store is idempotent for identical records and rejects conflicting bytes.

All fixtures are synthetic engineering tests, not real model benchmark cases.

## Out of scope

BL-8A does not:

- run a real model or provider;
- start Ollama;
- enable ACL execution;
- perform repeated statistical trials;
- aggregate or rank models;
- design the actual benchmark battery;
- provide a real subprocess model-driver adapter;
- weaken any BL-7 containment requirement.

The next construction gate after BL-8A is BL-8B repetition, aggregation, and reporting.
