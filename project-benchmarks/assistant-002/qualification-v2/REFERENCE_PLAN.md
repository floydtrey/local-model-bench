# ASSISTANT-002 — Independent reference plan for Event Simulator and Replay

**Reference revision:** draft-1 · **Approval:** `OWNER_REVIEW_PENDING` · **Visibility:** assessor/owner only for independent Planner qualification.  
**Source:** frozen ASSISTANT-002/v1 `PROJECT_INTENT.md`, `CONTRACT.md`, `TASKS.md`, `packet.json`, `UPSTREAM.json` and assessor; source Git object identities recorded in [TRACEABILITY.json](TRACEABILITY.json).  
**Evaluation purpose:** Evaluate whether a Planner proposes a feasible architecture and bounded work that delivers **equivalent simulation/recovery outcomes**. The candidate may choose different task boundaries or implementation details; this reference is not visible to that Planner. It does not grant operational authority or change any v1 benchmark rule.

## 1. Problem statement, boundaries and supplied dependencies

Build a usable **offline Python 3.10+ standard-library** simulator that accepts declared observation scenarios and deterministically compiles virtual-time delivery schedules; replays them into an injected journal sink; checks captured observations against authored expectations; and resumes from a validated checkpoint **at least once** after interrupted progress. Deliver a library and standalone CLI. It must not manufacture missing observations, infer personal presence, alter an input event's timestamp to match delivery, or execute live household actions.

Normative contract: the existing **S01–S06** in `v1/CONTRACT.md` (all cumulative). Distinguish three clocks: scenario `start_at` establishes virtual epoch, each event's original event-time is immutable, and delivery `at_ms` determines when the simulator calls the injected journal. No wall-clock sleeps, threads or probabilistic loss simulation. Transforms are authored and deterministic.

**Provided code that MUST be reused:** `assistant_simulator.event_contract` is a read-only helper exposing Assistant-001-normalizer-compatible `normalize_event`, `instant`, `canonical` and identifier checks. `v1/UPSTREAM.json` pins the source, transformation and hashes. This is trusted benchmark-supplied support, **not** evidence of a model-built ASSISTANT-001 Journal. The `Journal` itself is supplied as an injected interface; the simulator must **not** implement/clone it. A real `assistant_journal.Journal` is optional only for the `run --db` CLI path and for separate pair-interoperability assessment.

**Trust boundary:** the assessor can use a spy sink and a pinned calibration Journal to measure simulator behavior without supplying their implementations to the candidate. Candidate-visible starter is only the unsolved simulator, explicit helper, public tests and contract. No assessor reference solution may enter the Planner input or Worker continuation.

## 2. Coverage trace against the frozen six-stage project

| Requirement | Minimum independently verifiable behavior | First bounded Worker task | Critical wrong behavior |
| --- | --- | --- | --- |
| S01 | Strict scenario/schema/event/checkpoint validation, authored-order preservation, canonical SHA-256 identity, detached normalized data, defaults and bounds | T01 | Invalid scenario accepted, expectation change omitted from identity, input mutated |
| S02 | Compile stable (delivery time, original entry index, duplicate index) delivery schedule with immutable original events and explicit drops/retries | T02 | Lost duplicate, event-time sort, changed event IDs, unreliable tie order |
| S03 | Replay on virtual clock through injected `append`/`current_state`, strict bool result, per-delivery progress and error interruption | T03 | Cursor advanced before acknowledgement, sink substituted, state queried early |
| S04 | Exactly formatted scenario-bound checkpoint, all progress invariants, caller-owned persistence and at-least-once recovery against same persistent sink | T04 | Foreign/malformed checkpoint accepted, uncommitted progress skipped, exactly-once claim |
| S05 | Evaluate authored checkpoint expectations using actual sink state; both missing **and unexpected** sets; continue mismatches, drain later events | T05 | Rewrites expectations to match observation, unexpected-only reports PASS |
| S06 | Offline `validate/schedule/jsonl`, lazy optional Journal `run --db`, strict exit status and JSON/JSONL output, tests and documentation | T06 | Live dependency for offline commands, silently resets existing DB, mixed output/traceback |

