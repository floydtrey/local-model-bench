# Post-BL-7 Construction Sequence

This document records the accepted refinement made during Benchmark Lab V2 construction:
**finish the measuring instrument before designing or running the real model benchmark battery.**

It refines the older `BENCHMARK_LAB_V2_PLAN.md` ordering after BL-7. The broad model
campaign originally labeled BL-8 is deferred until the remaining execution machinery
is complete.

## Remaining construction gates

### BL-8A — V2 runner/orchestrator

Connect the already accepted V2 pieces without adding real model benchmark content:

1. load a Benchmark Pack;
2. resolve and seal exact effective configuration;
3. construct TrialIdentity records;
4. seal RunManifest before execution;
5. dispatch intrinsic or neutral-tool execution through an injected driver;
6. require containment preflight where subprocess execution is involved;
7. create CaseResult from immutable execution evidence;
8. invoke registered evaluators independently;
9. persist evidence without rewriting raw records.

Construction uses deterministic fake providers/drivers only.

### BL-8B — repetition, aggregation, and reporting

Add derived reporting without overwriting raw trial evidence:

- pass rate;
- mean/median score;
- variance/consistency;
- hard-failure counts;
- retries/attempts;
- tool-call counts;
- latency/duration;
- resource/telemetry fields when measured;
- evidence identities supporting every aggregate.

Aggregates are derived evidence, never the source of truth.

### Construction acceptance gate

Before real benchmark design begins, run a fully synthetic deterministic end-to-end
fixture through the complete V2 path. The fixture must prove both successful and
malicious/incorrect fake behaviors, including at minimum:

- authorized read/write completion;
- unauthorized path request;
- stale write;
- malformed tool request;
- tool-call limit;
- attempt limit;
- containment preflight refusal;
- timeout/resource-limit result plumbing;
- evaluator hard failure;
- replay/resume identity checks where applicable.

No real model is required for this gate.

## After construction acceptance

Only after the measuring instrument passes the synthetic acceptance gate should the
project begin designing the actual model test battery:

1. shared L0/L1 capability cases;
2. L2 neutral bounded-tool cases;
3. broad candidate campaign;
4. ACL cross-harness campaign when ACL separately permits execution;
5. role-specific qualification suites and repeated trials.

BL-3 intended-host measurement and strict containment-backend qualification may remain
host-specific acceptance items until the new tower is configured, but no real-task
qualification may bypass those pending gates.
