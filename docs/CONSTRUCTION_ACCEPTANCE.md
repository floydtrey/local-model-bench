# Benchmark Lab V2 Synthetic Construction Acceptance

**Status:** ACCEPTED

**Acceptance date:** 2026-09-11

**Construction branch:** `architecture/benchmark-lab-v2`

**Accepted implementation checkpoint:** `a557bd061d3f58bdc6d0d279cb92d7e07feac781`

**GitHub Actions run:** `34583105820`

## Purpose

This is the post-BL-8B construction acceptance gate defined by `docs/POST_BL7_CONSTRUCTION_SEQUENCE.md`.

Its purpose is to prove the assembled Benchmark Lab V2 measuring instrument with deterministic synthetic behavior before real benchmark content or candidate-model execution begins.

The gate does **not** qualify a model, runtime, host, containment backend, ACL worker, or role.

## Execution boundary

The acceptance gate is synthetic and sandboxed at the test-fixture level:

- no Ollama request is sent;
- no real model is loaded;
- no provider endpoint is contacted;
- no ACL execution occurs;
- the model surface is an injected deterministic Python driver;
- L2 file work uses temporary disposable workspaces;
- subprocess containment behavior is exercised with deterministic fake backends or fail-closed preflight checks.

## Complete L2 synthetic path

`tests/test_v2_construction_acceptance.py` drives a synthetic Benchmark Pack through:

```text
Benchmark Pack
  -> EffectiveRuntimeConfig resolution
  -> repetition planning
  -> TrialIdentity
  -> ExecutionBinding
  -> immutable RunManifest
  -> BL-6 bounded file-tool harness
  -> tool execution trace
  -> CaseResult
  -> deterministic evaluator
  -> EvaluationResult
  -> BL-8B AggregateReport
  -> append-only EvidenceStore
```

The campaign contains seven observations across six synthetic cases. `authorized-rw` is deliberately repeated twice so the gate also exercises repeated L2 workspace equivalence and evidence identity.

## Required behaviors proven

### Authorized read/write completion

The injected driver reads `input.txt`, writes uppercase content to the authorized `output.txt`, and terminates normally. Both repeated observations produce the expected bytes.

### Unauthorized path request

The driver requests `../secret.txt` while a real synthetic secret exists outside the disposable workspace. The tool boundary denies the request as `invalid_path`. The external bytes remain untouched.

The replay run intentionally uses different external secret bytes and still produces the same governed evidence identities, demonstrating that denied external data does not enter behavioral evidence.

### Stale write

The driver supplies an incorrect expected SHA-256 for an existing writable file. The harness records `stale_write`, increments failed-tool evidence, and leaves the original bytes unchanged.

### Malformed tool request

The driver issues `write_file` without the required argument set. Authorization denies it as `invalid_arguments`; no output file is created.

### Tool-call limit

A dedicated sealed configuration permits one tool call. The driver attempts another. The harness stops with CaseResult status `resource_limit`, stop reason `max_tool_calls`, and only the authorized first call is counted as executed.

### Evaluator hard failure

A dedicated case binds `synthetic-hard-failure`. The deterministic evaluator emits verdict `fail`, zero weighted score for its check, and the declared hard-failure rule. BL-8B aggregation preserves the hard failure separately from weighted statistics.

### Attempt limit

BL-7 `ContainmentExecutor` is exercised with a deterministic strict fake backend. One attempt is allowed; the second is blocked before another backend execution. Backend call count remains one.

### Containment preflight refusal

The repetition runner is given a subprocess DriverBinding with a strict containment policy and `NativeSubprocessBackend`. Preflight refuses the weaker backend before manifest creation or driver execution.

This also preserves the BL-8A rule that a subprocess plan cannot silently fall back to direct in-process model-driver execution.

### Timeout/resource-limit plumbing

A deterministic containment backend returns `timeout` / `wall_clock_limit`; the result is preserved as `containment_execution` evidence with cleanup evidence.

Separately, the L2 tool-limit case proves `resource_limit` propagation through CaseResult and AggregateReport.

### Replay identity

The complete synthetic L2 campaign is executed twice from different disposable workspace roots using identical governed inputs and clocks.

The following SHA-256 identities must match exactly across replay:

- BenchmarkInput;
- EffectiveRuntimeConfigs;
- TrialIdentities;
- ExecutionBindings;
- RunManifest;
- tool execution traces;
- CaseResults;
- EvaluationResults;
- AggregateReport.

Re-persisting the second run into the same content-addressed EvidenceStore is idempotent.

V2 does not yet define a separate mutable resume/checkpoint record. Therefore this gate does not invent a resume protocol. Current applicable identity guarantees are deterministic replay plus append-only/idempotent evidence persistence.

## Aggregate acceptance observations

The synthetic campaign expects:

- 7 planned and observed trials;
- 6 successful CaseResults;
- 1 `resource_limit` CaseResult;
- evaluator pass rate `6/7`;
- exactly 1 hard failure, `synthetic-hard-failure`;
- all AggregateReport case references to resolve to the exact raw CaseResults used to derive the report.

These values are acceptance-fixture expectations only. They are not model-performance thresholds.

## Regression result

Commit `a557bd061d3f58bdc6d0d279cb92d7e07feac781` passed the complete deterministic repository suite in GitHub Actions run `34583105820` on:

- Python 3.12 / Ubuntu;
- Python 3.12 / Windows.

The first fixture commit exposed a missing disposable parent-directory setup. That was a test-fixture defect, not a V2 runtime defect. The corrected fixture then passed on both platforms.

## Construction acceptance decision

The synthetic end-to-end V2 construction gate is **accepted**.

This means the V2 measuring instrument has a cross-platform deterministic construction baseline sufficient to begin **designing** real benchmark content.

It does **not** mean real-model execution is automatically authorized.

Remaining host/runtime-specific gates still apply, including:

- BL-3 intended-host capture and repeatability on the new tower;
- exact runtime/model identity and configuration sealing for each candidate;
- strict containment-backend qualification for any benchmark policy that requires guarantees the current backend cannot prove;
- ACL execution remains separately governed by ACL.

## Next bounded phase

Per `docs/POST_BL7_CONSTRUCTION_SEQUENCE.md`, construction acceptance unlocks benchmark-content design in this order:

1. shared L0/L1 capability cases;
2. L2 neutral bounded-tool cases;
3. broad candidate campaign after the applicable host/runtime gates are satisfied;
4. ACL cross-harness campaign only when ACL separately permits execution;
5. role-specific qualification suites and repeated trials.

The next work should begin with benchmark **design**, not an immediate ungoverned model run.