`TRACEABILITY.json` contains all six cumulative requirements, exact writable scopes, source Git hashes, 44 named decorated assessor methods, and the authored scenario inventory. The frozen suite contains **96 cumulative checks**, including generated invalid-input and scenario checks; neither number represents independent full projects. The normative candidate contract and frozen assessor remain unchanged.

## 3. Bounded reference implementation plan

This six-stage outline follows the existing Worker task IDs for auditability, but independent Planner evaluation must compare **effects**, not force these particular headings/task count.

### Task T01 — Normalize and identify full scenarios (S01)

**Original v1 writable paths:** `assistant_simulator/scenario.py`, `tests/test_candidate.py`.  
**Dependencies:** supplied `event_contract` API; no Journal implementation.

Implement `normalize_scenario(raw)` and `scenario_digest(raw)` as pure deterministic functions. Validate exactly schema_version=1, scenario ID pattern, timezone-aware start_at UTC representation, 0–86400000-ms duration, 0–256 events, 1–64 checkpoints, unique entry keys, event timestamp/TTL through the helper, all computed delivery-time bounds and <=1000 total nondropped deliveries. Each event entry has exact permitted fields, defaults, bounded at/delay/strictly increasing duplicate offsets (max eight), bool drop. Checkpoint at_ms must already be strictly increasing; expected_ids must be valid, unique and lexically normalized. Preserve authored event/checkpoint order; reject rather than silently repair malformed input. Canonical hash covers **all** normalized material including expected IDs, event order, transforms and duration; no filesystem or sink interaction.

**Acceptance evidence:** equivalent offsets/defaults canonicalize to same digest; changing any expectation/order/transform changes digest; nested normalized output detached from input; valid empty event set and zero duration; malformed event/clock/duplicate/key/checkpoint violations rejected.  
**Critical fail:** mutating scenario evidence, hashing without expectations, or silently dropping bad inputs.

### Task T02 — Compile deterministic delivery schedule (S01–S02)

**Writable:** `assistant_simulator/schedule.py`, `tests/test_candidate.py`.  
**Dependency:** validated normalized S01 scenarios.

Generate a record `{delivery_id,at_ms,event}` for each nondropped primary and duplicate: primary ID `key/0`, duplicate `key/1`, `key/2` etc. Time is declared entry at_ms + delay_ms + optional duplicate_after_ms. Even dropped entries' hypothetical delivery bounds were checked in T01; **drop removes primary and all duplicates**. Preserve original event_id, timestamp, confidence, TTL, data exactly; conflicting IDs remain valid simulator deliveries for the journal to decide. Sort by **(computed delivery at_ms, original authored event-entry index, copy index)**, not event timestamp or alphabetical key; return distinct detached event dicts including between duplicates. Repeated calls with same scenario produce byte-identical canonical schedules.

**Acceptance evidence:** simultaneously scheduled entries retain authored tie order; delayed old observation is not conflated with recent event timestamp; repeated event IDs do not disappear from schedule; dropped copies never deliver; detached duplicate records resist input/sink mutation.  
**Critical fail:** spontaneous suppression of duplicates, nonreproducible order, altered event identity.

### Task T03 — Replay through a strictly injected sink and virtual clock (S01–S03)

**Writable:** `assistant_simulator/replay.py`, `tests/test_candidate.py`.  
**Dependency:** T02 schedule; existing **external** `append(event)->bool`, `current_state(as_of=...)` sink interface only.

Build `Replay(raw,sink)` and `advance(to_ms)` with start cursor/current_ms/counters zero. Reject backward/noninteger/out-of-duration progression **before** interacting with sink; deliver every due record in compiled order at most once per successfully recorded cursor advance, giving the sink a detached event per call. Require append response to be exactly bool `True` (inserted) or `False` (duplicate), not numeric truthiness. After **each successful** append, update cursor, inserted/duplicate counts, virtual current_ms; on exception or invalid acknowledgement stop immediately, do not query state or skip the problem record; keep earlier acknowledged progress. After all due entries succeed set current_ms=to_ms and query sink `current_state(as_of=start_at+to_ms/1000)` with precise millisecond UTC; process all deliveries at an evaluation instant **before** querying state. Returning to the same clock time yields no new append, but a fresh state query. A query error occurs after deliveries were committed and must **not** cause them to be reappended during retry.

