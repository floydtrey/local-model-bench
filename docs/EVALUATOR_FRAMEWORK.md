# Benchmark Lab V2 Evaluator Framework

**Status:** BL-5B construction contract

**Schema:** `benchmark-lab-evaluator:v2`

**Implementation:** `src/localbench/v2/evaluators.py`

**Machine-readable definition schema:** `schemas/v2/evaluator-definition.schema.json`

## Purpose

BL-5B separates deterministic scoring from the runner and from benchmark-case content.

A future benchmark case names an evaluator by `evaluator_id` and `contract_version`. The runner must resolve that exact version through the evaluator registry. The registry supplies a normalized immutable evaluation context and converts the evaluator's deterministic output into existing V2 `evaluation_result` evidence.

The registry contains no planning-specific, coding-specific, or role-specific scoring logic.

## Evaluator definition identity

An `EvaluatorDefinition` declares:

- evaluator ID;
- contract version;
- exact implementation SHA-256;
- input contract;
- result contract;
- consumed evidence record types;
- whether each evidence type is required and whether multiples are permitted;
- whether human review is required;
- scoring mode (`weighted` or `unscored`).

The complete serialized definition receives `definition_sha256`.

The existing BL-2 `evaluator_identity` record is retained rather than replaced. Its logical ID is:

```text
eval-<definition_sha256>
```

The evidence payload separately retains evaluator ID/version, exact implementation SHA-256, result contract, and human-review policy. Because the evidence digest covers the logical ID, the complete evaluator definition remains bound to the evaluator identity without changing the accepted BL-2 evidence record type.

Changing the declared evidence surface, input contract, result contract, scoring mode, human-review policy, implementation digest, evaluator ID, or contract version therefore changes evaluator definition identity.

## Evidence consumption

Every evaluator must declare exactly one required, non-multiple `case_result` input.

Additional V2 evidence types may be declared as required or optional and as single or multiple. The registry rejects:

- supplemental evidence whose record type was not declared;
- missing required evidence;
- multiple records where the definition permits only one.

The implementation receives only the evidence surface accepted by that declaration.

## Case binding

The registry verifies that the supplied normalized case definition contains an exact evaluator binding matching:

```text
evaluator_id + contract_version
```

The `CaseResult.case_id` must match the benchmark case definition's `case_id`.

This means a runner cannot evaluate one case result against a different case definition or silently substitute another evaluator version.

## Hard-failure authority

Hard failures are policy, not merely score penalties.

The registry derives the allowed hard-failure rule IDs directly from the benchmark case's `hard_failure_rules` entries for the selected evaluator. They are not supplied as an expandable caller argument.

An evaluator implementation may emit only hard-failure rule IDs already declared by that case. Emitting any undeclared hard failure is rejected as a framework error.

If any declared hard failure is triggered, the evaluator verdict must be `fail`. A hard failure cannot be hidden behind a high score or a `pass` verdict.

## Deterministic checks and score

Evaluator implementations return an `EvaluationDraft` containing:

- verdict;
- deterministic checks;
- triggered hard-failure rule IDs.

Each `EvaluationCheck` contains:

- check ID;
- passed boolean;
- weight;
- earned points;
- deterministic detail string;
- optional V2 evidence references.

The framework rejects duplicate check IDs and incoherent scores where earned points exceed weight.

For `weighted` evaluators, the framework—not the evaluator implementation—calculates total score and maximum score by summing normalized checks.

For `unscored` evaluators, every check must have zero weight and zero earned points; the resulting V2 score fields are null.

This preserves diagnostic checks without pretending every evaluator produces a comparable numeric score.

## Human review

An evaluator definition may declare `requires_human_review=true`.

Such an evaluator cannot emit a final automated `pass`. It may emit `review` or a deterministic failure where appropriate. This keeps human-review requirements from disappearing during later orchestration.

## Fail-closed resolution

`EvaluatorRegistry` is keyed by exact `(evaluator_id, contract_version)`.

It rejects:

- unregistered versions;
- duplicate registrations;
- malformed case bindings;
- case/result identity mismatch;
- undeclared or missing evidence;
- undeclared hard-failure rules;
- evaluator implementations returning the wrong result type;
- hard failures paired with non-fail verdicts;
- final pass from evaluators requiring human review;
- nonzero score weights from unscored evaluators.

## Relationship to V1

The existing `src/localbench/evaluate.py` remains historical V1 behavior. It contains planning/task-set-specific logic and is not rewritten into V2 semantics.

V2 evaluators use the new registry and versioned evaluator definitions. Future evaluator implementations may reproduce useful V1 checks only when those checks are deliberately redefined under a V2 evaluator contract.

## Construction-only validation

`tests/test_v2_evaluators.py` uses synthetic sealed evidence and deterministic Python evaluator functions only.

It does not:

- call Ollama or any model provider;
- load a model;
- score a real model response;
- create the shared capability battery;
- invoke ACL;
- implement BL-6 bounded tool execution.

## BL-5B stop gate

BL-5B is accepted only when a synthetic `CaseResult` can be resolved through an exact evaluator version and produce normalized sealed `EvaluationResult` evidence while the fail-closed conditions above are covered by deterministic regression tests.

After BL-5B acceptance, the next construction step is BL-6 neutral bounded-tool harness work under `docs/BL5_FOUNDATION_PLAN.md`. The real shared model benchmark battery remains deferred until the measuring instrument construction gates are complete.
