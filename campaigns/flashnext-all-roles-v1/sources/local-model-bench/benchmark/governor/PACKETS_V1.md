# Governor Qualification v1 — Fixed Review Packets

This round keeps every normal Ollama Planner candidate in contention as a Governor candidate.

The Governor sees no Planner-model identity. Each fixed packet contains:
- the original project intent;
- one selected Planner output;
- the current canonical `docs/LAW.md` from the Governor repository;
- the current canonical `docs/STATE.md` from the Governor repository;
- the current canonical `docs/GENERAL_INTENT.md` from the Governor repository;
- the benchmark fixture Project Intent.

The runner reads the canonical Governor documents from the local Governor repository at run time. It does not maintain copied governance snapshots in the benchmark repository.

## Packet A — simple

- Original intent: `benchmark/planner/intent-03-config-default.md`
- Proposed plan: `benchmark/governor/plans/plan-a-simple.md`
- Planner provenance (not injected into Governor packet): GPT-OSS 20B

## Packet B — medium

- Original intent: `benchmark/planner/intent-04-batch-export.md`
- Proposed plan: `benchmark/governor/plans/plan-b-medium.md`
- Planner provenance (not injected into Governor packet): Gemma4 12B IT Q8

## Packet C — hard

- Original intent: `benchmark/planner/intent-05-job-cancellation.md`
- Proposed plan: `benchmark/governor/plans/plan-c-hard.md`
- Planner provenance (not injected into Governor packet): Qwen3.6 35B

## Packet D — contextual storage

- Original intent: `benchmark/planner/intent-06-contextual-storage-backend.md`
- Proposed plan: `benchmark/governor/plans/plan-d-contextual-storage.md`
- Planner provenance (not injected into Governor packet): Qwen3.6 35B, reasoning on

## Qualification condition

This is an isolated review simulation. The Governor is not executing a live governed action and is not being asked to establish or modify a protected role-to-model assignment.

The unfinished Owner identity and protected role-to-model assignment entries in the frozen State snapshot are intentionally outside this benchmark condition. They must not be used as a reason to reject or leave unresolved an otherwise reviewable plan unless the proposed plan itself requires an Owner-only action or changes a protected assignment.

All other Law, State, General Intent, Project Intent, and task constraints remain applicable to the review.