Never create/close/inspect sink internals, implement Journal, touch SQLite, use sleep/thread/wall clock or fabricate the state.

**Acceptance evidence:** spy sink captures precise call order/identity, state boundary after all due calls, partial failure resumes at unacknowledged cursor, query failure doesn't redeliver, nonbool acknowledgments rejected, detached result, no future-delivery calls.  
**Critical fail:** acknowledged progress lost inside one Replay, false success after sink exception, clock mixing.

### Task T04 — Checkpoint and recover with at-least-once semantics (S01–S04)

**Writable:** `assistant_simulator/replay.py`, `tests/test_candidate.py`.  
**Dependency:** deterministic event schedule and complete T03 progress accounting.

Implement `checkpoint()` with **exact** `schema_version,scenario_sha256,cursor,current_ms,inserted,duplicates`; values detached and JSON serializable. `Replay.from_checkpoint(raw,sink,saved)` validates schema/version, matching full-scenario digest, integer/bool distinctions, cursor limits, inserted+duplicates=cursor, in-range clock, previously consumed vs pending delivery ordering and equal-time partial cursor. Reject foreign/stale/corrupted snapshots without interacting with the sink; never truncate/skip/retimestamp to repair them.

State persistence is **the caller's responsibility**; simulator has no atomic filesystem checkpoint storage guarantee. Reopen from the **last saved** snapshot against the **same persistent Journal**. If an append committed but the caller lost the acknowledgement or did not persist cursor, replay may call that immutable event_id again and the journal will return False. This is at-least-once retry plus sink idempotency, **not exactly-once delivery**, and counts refer to this replay lineage, not all DB history. No new owner lease, fresh empty sink recovery promise, or automatic resume into another scenario.

**Acceptance evidence:** wrong digest or expectation version rejected; cursor/count/clock tampering rejected; equal-time partial state allowed; restart after lost checkpoint or lost acknowledgement returns duplicate and keeps original event.  
**Critical fail:** data skipped on recovery, false exactly-once claim, foreign checkpoint accepted.

### Task T05 — Compare observed evidence with authored expectations (S01–S05)

**Writable:** `assistant_simulator/evaluate.py`, `tests/test_candidate.py`.  
**Dependency:** working Replay/valid checkpoint semantics and injected Journal-compatible sink.

Implement `evaluate_scenario(raw,sink)`: fully validate before any sink call, create fresh Replay and advance through each authored checkpoint. Extract event IDs from the **actual sink state** and validate them, reject duplicate or malformed observed IDs. Sort expected/observed IDs and compute **missing=expected-observed**, **unexpected=observed-expected** separately as sets. Continue over expectation mismatches to report all checkpoints; don't replace authored IDs or treat an unexpected-only discrepancy as success. Once last checkpoint is evaluated, advance to scenario.duration_ms if necessary to deliver later events. Surface append/state failures without fabricated successful report. Final report includes scenario identity, overall bool, delivered/inserted/duplicates from the Replay lineage and all checkpoint reports.

**Acceptance evidence:** both missing and unexpected diagnostics, stable sorting, full mismatch collection, late-delivery drain, terminal time not queried twice, errors propagated; independent journal integration verifies state honesty.  
**Critical fail:** cheating by overwriting expectations, hiding unexpected evidence or claiming PASS after sink failure.

### Task T06 — Deliver reliable offline CLI, tests and documentation (S01–S06)

**Writable:** `assistant_simulator/cli.py`, `tests/test_candidate.py`, `README.md`.  
**Dependencies:** S01–S05 public API and provided event_contract; optional runtime-only real Journal import.

Expose `python -m assistant_simulator COMMAND --input PATH [--db PATH]`. `validate` emits scenario_id/hash and number of deliveries; `schedule` emits schedule JSON; `jsonl` emits canonical normalized events **per delivery** (including repeats, excluding drops) and final LF per event, empty output for no deliveries. These **three commands must work with NO Journal installed**. Only `run --db PATH` lazily imports `assistant_journal.Journal`, opens the exact explicit DB, assesses the scenario and reliably closes the owned Journal; must **not reset existing DB** to turn mismatches into passes.

