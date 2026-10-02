# Worker Qualification — Test 02 / Intent 04

Date: 2026-10-02

## Purpose

Test 02 uses the existing Planner Intent 04 and Governor Plan B to qualify the Worker role without requiring the Worker model to also perform the Tester role.

Canonical sources:

- original intent: `benchmark/planner/intent-04-batch-export.md`
- approved plan: `benchmark/governor/plans/plan-b-medium.md`
- Worker role: `benchmark/worker/ROLE_PROMPT.md`

The fixture is a disposable implementation of the project facts described by Intent 04.

## Role boundary

Plan B contains four plan tasks, but not every plan task belongs to the Worker role.

Plan B Task 4 is regression-test creation. Under the intended Lab pipeline, determining whether adequate tests exist, creating missing tests, running tests, diagnosing bad tests versus real implementation failures, and returning repair criteria belongs to the **Tester** role.

Worker Test 02 therefore scores only implementation Tasks 1–3:

1. register the `export-csv` parser surface;
2. implement service-backed stdout CSV formatting;
3. implement `--output` file/error behavior.

The full approved plan, including the later Tester-owned task, remains visible to every Worker as context. It is not authority to perform that task early.

The original Qwen3.8 smoke that executed Plan B Task 4 under the Worker role is role-mismatched evidence. Qwen3.8 passed Worker Tasks 1–3 in that run; the later test-authoring failure must not invalidate its Worker qualification.

## Deterministic assessor

Until a Tester model is separately qualified, Worker qualification uses a benchmark-owned deterministic assessor.

After each Worker attempt the assessor independently evaluates:

- exact workspace scope;
- task-specific acceptance behavior;
- pre-existing regression tests;
- required handoff;
- runtime completion.

The assessor code is outside the disposable Worker workspace. The Worker does not author or edit the assessor.

The assessor emits stable check IDs. Public repair criteria are mapped to those IDs in:

`benchmark/worker/intent04/ASSESSOR_CRITERIA.json`

Repair feedback contains:

- the failed acceptance criterion;
- observed externally visible behavior;
- the required repair criterion;
- concrete scope violations when present;
- existing regression-test failure evidence when present.

The repair packet does **not** expose hidden verifier implementation code or hand the Worker an implementation.

## One repair attempt

A normal completed Worker turn that fails deterministic assessment receives exactly one repair attempt.

The repair is sent back into the **same Worker DSH session** because it is continuation of the same assigned task.

Scoring preserves both outcomes:

- first-pass correctness;
- whether a repair was attempted;
- repair success/failure;
- final task state;
- terminal condition.

A task repaired successfully is not equivalent to a first-pass success.

Runtime/interface failures and Worker timeouts do not receive code-repair feedback. They are recorded separately.

## Qualification continuity after a failed task

One early task failure must not prevent measuring the candidate on every later Worker task.

Before each task, the runner preserves a private baseline copy of the workspace.

If a task still fails after its allowed repair, or terminates through a runtime/interface failure:

1. the task remains scored FAIL;
2. the candidate's failed workspace is preserved in evidence;
3. for the **next qualification task only**, the harness restores the pre-task baseline and overlays the benchmark's verified gold checkpoint for the failed prerequisite;
4. the gold checkpoint is independently re-verified;
5. a canonical qualification-recovery handoff is injected into the next fresh Worker session.

Gold checkpoints are under:

- `benchmark/worker/intent04/gold/task-01/`
- `benchmark/worker/intent04/gold/task-02/`
- `benchmark/worker/intent04/gold/task-03/`

This recovery exists only so later tasks remain measurable. It never converts the failed prerequisite into a model PASS.

A real integrated pipeline test will not use gold recovery; failures will propagate naturally there.

## Worker session and handoff behavior

Each implementation task uses a fresh Worker DSH session.

Every dispatch injects:

- the complete original Intent 04;
- the complete approved Plan B;
- the assigned bounded task;
- Governor intent guidance;
- prerequisite handoff;
- explicit Windows/current-working-directory runtime context;
- the task authority boundary.

If the prerequisite Worker passed, its accepted handoff is injected verbatim.

If qualification recovery was required, the next task receives an explicit canonical recovery handoff describing the gold state rather than pretending the failed Worker succeeded.

## Scope

Worker Tasks 1–3 may modify only:

`inventory/cli.py`

No helper files are authorized.

The deterministic assessor also checks later-task restraint:

- Task 1 must not perform Task 2 CSV implementation early;
- Task 2 must not successfully perform Task 3 file-output behavior early.

## Promotion from Test 01

The default Test 02 roster contains the clean Test 01 passers:

- qwen3.8 27B
- qwen3.6 35B
- qwen3-coder 30B
- Gemma4 12B
- qwen3.6 27B
- Nemotron 3.5 Lightning 30B
- North Mini Code
- Muse Glimmer

Qwen3.5, GPT-OSS, Granite, and Laguna XS remain documented Test 01 failures/conditional results and are not in the default promotion roster.

## Evidence

Per task, the runner records:

- role turn;
- first Worker attempt;
- deterministic verifier result with check IDs;
- existing regression-suite result;
- first-pass workspace diff;
- generated repair packet, when applicable;
- repair turn and second assessment, when applicable;
- accepted handoff;
- qualification-recovery evidence, when applicable.

The batch summary separates first-pass and repaired performance.

## Validate assessor, then smoke

Before spending a model call, validate the fixture, assessor criteria, deterministic verifier, and all three gold checkpoints:

`benchmark/validate-worker-intent04-assessor.cmd`

Then run the Qwen3.8-only smoke:

`benchmark/run-worker-intent04-smoke.cmd`

Only after the deterministic assessor, repair loop, and gold recovery behavior are validated should the promoted batch run:

`benchmark/run-worker-intent04-batch.cmd`

## Tester qualification

Tester selection is intentionally separate. See:

`benchmark/tester/QUALIFICATION_PLAN.md`

The later integrated benchmark should combine qualified Worker and Tester candidates only after each role has been measured independently.
