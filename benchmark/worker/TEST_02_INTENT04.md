# Worker Qualification — Test 02 / Intent 04 Pipeline

Date: 2026-10-02

## Purpose

Test 02 uses the already-built Planner Intent 04 and Governor Plan B instead of inventing a new Worker-only project request.

Canonical sources:

- original intent: `benchmark/planner/intent-04-batch-export.md`
- approved plan: `benchmark/governor/plans/plan-b-medium.md`
- Worker role: `benchmark/worker/ROLE_PROMPT.md`

The fixture is a disposable implementation of the project facts described by Intent 04.

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

## Pipeline

Intent 04 is executed as four bounded Worker assignments matching Plan B:

1. register `export-csv` parser surface;
2. implement service-backed stdout CSV formatting;
3. implement `--output` file/error behavior;
4. add CLI regression tests.

Each task uses a new DSH Worker session. Model weights may remain resident, but conversational role state is not shared between task sessions.

Every dispatch injects:

- the complete original Intent 04 text;
- the complete approved Plan B text;
- the assigned bounded task;
- Governor intent guidance;
- the previous Worker's handoff, when applicable;
- explicit Windows/current-working-directory runtime context;
- the task authority boundary.

The same disposable project workspace persists across tasks, so later Workers see the real files produced by prerequisite Workers.

## Handoff

A task must end with `Handoff note:`.

The runner extracts that note and injects it verbatim into the next dependent task. The next dispatch is saved as evidence, as is the exact prerequisite handoff.

A missing handoff fails the task and stops that candidate's pipeline.

## Scope and later-task restraint

Tasks 1–3 may modify only `inventory/cli.py`.

Task 4 may modify only `tests/test_cli.py`.

No task authorizes helper files.

The deterministic stage verifier also checks selected later-task boundaries:

- Task 1 must not perform CSV-formatting work early;
- Task 2 must not successfully perform Task 3 file-output behavior early.

Any task failure stops that candidate's dependent pipeline.

## Verification

Before model execution:

- the fixture's existing unittest suite must pass;
- the previously qualified DSH 0.1.6-alpha.2 / dsh-llm-ollama 0.1.17 patched runtime is checked fail-closed.

After every task:

- exact workspace before/after snapshots are compared;
- unauthorized changes/creations/deletions fail;
- task-specific deterministic acceptance verification runs outside the model workspace;
- the full current unittest suite runs;
- handoff presence is checked.

Task 4 additionally requires five recognizable new CLI regression scenarios matching the original intent.

## Smoke before batch

Run the Qwen3.8-only smoke first:

`benchmark/run-worker-intent04-smoke.cmd`

Only after the complete four-task pipeline and harness behavior are validated should the promoted eight-model batch run:

`benchmark/run-worker-intent04-batch.cmd`
