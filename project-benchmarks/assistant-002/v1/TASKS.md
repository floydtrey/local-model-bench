# Fixed six-task implementation sequence

Each task begins with the actual accepted predecessor workspace and full handoff.
No reference continuation, automatic repair, or mandatory handoff label. This is
a controlled implementation track, not a Planner-generated or Governor-approved plan.

## T01: Normalize scenarios and stable identity

Acceptance: S01 in CONTRACT.md.
Writable paths: `assistant_simulator/scenario.py`, `tests/test_candidate.py`.
Preserve other files and earlier behavior. Read the existing interfaces first.
Implement only the assigned task; later methods may remain stubs.

## T02: Compile deterministic delayed/dropped/duplicate deliveries

Acceptance: S01–S02 in CONTRACT.md.
Writable paths: `assistant_simulator/schedule.py`, `tests/test_candidate.py`.
Preserve other files and earlier behavior. Read the existing interfaces first.
Implement only the assigned task; later methods may remain stubs.

## T03: Drive the journal with a virtual clock

Acceptance: S01–S03 in CONTRACT.md.
Writable paths: `assistant_simulator/replay.py`, `tests/test_candidate.py`.
Preserve other files and earlier behavior. Read the existing interfaces first.
Implement only the assigned task; later methods may remain stubs.

## T04: Validate checkpoints and recover at least once

Acceptance: S01–S04 in CONTRACT.md.
Writable paths: `assistant_simulator/replay.py`, `tests/test_candidate.py`.
Preserve other files and earlier behavior. Read the existing interfaces first.
Implement only the assigned task; later methods may remain stubs.

## T05: Compare declared observations against actual journal state

Acceptance: S01–S05 in CONTRACT.md.
Writable paths: `assistant_simulator/evaluate.py`, `tests/test_candidate.py`.
Preserve other files and earlier behavior. Read the existing interfaces first.
Implement only the assigned task; later methods may remain stubs.

## T06: Deliver the offline CLI, tests and usage examples

Acceptance: S01–S06 in CONTRACT.md.
Writable paths: `assistant_simulator/cli.py`, `tests/test_candidate.py`, `README.md`.
Preserve other files and earlier behavior. Read the existing interfaces first.
Implement only the assigned task; later methods may remain stubs.
