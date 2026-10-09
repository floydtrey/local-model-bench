# ASSISTANT-001 — Independent reference plan for Persistent Event Journal

**Reference revision:** draft-1 · **Approval:** `OWNER_REVIEW_PENDING` · **Visibility:** assessor/owner only during blind Planner qualification.  
**Source:** frozen ASSISTANT-001/v1 `PROJECT_INTENT.md`, `CONTRACT.md`, `TASKS.md`, `packet.json` and independent assessor, pinned in [TRACEABILITY.json](TRACEABILITY.json).  
**Evaluation purpose:** Compare a Planner candidate's independently proposed implementation plan against **equivalent outcomes**, not identical headings, task counts or particular internal algorithms. This document is **not** the candidate-visible Planner packet. It adds no project requirement, Governor grant, accepted exception, production permission or role qualification.

## 1. Objective and completion boundary

Deliver a local, reusable **Python 3.10+ standard-library-only** event journal with explicit SQLite file persistence, safe validation, idempotent append, bounded ordered history, deterministic time-indexed current observations, atomic bounded ingestion, and a small JSON CLI. The journal preserves observations as evidence; it must not infer household reality or connect to external services.

**Non-negotiable interface and semantic contract:** existing `v1/CONTRACT.md` R01–R06. The original contract is normative if this plan paraphrases a point imprecisely. Do not silently change benchmark decisions about global identifiers, 300-second default TTL, explicit replay clock, latest-observation expiry or no stale resurrection. Those are benchmark-v1 rules, **not** owner-approved production protocol decisions.

**Completion evidence:** independently executed checks against the final code hash, verification of task file scope, useful model-authored tests and documentation, understandable implementation, real SQLite on disk, and substantive human review. V1 contains **79 cumulative** acceptance checks; those are not 79 independent projects. Model prose claiming success is not test evidence; human/owner approval is necessary before real Assistant integration.

## 2. Capability-to-requirement traceability (reference oracles, not Planner hints)

| Requirement | Minimum outcome | First bounded Worker task | Representative failure that must be caught |
| --- | --- | --- | --- |
| R01 | Strict detached `normalize_event`; real timezone-aware, six-digit UTC timestamps; canonical nested JSON and exact types/limits | T01 | Coerced/corrupt event, invalid Unicode/time, unsafe data interpretation |
| R02 | Durable SQLite `Journal`; global immutable identity and canonical duplicate/conflict behavior; committed before return | T02 | Silent evidence overwrite, database reset or lost post-append commit |
| R03 | Validated bounded history ordered by normalized event-time plus event ID, with combined filters and half-open time bounds | T03 | Paging before filtering, ordering by arrival, invalid empty-DB queries |
| R04 | Explicit-`as_of` source-separated latest observation with exact TTL expiry and **no resurrection** | T04 | Expired-latest restored from older event or future-event suppression |
| R05 | Up-to-1000-event `append_many` as a single all-or-nothing transaction, with correct duplicate flags | T05 | Partial persistence after an invalid or conflicting later row |
| R06 | Runnable `python -m assistant_journal --db ...` CLI, consistent JSON outputs/errors, atomic UTF-8 JSONL import and README/tests | T06 | Raw payload/traceback leak, bad exit status, non-atomic ingest |

The accompanying `TRACEABILITY.json` records the exact existing T01–T06 writable-file policy, source Git blobs, all 45 named decorated assessor test methods grouped by stage, and the fact that the frozen check inventory also contains generated cases. It is an **assessor-owned** traceability aid, not a new hidden product requirement.

## 3. Proposed bounded task plan and rationale

This six-stage implementation is the **reference implementation plan** because dependencies are naturally sequential. It aligns task IDs with the existing Worker baseline so outcomes can be mapped to the frozen v1 tests. The independent Planner may choose a different viable decomposition without penalty if every material requirement remains covered.

### Task T01 — Define event validation and immutable canonical identity (R01)

**Inputs:** already supplied starter package and candidate-visible `CONTRACT.md`; `assistant_journal/validation.py` stub.  
**Writable for the original Worker benchmark:** `assistant_journal/validation.py`, `tests/test_candidate.py`.

