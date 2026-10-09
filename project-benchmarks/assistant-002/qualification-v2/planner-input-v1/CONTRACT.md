# ASSISTANT-002/v1 — candidate-visible contract

All requirements describe the complete deliverable. No hidden product requirements,
mandatory response headings or model-output JSON forms. Returned structures are
ordinary Python dict/list/bool/int/str, detached from mutable input and internal state.
Use the supplied read-only `assistant_simulator.event_contract` for event validation,
UTC timestamp parsing (`instant`), identifier checks and canonical JSON (`canonical`).
That helper preserves Assistant-001/v1 semantics. Do not copy a Journal implementation.

## S01. Scenario validation and identity
Export `normalize_scenario(raw) -> dict` and `scenario_digest(raw) -> str`.
Invalid inputs raise ValueError, including wrong types, unknown/missing fields,
nonfinite values and invalid nested events. Never modify inputs.

A scenario is an exact dict with these keys:
- `schema_version`: integer 1, not bool.
- `scenario_id`: `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`.
- `start_at`: valid timestamp under the supplied helper; normalize to UTC with
  exactly six fractional digits and Z. Adding duration must not overflow datetime.
- `duration_ms`: integer 0–86400000, not bool.
- `events`: list of 0–256 event-entry dicts, in authored order.
- `checkpoints`: list of 1–64 expected-observation dicts in strictly increasing time.
No top-level keys are optional.

Event-entry required keys are `key`, `at_ms`, `event`; optional keys are `delay_ms`
(default 0), `duplicate_after_ms` (default []), `drop` (default False). No other keys.
`key` uses the scenario_id syntax and is unique within this scenario. `at_ms` and
`delay_ms` are nonnegative integers, not bool, bounded by duration_ms. Each duplicate
offset is a positive integer, not bool, bounded by duration_ms. At most eight offsets,
strictly increasing. `drop` is exactly bool. `event` follows the supplied normalizer;
normalized output includes all eight Assistant-001 fields, including default TTL.
An event_id may deliberately recur under another entry key, with identical OR
conflicting content; do not deduplicate, resolve or suppress it in the simulator.

Primary delivery time = at_ms + delay_ms. Extra deliveries occur at primary time
+ each duplicate offset. Every computed time must be <= duration_ms, EVEN for a
dropped entry. Total scheduled deliveries from non-dropped entries must be <=1000.
All entries, including dropped events, must validate. No truncation to fit limits.
Event timestamp is separate from delivery time: past/future/skewed timestamps are
permitted under the event helper. Never rewrite timestamp, event_id, confidence or
TTL to match arrival time. Data strings are inert, not instructions or code.

Checkpoint dict: exactly `at_ms` (integer 0–duration_ms, not bool) and `expected_ids`
(list of 0–1000 distinct valid event-ID strings under the event helper). Normalize
expected_ids to ascending lexical order. Empty observations are valid and mean no
current evidence, not that every person/device is absent. Checkpoints must already
be strictly time ordered; reject rather than sort malformed input.

Normalized scenario preserves authored event/checkpoint order and materializes
optional defaults. Identity is lowercase SHA-256 of UTF-8 canonical JSON of the
ENTIRE normalized scenario, including expected IDs and transforms, with no newline.
Equivalent time offsets/defaults/dict key order produce the same digest. Changing
an event, expectation, transform, duration or list ordering changes identity.
No wall clock, filesystem, randomness, environment or sink access is involved.

## S02. Deterministic delivery compilation
`compile_schedule(raw) -> list[dict]` first validates the WHOLE scenario.
Each record has exactly `delivery_id`, `at_ms`, `event`. Primary ID is `key/0`;
duplicate IDs are `key/1`, `key/2`, ... in duplicate_after_ms order. Drop removes the
primary AND all its duplicates. Each record/event is a detached copy, including
between duplicate records. Event IDs and content are unchanged by retransmission.

Order by (computed at_ms, original event-entry index, copy index), NOT by event
timestamp, key, event_id, confidence or dict iteration order. This is a stable
cross-process ordering, not a seeded random shuffle. Delivery IDs are unique.
Same scenario produces byte-identical canonical schedule across repeated calls.

## S03. Virtual-time replay and injected journal
Export `Replay(raw, sink)`. The sink supplies `append(event) -> bool` and
`current_state(*, as_of: str) -> list[dict]`, matching Assistant-001/v1. Validate
before interacting with it. Never create, reset, close, replace or inspect sink
internals. No SQLite, file writes, sleeps, threads or provider calls in replay.

`advance(to_ms) -> dict` accepts an integer, not bool, from current_ms to duration_ms
inclusive. Initial current_ms is 0, cursor 0, inserted 0, duplicates 0. Deliver every
not-yet-consumed scheduled entry with at_ms <= to_ms, once per successful cursor
advance, in compiled order. Each sink call gets a detached event. Append must return
exactly True (new insertion) or False (idempotent duplicate), not truthy integers.
A non-bool response raises ValueError and does not advance that delivery's cursor.
Do not suppress duplicate calls: the journal decides whether they are duplicates.

