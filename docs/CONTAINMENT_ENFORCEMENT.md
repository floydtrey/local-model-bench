# BL-7 Containment and Execution-Limit Enforcement

## Purpose

BL-7 converts execution-policy declarations into a fail-closed enforcement contract.
A V2 qualification result may claim only limits that the selected containment backend
explicitly advertises and passes in preflight.

This is deliberately stricter than the historical `real-tasks-v1` launcher. The V1
packet and launcher are preserved as historical evidence; BL-7 adds a V2 projection
rather than rewriting them.

## Core implementation

- `src/localbench/v2/containment.py`
- `src/localbench/v2/validation_adapter.py`
- `schemas/v2/containment-execution.schema.json`
- `tests/test_v2_containment.py`

Containment execution is a first-class V2 evidence record with record type
`containment_execution`.

## Policy contract

`ContainmentPolicy` seals the behavior-bearing limits that must be enforced for one
execution context:

- wall-clock seconds;
- maximum attempts;
- network policy;
- required process-custody strength;
- workspace-isolation requirement;
- assessor-isolation requirement;
- exact writable-path overlay;
- optional output-byte limit;
- optional memory limit.

The policy receives a deterministic SHA-256. A backend cannot silently weaken it.

## Capability-backed preflight

Each backend declares `ContainmentCapabilities` separately from the policy. The
preflight gate compares them and returns explicit reasons for every requirement that
cannot be proven.

Examples include:

- `wall_clock_timeout_not_enforced`;
- `process_custody_too_weak`;
- `network_policy_not_enforced:disabled`;
- `workspace_isolation_not_enforced`;
- `workspace_write_scope_unresolved`;
- `workspace_write_scope_not_enforced`;
- `assessor_isolation_not_enforced`;
- `output_limit_not_enforced`;
- `memory_limit_not_enforced`.

Any issue blocks qualification execution. There is no warning-only downgrade path.

## Attempt limits

`ContainmentExecutor` owns attempt accounting. Once `max_attempts` is consumed, a
further attempt raises `ContainmentBlocked` before the backend executes anything.

This is distinct from BL-6's maximum tool-call enforcement. BL-6 remains responsible
for the sealed model/tool-loop call budget; BL-7 is responsible for outer execution
attempts and containment.

## Native subprocess backend

`NativeSubprocessBackend` is intentionally conservative.

It currently advertises only:

- wall-clock timeout;
- best-effort process-tree cleanup;
- unrestricted/task-allowed network behavior.

It does **not** advertise:

- strict process custody;
- disabled/provider-only network isolation;
- filesystem/workspace isolation;
- exact subprocess write confinement;
- assessor isolation;
- output-byte enforcement;
- memory enforcement.

Therefore the historical real-task policies, which require `network=disabled`, fail
preflight on the native backend. This is correct behavior. A local process with a
changed working directory is not a network or filesystem sandbox.

A stronger backend can implement the same interface later without changing benchmark
case semantics or historical packet evidence.

## Containment execution evidence

For an allowed execution, BL-7 seals:

- exact policy and policy digest;
- backend identity/version and claimed capabilities;
- command logical ID and command digest;
- workspace role, not the absolute disposable workspace path;
- attempt ordinal;
- status and stop reason;
- exit code;
- timing/duration;
- whether cleanup was performed;
- stdout/stderr SHA-256, byte count, and captured UTF-8 representation.

Raw run evidence may contain private source/test output and should follow the existing
V2 private-result policy. The public repository does not require real containment
records to be committed.

## Assessor staging

`validate_assessor_staging()` requires both:

1. the candidate workspace record states `assessment_included=false`; and
2. candidate execution is terminal before assessor staging begins.

The containment backend still must advertise assessor isolation when the policy
requires it. Staging order alone is not treated as an OS sandbox.

## Historical validation packet adapter

`adapt_legacy_validation_task()` projects one V1 task into V2 containment semantics
while preserving the exact source packet bytes by SHA-256.

For `real-tasks-v1` it preserves:

- task ID/title/category;
- baseline commit and `git archive` materialization;
- wall-clock limit;
- maximum attempts;
- disabled-network requirement;
- assessor paths as staging metadata.

The historical packet does not contain a machine-readable exact write allowlist.
Therefore the V2 adapter marks `explicit_workspace_write_scope_required` until a new
V2 overlay supplies exact writable paths. The old packet file is not edited to invent
that information retroactively.

## Acceptance meaning

BL-7 construction acceptance means the lab can no longer turn an unenforced policy
declaration into a qualification claim. It does **not** mean the current laptop or
new tower already has a strict network/filesystem sandbox backend.

Before real-task qualification begins on the intended host, that host must have a
backend whose measured capabilities satisfy the selected policy in preflight. Until
then, affected tasks remain blocked rather than being run with weaker isolation.

## Out of scope

BL-7 does not:

- run a real model;
- enable ACL execution;
- create the real benchmark battery;
- choose the final intended-host strict sandbox technology;
- turn the native subprocess backend into a falsely labeled security boundary.
