# Planner Qualification v1 — Frozen Inputs

Frozen for model comparison on 2026-10-01.

## Frozen files

- `benchmark/planner/ROLE_PROMPT.txt`
  - blob: `054b0083b150f3ef0f8e65934569af910e22d0d6`
- `benchmark/planner/intent-01-cli-time-filter.md`
  - blob: `5400db1d0d655e8b95cb4c618fef69e9b8d398c2`
- `benchmark/planner/intent-02-webhook-retry-policy.md`
  - blob: `77c6c0fba98c66a3e2ca5e8c7b290a90ab8a630a`

## Freeze rule

Do not edit the frozen Planner prompt or either intent while comparing model candidates. Candidate outputs may reveal model behavior, but must not be used to tune these inputs during this qualification round.

If a benchmark-breaking defect is discovered in the frozen inputs or transport, stop the round, document the defect, revise deliberately, and begin a new qualification version.

## Current baseline evidence

Qwen3.5 9B with reasoning off and 32,768 context has valid transport-qualified runs against both intents.

The final Style J trial showed useful behavior but also candidate-specific imperfections:
- Intent 02 ultimately identified the missing transient/permanent classification as `AMBIGUOUS`, but initially emitted `BLOCKED` before correcting itself.
- Intent 01 produced a bounded task list with prerequisites and acceptance conditions, while making some implementation choices that should be considered during manual review.

These are model-behavior observations, not reasons to alter the frozen inputs.
