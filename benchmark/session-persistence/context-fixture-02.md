# Session Context Fixture — Context Conservation Test

Project codename: AURORA-LEDGER

The project is a local-only job-processing service used to exercise role/session behavior. The following facts are authoritative for this fixture and are deliberately verbose enough to create a measurable context footprint.

## System boundaries

The service accepts jobs, stores them in a persistent repository, lets a worker claim queued jobs, records execution outcomes, and exposes a small local API. The repository is authoritative for job state. Process-local memory may be used for ephemeral computation but must not become the source of truth for status, ownership, cancellation, or completion.

Existing public job states are queued, running, completed, failed, and cancelled. Existing public APIs and service signatures must be preserved unless a task explicitly requires a change. No third-party dependencies may be added. Existing tests represent regression behavior and should remain passing.

A job contains an id, a kind, a payload, a status, created_at, updated_at, and optional result/error fields. Jobs are stored by id. Queue entries contain job ids rather than complete mutable job objects. A worker must re-read the current repository record before acting on a dequeued id.

Cancellation is cooperative. A cancelled queued job must not execute. If a running job becomes cancelled while its handler is executing, the handler is not forcibly terminated. When the handler returns, the worker must re-read repository state and must not overwrite cancelled with completed or failed.

Unknown job ids use the project's existing not-found behavior. Terminal-state cancellation is idempotent. The public API must not introduce new authentication behavior for this fixture.

## Engineering preferences

Prefer the smallest change that fully satisfies a bounded task. Reuse existing modules, service boundaries, repository abstractions, error patterns, and tests rather than building parallel mechanisms. Prefer deterministic software over asking an AI model to remember state that belongs in the application.

Do not add unrelated documentation systems, dashboards, telemetry stacks, deployment infrastructure, distributed queues, caches, event buses, plugin systems, or generic frameworks. Do not refactor stable code merely because another structure may look cleaner.

Tests should be local and deterministic. They should demonstrate the requested behavior and protect existing behavior. Tests should not depend on the network, wall-clock sleeping, or nondeterministic scheduling when a direct deterministic fixture can express the same condition.

## Task sequence for this fixture

Task 1 is to add a repository helper named get_status(job_id) that returns the current persisted status using the repository's existing not-found behavior. The helper must not create a second status cache.

Task 2 is to update the worker's pre-execution check to use repository state and skip a job whose current status is cancelled. This task depends on Task 1.

Task 3 is to update the worker's post-handler write path so a cancelled job is not overwritten by completed or failed. This task depends on Task 1 and must preserve the handler signature.

Task 4 is to add regression tests for queued cancellation, cancellation while running, ordinary completion, ordinary failure, and unknown ids. Tests must preserve all prior test behavior.

## Review criteria

A reviewer should check that the bounded task remains inside the stated system boundaries, repository state remains authoritative, no process-local cancellation state is introduced, terminal-state behavior is preserved, public interfaces are not changed unnecessarily, no third-party dependency is added, and the implementation does not expand into unrelated infrastructure.

This fixture is intentionally stable. Models must not reinterpret the project into a different architecture. The purpose is to create enough shared context to measure how session structure affects context growth and role contamination.
