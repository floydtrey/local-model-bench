# Worker Qualification — Test 02 / Intent 04

Date: 2026-10-02

## Purpose

Test 02 qualifies the Worker role against the existing Planner Intent 04 and Governor Plan B without requiring the Worker model to also act as Tester.

Canonical inputs:

- original intent: `benchmark/planner/intent-04-batch-export.md`
- approved plan: `benchmark/governor/plans/plan-b-medium.md`
- Worker role: `benchmark/worker/ROLE_PROMPT.md`

Plan B Task 4 is test authoring and belongs to the future Tester role. Worker qualification executes only implementation Tasks 1–3.

## Exact qualification loop

For each Worker task:

1. start a fresh Worker DSH session;
2. inject the original intent, full approved plan, assigned bounded task, prerequisite handoff, runtime context, and authority boundary;
3. let that Worker complete the assigned task;
4. keep the Ollama model resident;
5. run the benchmark-owned deterministic acceptance checks;
6. run the fixture's existing regression suite;
7. inspect deterministic scope and handoff checks;
8. if everything passes, accept that Worker's handoff;
9. send the next task to a fresh Worker session with the accepted handoff;
10. if a deterministic check fails, map each failed check ID to a prewritten repair response and send one repair turn back to the **same Worker session**;
11. rerun the same deterministic checks after the repair;
12. if the repaired task still fails, stop that candidate's scenario.

There is no model-generated testing in Worker qualification.

There is no gold-state replacement or artificial continuation after a failed task.

## Model residency and session behavior

The candidate model remains loaded in Ollama while deterministic tests run between Worker turns. The runner does not unload the model between:

- the Worker implementation turn;
- deterministic test execution;
- a repair turn.

A repair resumes the same DSH Worker session because it is still the same task.

A passed task ends that Worker session's responsibility. The next task gets a fresh DSH Worker session, while the same model may remain resident in Ollama.

The outer batch runner unloads the model only after that candidate's entire Intent 04 scenario has completed or failed.

No additional context-cap management is implemented. If real runs show that context limits become a problem, evaluate that evidence before adding machinery.

## Deterministic checks

The hidden acceptance script is:

`benchmark/worker/intent04/verify_stage.py`

It is outside the disposable Worker workspace.

The script emits stable failed-check IDs. Repair wording is preselected in:

`benchmark/worker/intent04/ASSESSOR_CRITERIA.json`

The runner does not ask another model to interpret the failure.

A repair packet contains:

- the deterministic failed check ID;
- the observed failure evidence;
- the prewritten repair criterion;
- the task's unchanged authority boundary.

The Worker never receives the hidden acceptance-test implementation.

## Existing tests

The fixture's pre-existing tests run after every Worker pass in addition to the hidden acceptance checks.

A regression failure maps to a fixed repair response instructing the Worker to restore existing behavior without modifying tests.

Worker Tasks 1–3 authorize changes only to:

`inventory/cli.py`

The Worker may run existing tests for self-check, but it may not create, modify, or delete tests.

## Handoffs

A task is not accepted until:

- deterministic acceptance checks pass;
- existing regressions pass;
- scope checks pass;
- the Worker final response contains `Handoff note:`.

If the first Worker pass fails and the repair succeeds, the **repair turn's handoff** is the accepted handoff passed to the next fresh Worker.

If the task still fails after the repair, the scenario stops.

## Scoring

Record separately:

- first-pass task result;
- whether a repair was needed;
- repair result;
- final task result;
- runtime/interface terminal condition.

A repaired PASS remains distinguishable from a first-pass PASS.

## Smoke before batch

Run the Qwen3.8-only smoke first:

`benchmark/run-worker-intent04-smoke.cmd`

Only after that complete three-task flow behaves correctly should the promoted multi-model batch run:

`benchmark/run-worker-intent04-batch.cmd`

## Tester role

Tester qualification remains a separate later phase. The future Tester model will eventually replace the benchmark-owned deterministic-test / fixed-repair layer with dynamic test selection, missing-test creation, bad-test diagnosis, and repair-criteria generation.

Until then, Worker qualification uses only the deterministic layer described above.
