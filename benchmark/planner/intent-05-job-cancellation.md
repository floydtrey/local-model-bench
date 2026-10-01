# Planner Intent 05 — cancellable background jobs

A Python application runs long-lived background jobs through a queue, worker, and persistent job store. Jobs can currently be created, started, completed, or failed, but they cannot be cancelled.

Current project facts:
- Job model and status enum: `src/jobs/model.py`
- Persistent job repository: `src/jobs/repository.py`
- Queue interface and in-memory implementation: `src/jobs/queue.py`
- Worker execution loop: `src/jobs/worker.py`
- Service layer used by API/CLI callers: `src/jobs/service.py`
- HTTP routes: `src/jobs/api.py`
- Existing tests:
  - `tests/test_repository.py`
  - `tests/test_queue.py`
  - `tests/test_worker.py`
  - `tests/test_service.py`
  - `tests/test_api.py`
- Public job statuses are exactly `queued`, `running`, `completed`, and `failed`.
- The repository is the authoritative source of persisted job state.
- The queue stores job IDs, not full job objects.
- A worker reads the job from the repository before execution and updates the repository when execution finishes.
- Job handlers are synchronous Python callables.
- Existing handler signatures cannot be changed.
- The application may have more than one worker process.
- There is no shared in-memory state between worker processes.
- API clients identify jobs by job ID.

Requested change:
Add cooperative job cancellation.

Required behavior:
- Add a new public job status named `cancelled`.
- Add `cancel_job(job_id)` to the service layer.
- Add HTTP endpoint `POST /jobs/{job_id}/cancel`.
- Cancelling a `queued` job:
  - persist its status as `cancelled`;
  - it must never execute even if its ID remains in the queue.
- Cancelling a `running` job:
  - persist its status as `cancelled`;
  - do not attempt to forcibly terminate the Python callable that is already running;
  - when that callable eventually returns or raises, the worker must not overwrite `cancelled` with `completed` or `failed`.
- Cancelling a job already in `completed`, `failed`, or `cancelled` state is idempotent: leave its status unchanged and report success.
- Cancelling an unknown job ID must return the project's existing not-found error through the service and API layers.
- Before executing a dequeued job ID, the worker must read the current repository state and skip execution when the job is already `cancelled`.
- Before persisting `completed` or `failed`, the worker must re-read the repository state. If the current state is `cancelled`, leave it cancelled.
- Cancellation coordination must use the persistent repository. Do not add a process-local cancellation registry.
- The queue interface does not need a remove operation.

API behavior:
- Successful cancellation returns HTTP 200 with the project's existing serialized job representation.
- Unknown job ID uses the project's existing not-found response and status code.
- No new endpoint authentication behavior is required.

Constraints:
- Do not add third-party dependencies.
- Preserve all existing public service methods and API routes.
- Do not change job-handler signatures.
- Do not add forced thread/process termination.
- Do not introduce process-local cancellation state.
- Add or update tests covering:
  - queued job cancellation and worker skip;
  - running job cancellation followed by handler success;
  - running job cancellation followed by handler failure;
  - repeated cancellation;
  - cancellation of completed and failed jobs;
  - unknown job cancellation;
  - API success and not-found behavior;
  - regression coverage for existing non-cancelled jobs.