Build a single strict normalization boundary used by all later journal operations. Validate exactly seven required input fields and one optional TTL; reject extras, bool-as-int, omitted fields, malformed IDs, naive/overflowing or excess-precision timestamps, nonfinite confidence, wrong TTL bounds, cyclic/deep JSON and oversized canonical data. Normalize UTC with exactly six fractional digits and terminal Z; detach all nested mutable data. Canonical JSON identity must respect the specified 1 vs 1.0 data distinction, while equivalent timestamp offsets/default TTL normalize identically. Strings in event data are inert values and never instructions.

**Acceptance evidence:** events roundtrip detached; input is unchanged; timezone-equivalent inputs canonicalize; input validation rejects all prescribed boundary and error classes; public and independent R01 checks pass.  
**Critical fail:** loss/corruption/coercion of evidence, mutable aliasing or any execution/interpretation of data strings.  
**Dependency:** none; later tasks use this boundary.

### Task T02 — Persist immutable events and manage SQLite lifecycle (R01–R02)

**Inputs:** accepted T01 API and actual prior code.  
**Writable:** `assistant_journal/journal.py`, `tests/test_candidate.py`.

Open the explicit existing-parent SQLite path. Represent each event's global `event_id` and its detached normalized payload so an identical canonical retry returns `False` without mutation; a conflicting retry raises `EventConflictError` and leaves the original untouched. Return `True` only for a new committed event. Use a transaction/connection discipline that commits before `append` returns and correctly propagates DB/corruption failures; never silently replace records, choose another DB, reset on corruption, or infer concurrency beyond the contract. Implement `get`, `count`, idempotent `close` and error-on-closed behavior. Two separately opened journal instances must see sequential committed writes.

**Acceptance evidence:** duplicates/conflicts (including cross-source same ID), process exit without close, reopen, two connections, detached `get`, invalid append immutability and corrupt-file preservation.  
**Critical fail:** event overwrite, reset, uncommitted success, accidental insertion after rejection.  
**Dependency:** canonical T01 event representation.

### Task T03 — Provide bounded deterministic history (R01–R03)

**Inputs:** accepted persisted event store and T01 validation helpers.  
**Writable:** `assistant_journal/journal.py`, `tests/test_candidate.py`.

Build `history` with exact-match optional source/entity/type and normalized since/until filters. Validate query arguments **before** an empty-result shortcut; apply all filters before pagination. Sort by normalized timestamp then event_id **ascending**, independently of delivery order. since is inclusive; until exclusive; equal bounds return empty; limit 1–1000, offset >=0 and bool invalid. Return detached normalized event objects. Preserve expired/future events as immutable history.

**Acceptance evidence:** tie-breaks, combined filter+page, validation on empty store, time-bound boundaries, beyond-end paging, detached results, future/expired evidence retained.  
**Critical fail:** filtering after paging, silent invalid parameters, mutating/deleting evidence.  
**Dependency:** T02 durable store and T01 canonical timestamps.

### Task T04 — Project explicit-time current observations (R01–R04)

**Inputs:** time-indexed records and validated history; explicit caller-supplied `as_of`.  
**Writable:** `assistant_journal/journal.py`, `tests/test_candidate.py`.

For every (`source`, `entity`, `type`) select the maximum (`timestamp`, `event_id`) among events whose timestamp is **not later than** `as_of`. Include the winner only while `as_of < timestamp + ttl_seconds`; at exact expiry remove it, **never resurrect an older event**. A future event must not hide an earlier still-current observation. Sorting of output winners is by source/entity/type. Confidence is stored evidence, never selection authority; do not fuse sources, infer absence/presence from missing evidence, identify people, sample wall-clock time or use a background expiry scheduler. Exact same input and replay clock must produce the same state after restart.

**Acceptance evidence:** late and out-of-order appends, future observations, identical timestamps with event-ID tie, expiry boundary, latest-expired-old-still-valid, source/type separation and order-independent restart replay.  
**Critical fail:** stale resurrection, false absence inference, cross-source state collapse.  
**Dependency:** stored event/time semantics from T01–T03.

### Task T05 — Commit bounded ingestion atomically (R01–R05)

**Inputs:** existing `append` semantics, current state and DB transaction handling.  
**Writable:** `assistant_journal/journal.py`, `tests/test_candidate.py`.

