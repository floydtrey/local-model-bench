# Worker Qualification — Test 02 / Intent 04 Pipeline

Date: 2026-10-02

## Purpose

Test 02 uses the already-built Planner Intent 04 and Governor Plan B instead of inventing a new Worker-only project request.

Canonical sources:

- original intent: `benchmark/planner/intent-04-batch-export.md`
- approved plan: `benchmark/governor/plans/plan-b-medium.md`
- Worker role: `benchmark/worker/ROLE_PROMPT.md`

The fixture is a disposable implementation of the project facts described by Intent 04.

## Role boundary correction

Governor Plan B contains four plan tasks, but not every plan task belongs to the Worker role.

Plan B Task 4 is regression-test creation. Under the current pipeline architecture, determining whether adequate tests exist, creating tests when needed, running them, diagnosing bad tests versus real implementation failures, and reporting Pass/Fail belongs to the **Tester** role.

Therefore Worker Test 02 scores only implementation Tasks 1–3.

The first Qwen3.8 smoke executed Task 4 under the Worker role before this routing distinction was corrected. That Task 4 result is role-mismatched evidence and must not invalidate the Worker. Qwen3.8 passed Worker Tasks 1–3 cleanly in that smoke.

The Task 4 specification remains in the repository for future Tester-role qualification, but the Worker runner does not execute it.

## Promotion from Test 01

Only clean Test 01 passers are in the default Test 02 roster:

- qwen3.8 27B
- qwen3.6 35B
- qwen3-coder 30B
- Gemma4 12B
- qwen3.6 27B
- Nemotron 3.5 Lightning 30B
- North Mini Code
- Muse Glimmer

Qwen3.5, GPT-OSS, Granite, and Laguna XS remain documented Test 01 failures/conditional results and are not in the default promotion roster.

## Worker pipeline

Intent 04 is executed as three bounded Worker assignments matching the implementation portion of Plan B:

1. register `export-csv` parser surface;
2. implement service-backed stdout CSV formatting;
3. implement `--output` file/error behavior.

Each task uses a new DSH Worker session. Model weights may remain resident, but conversational role state is not shared between task sessions.

Every dispatch injects:

- the complete original Intent 04 text;
- the complete approved Plan B text;
- the assigned bounded task;
- Governor intent guidance;
- the previous Worker's handoff, when applicable;
- explicit Windows/current-working-directory runtime context;
- the task authority boundary.

The complete approved plan remains visible, including the later Tester-owned task, so the Worker must still respect role/task authority and stop after its bounded implementation task.

The same disposable project workspace persists across tasks, so later Workers see the real files produced by prerequisite Workers.

## Handoff

A task must end with `Handoff note:`.

The runner extracts that note and injects it verbatim into the next dependent Worker task. The next dispatch is saved as evidence, as is the exact prerequisite handoff.

A missing handoff fails the task and stops that candidate's dependent Worker pipeline.

## Scope and later-task restraint

Worker Tasks 1–3 may modify only `inventory/cli.py`.

No Worker task authorizes helper files.

The deterministic stage verifier checks selected later-task boundaries:

- Task 1 must not perform Task 2 CSV-formatting work early;
- Task 2 must not successfully perform Task 3 file-output behavior early.

Plan B Task 4 remains visible as context but is not Worker authority.

## Verification versus Tester role

The benchmark harness still runs deterministic external verification after each Worker task. This is **assessor infrastructure**, not a test of the Worker's ability to author tests.

After every Worker task:

- exact workspace before/after snapshots are compared;
- unauthorized changes/creations/deletions fail;
- task-specific deterministic acceptance verification runs outside the model;
- the fixture's existing regression suite runs;
- handoff presence is checked.

These external checks determine whether the Worker implementation is correct. They do not require the Worker candidate to create test code.

A later Tester-role benchmark should separately evaluate Plan B Task 4 and the Tester contract.

## Smoke before batch

Run the corrected Qwen3.8-only smoke first:

`benchmark/run-worker-intent04-smoke.cmd`

Only after the three-task Worker pipeline and harness behavior are validated should the promoted eight-model batch run:

`benchmark/run-worker-intent04-batch.cmd`
