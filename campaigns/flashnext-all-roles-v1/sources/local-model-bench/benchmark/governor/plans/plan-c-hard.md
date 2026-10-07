The intent is clear. The requirements for adding cooperative job cancellation are explicitly defined, including the new status, service layer changes, API endpoint behavior, worker logic updates, and testing requirements. The constraints (no third-party deps, no signature changes, repository-based coordination) are also clear.

There are no missing facts or ambiguous decisions that require external input. The plan can proceed by breaking down the implementation into bounded tasks that respect the dependency order (e.g., model changes before service logic, service logic before API/worker updates).

Here is the bounded task list:

### Task 1: Update Job Model and Repository
**Goal:** Add `cancelled` status to the enum and ensure the repository can handle it.
**Prerequisites:** None.
**Tasks:**
1. Update `src/jobs/model.py` to add `cancelled` to the public job status enum.
2. Review `src/jobs/repository.py` to ensure no implicit assumptions block the `cancelled` status (e.g., if there are hard-coded status lists). If any exist, update them to include `cancelled`.
3. Verify `src/jobs/repository.py` methods used by the service layer for updating status do not validate against a restricted list that excludes `cancelled`. If they do, update the validation or remove it if the repository is the authoritative source.

**Acceptance Condition:**
- The `JobStatus` enum (or equivalent) explicitly includes `cancelled`.
- Code review confirms that `cancelled` is treated as a valid status everywhere in the model/repository layer.

### Task 2: Implement Service Layer Cancellation Logic
**Goal:** Add `cancel_job` method to `src/jobs/service.py`.
**Prerequisites:** Task 1.
**Tasks:**
1. Add `cancel_job(job_id: str)` to the service class/interface in `src/jobs/service.py`.
2. Implement logic:
   - Fetch job by ID.
   - Handle "not found" using the project's existing mechanism.
   - Check current status:
     - If `completed`, `failed`, or `cancelled`: Return success (idempotent).
     - If `queued`: Update status to `cancelled` in the repository.
     - If `running`: Update status to `cancelled` in the repository.
   - Return the updated job object (serialized representation).
3. Ensure the service method uses the standard error handling for not-found jobs.

**Acceptance Condition:**
- `cancel_job` exists in `src/jobs/service.py`.
- Logic correctly handles all status cases as specified.
- Idempotent behavior for `completed`, `failed`, `cancelled` is implemented.
- Errors for unknown IDs match existing patterns.

### Task 3: Implement HTTP Endpoint
**Goal:** Add `POST /jobs/{job_id}/cancel` route in `src/jobs/api.py`.
**Prerequisites:** Task 2.
**Tasks:**
1. Add the route `POST /jobs/{job_id}/cancel` in `src/jobs/api.py`.
2. Call `service.cancel_job(job_id)`.
3. Handle response:
   - On success: Return HTTP 200 with the serialized job object.
   - On not-found: Return the project's existing not-found response and status code.
4. Ensure no new authentication/authorization logic is added.

**Acceptance Condition:**
- Endpoint exists at `/jobs/{job_id}/cancel`.
- Returns HTTP 200 and job details on successful cancellation.
- Returns standard not-found error for invalid IDs.
- No new auth middleware is applied.

### Task 4: Update Worker Execution Logic
**Goal:** Make worker cooperative with cancellation via repository checks.
**Prerequisites:** Task 1.
**Tasks:**
1. In `src/jobs/worker.py`, before executing a dequeued job ID:
   - Fetch the current state of the job from the repository.
   - If status is `cancelled`, skip execution and continue to the next job.
2. After a handler completes (success or failure):
   - Before writing `completed` or `failed` status back to the repository:
     - Re-fetch the current state of the job from the repository.
     - If status is `cancelled`, abort the update (leave as `cancelled`).
     - Otherwise, proceed with the update.
3. Ensure this re-fetch logic does not introduce race conditions that violate the "persistent repository is authoritative" rule. Since the queue stores IDs, not objects, fetching at execution time is necessary.

**Acceptance Condition:**
- Worker checks status before execution; cancelled jobs are skipped.
- Worker checks status after execution; if cancelled, it does not overwrite with `completed`/`failed`.
- Logic handles the case where the job is still `running` at the time of the post-execute check (though the check is for `cancelled`, if it's `running`, it proceeds to update, which is correct for non-cancelled jobs).

### Task 5: Write Tests
**Goal:** Cover all required test cases.
**Prerequisites:** Tasks 1-4.
**Tasks:**
1. Update `tests/test_service.py`:
   - Test `cancel_job` for `queued` job (status becomes `cancelled`).
   - Test `cancel_job` for `running` job (status becomes `cancelled`).
   - Test `cancel_job` for `completed`, `failed`, `cancelled` jobs (idempotent, no change).
   - Test `cancel_job` for unknown job ID (not-found error).
2. Update `tests/test_worker.py`:
   - Test worker skips execution if job is `cancelled` when dequeued.
   - Test worker does not overwrite `cancelled` with `completed` if handler succeeds.
   - Test worker does not overwrite `cancelled` with `failed` if handler raises.
   - Test worker updates status to `completed`/`failed` for normal (non-cancelled) jobs.
3. Update `tests/test_api.py`:
   - Test `POST /jobs/{job_id}/cancel` for valid job (returns 200 + job data).
   - Test `POST /jobs/{job_id}/cancel` for unknown ID (returns not-found).
4. Update `tests/test_repository.py` (if necessary):
   - Ensure repository correctly persists and retrieves `cancelled` status.
5. Update `tests/test_queue.py` (if necessary):
   - Verify queue does not need changes (constraint says "does not need a remove operation").

**Acceptance Condition:**
- All specified test cases pass.
- Regression tests for existing non-cancelled jobs still pass.
- Code coverage for cancellation logic is sufficient.
