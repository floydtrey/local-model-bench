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
- `src/localbench/v2/process_custody.py`
- `src/localbench/v2/validation_adapter.py`
- `schemas/v2/containment-policy.schema.json`
- `schemas/v2/containment-execution.schema.json`
- `tests/test_v2_containment.py`
- `tests/test_v2_process_custody.py`

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

`NativeSubprocessBackend` is intentionally conservative. It advertises wall-clock
timeout, best-effort process-tree cleanup, and task-allowed network behavior only.
It does not advertise strict process custody, network isolation, workspace isolation,
write confinement, assessor isolation, output limiting, or memory limiting.

## Staged process-custody backend

`StrictProcessBackend` adds useful enforcement without calling it a full sandbox:

- disposable workspace copy;
- exact changed-path comparison after successful execution;
- only declared writable paths are promoted back to the original workspace;
- unauthorized changes inside the disposable workspace are rejected and not promoted;
- bounded combined stdout/stderr capture;
- wall-clock termination;
- Windows Job Object custody with kill-on-close;
- POSIX process-group cleanup.

Its capability declaration is intentionally narrower than its class name may suggest:

- `workspace_write_scope=true` means promotion back into the governed candidate
  workspace is restricted to the declared paths;
- `workspace_isolation=false` because the subprocess still runs under the host account
  and can access host paths outside the disposable workspace;
- `assessor_isolation=false` because sequencing/staging alone does not provide OS-level
  isolation from assessor material stored elsewhere on the host;
- `network_policies=[task_allowed]`; disabled/provider-only networking is not enforced;
- `memory_limit=false`;
- `process_custody=strict` on Windows, where Job Objects provide the accepted custody
  mechanism for this backend;
- `process_custody=best_effort` on POSIX, because a process group alone is not treated
  as an inescapable security boundary.

A deterministic test intentionally writes to a temporary path outside the disposable
workspace and confirms that the path is reachable. This preserves the fact that the
backend is **staged workspace protection**, not host filesystem isolation.

`StrictAssessorBackend` additionally validates that assessment material was not
included in candidate staging and that the candidate is terminal before assessor
execution. It still advertises `assessor_isolation=false`; the staging proof is useful
but is not mislabeled as an OS security boundary.

Therefore the historical real-task policies, which require `network=disabled` and
qualification-grade isolation, remain blocked until a stronger backend can actually
satisfy those requirements.

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

The selected backend must still advertise assessor isolation when a policy requires
it. Staging order alone is not treated as a sandbox.

## Historical validation packet adapter

`adapt_legacy_validation_task()` projects one V1 task into V2 containment semantics
while preserving the exact source packet bytes by SHA-256.

For `real-tasks-v1` it preserves task ID/title/category, baseline commit and
`git archive` materialization, wall-clock limit, maximum attempts, disabled-network
requirement, and assessor paths as staging metadata.

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

BL-7 does not run a real model, enable ACL execution, create the real benchmark
battery, or select/qualify the final intended-host network/filesystem isolation
technology.
