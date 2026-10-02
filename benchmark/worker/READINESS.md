# Worker Qualification Readiness

## Required before scored Worker runs

- [x] Durable role-specific session behavior tested.
- [x] Separate role sessions preferred over temporary role switching in one session.
- [x] Worker dispatch contract defined.
- [x] Mandatory completion handoff defined.
- [x] Worker role prompt defined.
- [x] Disposable qualification project fixture defined.
- [x] Worker-specific workspace-write sandbox overlay defined.
- [x] Worker receives original intent, full approved plan, exact assigned task, Governor guidance, and prerequisite handoff.
- [x] Test 01 has deterministic scope checks: only the assigned source file may change.
- [x] Test 01 has deterministic behavioral checks.
- [x] Test 01 checks that a handoff note is emitted.

## Test 01 objective

Verify that a Worker can complete Task 1 of a three-task plan without continuing into Tasks 2 or 3.

Expected authorized change:
- reporting/config.py

Files that must remain unchanged:
- reporting/render.py
- tests/test_render.py
- PROJECT_INTENT.md
- APPROVED_PLAN.md
- DISPATCH_TASK_01.md

The Worker must leave a concise handoff note for Task 2.

This first run is a harness/sandbox qualification run using qwen3.5:9b. It is not yet a comparative model score. Once the execution path passes, the same fixture can be run across Worker candidates.
