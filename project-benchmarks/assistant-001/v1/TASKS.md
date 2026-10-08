# Fixed implementation sequence

This sequence isolates Worker capability. It is not a claim that a Planner
generated or a live Governor approved it. The operator explicitly authorizes a
run. Each next task receives the actual predecessor workspace and full final
response only after cumulative independent acceptance passes. No reference-code
continuation, repair solution, or previous model memory is injected.

## T01: Validate and normalize events

Implement strict input validation and canonical copies. Preserve all API signatures; the remaining Journal methods may remain stubs.

Acceptance: R01 in CONTRACT.md.
Writable files: `assistant_journal/validation.py`, `tests/test_candidate.py`.
All other starter files are protected. Do not implement later tasks early.

## T02: Persist observations and duplicates

Implement SQLite lifecycle, append/get/count/close. Validate through the existing normalization API. Commit before returning and reject conflicting IDs without overwriting evidence.

Acceptance: R01–R02 in CONTRACT.md.
Writable files: `assistant_journal/journal.py`, `tests/test_candidate.py`.
All other starter files are protected. Do not implement later tasks early.

## T03: Query bounded ordered history

Add filtered, stable, bounded history with explicit time bounds. Preserve earlier behavior, including empty-database parameter validation.

Acceptance: R01–R03 in CONTRACT.md.
Writable files: `assistant_journal/journal.py`, `tests/test_candidate.py`.
All other starter files are protected. Do not implement later tasks early.

## T04: Project current state with replay time

Implement current_state using explicit as_of, source-separated keys, deterministic ties, future filtering and no resurrection after latest-event expiry.

Acceptance: R01–R04 in CONTRACT.md.
Writable files: `assistant_journal/journal.py`, `tests/test_candidate.py`.
All other starter files are protected. Do not implement later tasks early.

## T05: Ingest batches atomically

Implement bounded all-or-nothing append_many. Roll back conflicts/invalid later records, maintain prior commits and keep the connection usable.

Acceptance: R01–R05 in CONTRACT.md.
Writable files: `assistant_journal/journal.py`, `tests/test_candidate.py`.
All other starter files are protected. Do not implement later tasks early.

## T06: Deliver the CLI, tests and documentation

Implement every released CLI command and error contract. Add candidate tests and complete README. Run the full public suite and report what is and is not verified.

Acceptance: R01–R06 in CONTRACT.md.
Writable files: `assistant_journal/cli.py`, `tests/test_candidate.py`, `README.md`.
All other starter files are protected. Do not implement later tasks early.