Implement `append_many` for exact list of 0–1000 events. Validate and apply writes as one database transaction that either commits every new event or rolls back **all** changes from this batch. Return inserted/duplicate flags in input order. Preserve existing data, cross-batch/within-batch duplicate semantics, and a usable journal after late conflict or validation failure. Empty list is valid and has no side effects. Avoid accidentally committing earlier members of the failed batch.

**Acceptance evidence:** conflict in last record, validation failure after earlier valid records, duplicate within batch, duplicates against database, bounds, rollback then successful later append, unchanged current state after rejection.  
**Critical fail:** partially persisted records, lost prior evidence, broken DB transaction state.  
**Dependency:** stable transactional store and current-state query.

### Task T06 — Deliver a real offline CLI, test coverage and documentation (R01–R06)

**Inputs:** accepted T01–T05 public APIs.  
**Writable:** `assistant_journal/cli.py`, `tests/test_candidate.py`, `README.md`.

Expose `python -m assistant_journal --db PATH` with `append`, `ingest`, `get`, `count`, `history`, `state`. Emit exactly one JSON object/value on stdout for success (exit 0, stderr empty). On conflict, invalid data/parameters, missing files or database error, emit no stdout and one JSON error object with nonempty error string on stderr (exit 2); never print raw events/secrets or Python traceback. UTF-8 JSONL ingest ignores blanks but rejects invalid/late conflicts **atomically** and caps nonblank events at 1000. Support help. Add meaningful candidate tests without removing public examples. Document example commands, global duplicate identity, TTL/replay semantics, restart durability, source-separated state and explicit absence of an OS sandbox.

**Acceptance evidence:** actual independent CLI subprocess and module import, Unicode path, count/get/history/state output, JSONL errors and rollback, correct help/errors, candidate/public tests executed and README usable.  
**Critical fail:** non-atomic ingest, traceback/raw sensitive payload emission, hidden benchmark dependency, fabricated verification claims.  
**Dependency:** all preceding released APIs.

## 4. Cross-task gates and plan alternatives

**Original v1 Worker sequence:** every T0x passes cumulative R01–R0x assessor checks, obeys the exact task writable paths and supplies a useful free-prose handoff before another fresh role session receives its actual code. Failed successors are recorded as blocked; *never* paste in reference code or another model's fixes. The reference plan does **not** itself authorize executing a model. A separate trusted authority record must be approved in T09.

**Plan-equivalence test:** the Planner candidate might combine validation/data model in one task, split persistence from duplicate resolution, or organize tests/documentation throughout the implementation. Accept when dependencies, API semantics, scoped work and fully testable outcomes are preserved. Do not demand six tasks or these exact headings. Penalize overengineering only when it increases unneeded scope/risk or hides critical testability.

**Non-equivalent plan examples (FAIL unless appropriately flagged BLOCKED for missing authority):**
- TTL from delivery/arrival time, implicit clock or an expired latest observation restored to a prior one.
- Global IDs mistakenly scoped per source, replacement on conflicting duplicate, or successful append that has not been committed.
- Pagination applied before filtering or history dropping expired records.
- `append_many` performing independent commits or quietly ignoring a late conflict.
- An HTTP server, camera/HA/KC integration, production data access or required third-party dependencies in this deliberately offline standard-library deliverable.

**Allowed assumptions:** existing starter package and Python 3.10+ standard library, real SQLite at an explicitly provided disposable path and no concurrent writer/performance SLA. A Planner should surface missing external deployment/security policy rather than invent owner authorization.

## 5. Reviewer acceptance and unresolved approval

The v2 assessor can check independently that a proposed plan covers R01–R06 and ranks tasks in a feasible dependency order. Human review must judge the **substance** of materially different approaches and risk treatment. A passing code suite later does not automatically qualify the Planner, Governor or produced component.

**Owner status:** `OWNER_REVIEW_PENDING`. No owner review or production promotion is represented by this document. Keep the candidate-visible v1 `CONTRACT.md` unchanged. Never copy this file or `TRACEABILITY.json` into a blind Planner's prompt/workspace, direct tools or ancillary retrieved context. After review, T09 can assemble a separately authorized Worker handoff with a fixed plan identity; this draft alone is not an authority grant.