Successful commands exit 0 and leave stderr empty. Authored expectation mismatch on `run` returns full JSON report on stdout and exit **1** with stderr empty. Invalid input, missing dependency/path, command misuse and sink errors return exit **2** with empty stdout, one nonempty JSON error string on stderr, no raw payloads/tracebacks or partial output. `--help` uses normal argparse help. Add meaningful tests and README explaining time, schedule transforms, injected journal, at-least-once checkpoints, caller persistence, partial failures and lack of OS sandbox.

**Acceptance evidence:** real module CLI subprocess without local journal for offline modes, Unicode path/content, JSONL retains duplicates, errors/exit classifications exactly match, wrong expectations preserved as exit 1, preexisting DB not reset, public/candidate tests executed.  
**Critical fail:** rewriting journal, leaking sensitive data, coupling offline commands to services, false test claims.

## 4. Authored scenario evidence and noninferred truths

All eight named files are frozen in `v1/starter/scenarios/`; they contain authored `expected_ids` and are public candidate inputs. Their actual expected values are **not generated by the simulator under test**.

| Scenario | Important verification question |
| --- | --- |
| `clock-skew.json` | A future event timestamp can arrive early but remain ineligible until the virtual clock catches up |
| `delayed-delivery.json` | Scheduled arrival and original event time can disagree without changing identity or ordering policy |
| `door-reconnect.json` | Retransmissions retain immutable event IDs; duplicates rely on sink and eventually expire |
| `dropped-presence.json` | A dropped entry generates zero deliveries, including retransmissions |
| `expired-latest.json` | A latest expired observation does not resurrect an older one |
| `late-observation.json` | A late older event cannot overrule a newer eligible event |
| `quiet-room.json` | No current observations means **unknown**, not a positive claim of real-world absence |
| `sensor-disagreement.json` | Independent sources disagree without cross-source fusion or invented certainty |

**Pair interoperability:** standalone simulator scoring uses spy sink and pinned A001 calibration Journal; a separate `interop` trial can pair two *model-produced* A001/A002 workspaces after individual acceptance and human review. A pair mismatch is attributable to the pair pending independent diagnosis, not automatically to the simulator or Journal; it never qualifies all of A001.

## 5. Alternative valid plans and unacceptable changes

**Valid alternate decomposition:** merge normalization and schedule into one bounded task, split Replay state-progress logic from sink interaction, perform test fixtures earlier, or use different pure helper structure—provided all S01–S06 outcomes, dependency ordering, explicit helper/sink ownership, bounded scopes and CLI evidence remain correct. The reference six-stage structure is a comparison aid, **not** a forced Planner output form.

**Non-equivalent proposals:** implementing a new Journal, requiring real HA/camera/KC data, wall-clock sleeps, stochastic fault rates, replacing event IDs, interpreting expiration as someone's physical absence, asserting exactly-once delivery, using an automatic new database to avoid conflicts, silently merging corrupt checkpoints, hiding unexpected observations, or importing assessor reference code into the candidate.

**Known limitations:** no production retention/migration, no real-time pacing, no global/replay-owner concurrency protocol, no automatic atomic snapshot persistence, no cryptographic checkpoint authentication, no real Assistant reasoning, no malicious-code containment. The benchmark's loopback Ollama controller access is not candidate permission to use the network.

## 6. Progression and owner review gate

The original v1 Worker chain executes from fresh starter with real previous code and free-prose handoff; each T0x must satisfy **cumulative S01–S0x** and its writable paths to proceed. There is no assessor-guided gold repair, automatic reference continuation, or production promotion. A new independent isolated Worker task mode needs identical trusted predecessor seed bytes and provenance; that is future T10, **not** a capability of the current v1 `-Through T0x` launcher.

**Owner status:** `OWNER_REVIEW_PENDING`. This plan is authored for controlled comparison and must be independently reviewed/approved before being treated as an authorized reference for Worker dispatch. The independent Planner must not see this plan, traceability metadata, or fixed `v1/TASKS.md` through prompt, workspace or tools. T05 enforces that boundary. T07–T09 supply reviewed governance cases and separately authorized handoffs; this document itself creates no release, exception or Owner approval.