After each successful append, increment cursor and exactly one count, and set
current_ms to that delivery's at_ms. When all due deliveries succeed, set current_ms
to to_ms, then query current_state(as_of=start_at + to_ms/1000), preserving exact
millisecond precision. All events at a checkpoint time arrive BEFORE its state query.
Return exactly {`at_ms`, `as_of`, `deliveries`, `state`}; deliveries includes only
calls completed during THIS advance, each with delivery_id, event_id, at_ms and
inserted (bool). State is a detached copy of the sink's result. Do not derive or
correct state yourself. Repeating the same advance makes no new append calls but
queries state again. Zero events and zero duration are valid.

Sink exceptions propagate. Stop immediately: no later delivery is attempted and no
checkpoint state query is made after append fails. Preserve prior successful cursor
updates. A state-query failure occurs AFTER due deliveries/clock commit; retrying
that time must not reappend them. Replay offers no transaction spanning multiple
sink calls and no rollback promise for a partially delivered scenario.

## S04. Checkpoint and restart semantics
`replay.checkpoint() -> dict` returns exactly:
{`schema_version`:1, `scenario_sha256`:digest, `cursor`:N, `current_ms`:N,
 `inserted`:N, `duplicates`:N}.
`Replay.from_checkpoint(raw, sink, saved) -> Replay` validates scenario/checkpoint
without sink calls. All integer fields exclude bool. Cursor is 0–schedule length;
counts are nonnegative and sum to cursor; clock is 0–duration. Version and hash
must match exactly. No unknown fields. Last consumed delivery cannot be after the
clock; next pending delivery cannot be BEFORE the clock. Equal-time partial progress
is valid. Detached checkpoint copies cannot mutate the Replay.

Reject corrupted, foreign or changed-scenario checkpoints; no silent reset, skip,
retimestamp or best-effort merge. Checkpoints are plain JSON-serializable records;
persisting them atomically belongs to the caller and is not implemented here.

Delivery is AT LEAST ONCE across crashes: restore the LAST saved checkpoint and
reuse the same persistent sink. If append committed before the caller saved progress,
the same event may be delivered again; its immutable event_id lets the journal
return False. Do not claim exactly-once delivery or deduplication by the simulator.
Counts describe confirmed calls on this replay lineage, not all historical journal
writes; an uncheckpointed successful call can become a duplicate after restore.
There is no resume into a fresh empty sink guarantee and no concurrent replay-owner
protocol or cryptographic checkpoint authentication.

## S05. Expected-observation evaluation
`evaluate_scenario(raw, sink) -> dict` uses a fresh Replay and calls advance at each
declared checkpoint. Validate the entire scenario before any sink call. Extract
observed event_ids from the returned state, validate IDs and reject duplicates with
ValueError. Compare as sets; do not depend on the sink's list order. Never replace
expected IDs with observed IDs or silently ignore an expectation.

Each check returns exactly at_ms, as_of, expected_ids, observed_ids, missing,
unexpected, passed. Every ID list is lexically sorted. Missing = expected minus
observed; unexpected = observed minus expected; passed iff BOTH are empty.
Continue after expectation mismatches. After the last checkpoint, advance to
scenario.duration_ms only if that time has not already been reached, so remaining
events are delivered. Errors still propagate; no fabricated successful report.

Report exactly scenario_id, scenario_sha256, passed, delivered, inserted, duplicates,
checks. Counts come from final Replay progress; passed iff all declared checkpoints
passed. Mismatched expectations are a report with passed=False, not a transport error.
No numerical quality score or claim that a passing report proves Assistant reasoning.

## S06. Local CLI and usable delivery
`python -m assistant_simulator COMMAND --input PATH [--db PATH]`:
- `validate`: one JSON object {scenario_id, scenario_sha256, deliveries}.
- `schedule`: the compiled schedule as one JSON array.
- `jsonl`: one canonical normalized event per line, in delivery order, including
  duplicates and excluding dropped entries; final LF for each event, empty output
  for empty schedule. This is batch-ingestion input, NOT timed replay metadata.
- `run --db PATH`: lazily import `assistant_journal.Journal`, open the explicit DB,
  evaluate_scenario against it, output its report, and always close the owned journal.
  Other commands must work with NO assistant_journal installed. No pip install,
  model calls, server, GUI, dynamic plugin discovery or automatic database selection.

Read UTF-8 scenario JSON. Success exit 0 and stderr empty; failed expectations exit
1 with the complete report on stdout and stderr empty. Invalid input, missing files,
missing journal dependency, invalid parameters and sink errors: exit 2, stdout empty,
a JSON object containing a nonempty `error` string on stderr, without raw payloads
or traceback. Complete compilation/evaluation BEFORE writing output. --help can use
ordinary argparse help and exit 0. Do not reset a journal to force expectations to
pass; a pre-existing journal may legitimately produce unexpected observations.

Implement meaningful tests in tests/test_candidate.py; preserve public examples.
README explains runnable CLI examples, virtual versus real time, journal dependency,
duplicate/drop/delay semantics, at-least-once replay, checkpoint responsibility,
partial failures and no OS sandbox. Human review assesses documentation and test
quality; acceptance does not parse a magic heading as proof. Handoff is free prose.

## Explicit exclusions
Assistant intelligence or notifications, live device actions, real household data,
real-time pacing, probabilistic faults, atomic scenario delivery, journal redesign,
production retention/migration/concurrency, exactly-once delivery, malicious-code
containment and automatic deployment. No real benchmark or model is run by unit tests.
