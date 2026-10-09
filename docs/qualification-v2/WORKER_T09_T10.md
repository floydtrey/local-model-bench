# Canonical Worker qualification — T09–T10

> **2026-10-09 technical audit supersedes the earlier review-pending checkpoint below.** Both bundles/all 12 task slots have now received delegated AI technical review. Real isolated seeds remain BLOCKED; fake-assessor unit fixtures are not validated prerequisites. Cumulative preparation starts at T01, and authorization placement is checked before provider construction. This is AI technical approval, not independent human certification, model qualification or Owner execution authorization. See the [audit report](technical-audit-20261009/AUDIT_REPORT.md) and [complete decisions](technical-audit-20261009/CASE_CONTROL_DECISIONS.md).

Batch 4 extends the existing `localbench.qualification_v2` CLI, original project
materializers, `assistant001.campaign.run_worker_chain`, independent acceptance
assessor, `OllamaSessions`/fresh `RoleConversation`, and `flashnext_review` writer.
No controller, state store, service, runtime repair or frozen v1 change is added.
The original historical commands and chain retain their original behavior.

## Canonical reference and authorization

Each project's `qualification-v2/WORKER_HANDOFF_V1.json` binds all six task scopes,
assigned task text, acceptance requirements, full reference plan, project intent,
contract, Governor restrictions and source hashes. Source changes fail closed.
The Governor restrictions come from the frozen authored bounded offline case;
the simulation assumptions and authored origin remain explicit. No candidate
Governor output is accepted as canonical input or actual authority.

The user authorized implementation of this batch. This provenance grants no
inference, generated-code execution, exceptional permission, deployment or role
assignment. Bundles remain `HUMAN_REVIEW_PENDING`; the earlier benchmark-design
acceptance is preserved without claiming formal artifact or execution signoff.
T06/T07/T08 substantive review/calibration is still pending.

For a future separately authorized trial, a trusted operator selects a **private**
authorization file and its exact SHA-256 at the CLI. This is explicit adoption by
the operator; hashes establish byte identity, **not authentication of a person or
the canonical Owner**. Candidate-provided files/digests must never be adopted.
The record must have these fields:

```json
{
  "schema_version": "qualification-v2/worker-authorization-v1",
  "origin": "trusted_operator",
  "provenance_reference": "trusted owner/operator approval evidence reference",
  "input_sha256": "exact worker-input.json input_sha256",
  "bundle_sha256": "exact worker-input.json bundle_sha256",
  "reference_review": "approved",
  "allow_model_inference": true,
  "allow_host_execution": true,
  "exceptions": [],
  "seed_validation_sha256": "sha256_json of the embedded seed record; isolated only",
  "target_unsolved_review": "approved"
}
```

Use the existing `localbench.v2.contracts.sha256_json` for canonical JSON digests
and `Get-FileHash -Algorithm SHA256` for the authorization file's raw byte digest.
Keep authorization material outside candidate workspaces. No approved real
release record is shipped. `run` requires both separate consent flags and this
record **before** constructing the provider. Flash-Next is additionally blocked
by name in this CLI while suspended; its machine runtime is untouched.

## Worker modes and prerequisites

`CUMULATIVE_PROJECT` uses the original raw starter. Each accepted task continues
in that candidate's own workspace with its actual previous prose and code hashes.
The original runner blocks successors after any failure. Seeds are prohibited in
this mode. Different candidates' later workspaces are intentionally not equal.

`ISOLATED_TASK` copies a common independently prevalidated prerequisite workspace
once before the assigned task, then uses a one-task packet view of the same
runner. The seed, canonical bundle, mode, assigned task and workspace hashes are
the comparison identity; model names, disposable run paths and timestamps are
excluded. The original seed is never mutated or used to repair a failed trial.
Every trial needs a fresh materialization and role conversation.

Seeds are operator-reviewed external prerequisite fixtures, **not** a full
reference installed after a model failure. Use an original prepared project run
containing only accepted prerequisites; leave the target and later requirements
unsolved. The separately gated `validate-seed` command uses the existing assessor
on the immediate predecessor (whose checks cover all earlier requirements), then
the target. It requires predecessor acceptance, a completed failing target check
inventory and an unchanged workspace. T01 has no predecessor. Infrastructure
errors, missing check results and passing target solutions cannot prevalidate a
seed. Validation records remain immutable and pending human review.

A failing target test cannot prove absence of target solutions. The operator must
inspect the fixture, test observations and provenance, attest to its unsolved
target, and bind the exact validation record in the private authorization. No
real seed validation or substantive seed approval occurred in Batch 4; all
deterministic test seeds and grants are explicitly fake test controls. The
implementation supports both projects and all twelve task slots, but release of
real isolated comparisons remains gated on those reviews and separate execution
authorization. It never executes seed code during prepare or metadata validation.

Read-only and preparation commands (no inference/execution):

```powershell
$env:PYTHONPATH = 'src'
python -m localbench.qualification_v2 worker validate --project assistant-001
python -m localbench.qualification_v2 worker validate --project assistant-002
python -m localbench.qualification_v2 worker prepare --project assistant-001 --mode CUMULATIVE_PROJECT --output-root C:\Disposable\worker-trials
python -m localbench.qualification_v2 worker prepare --project assistant-001 --mode ISOLATED_TASK --task T03 --seed-run C:\ReviewedSeeds\a001-t03 --output-root C:\Disposable\worker-trials
```

The last command requires an already prevalidated seed. After **separate**
generated-code execution authorization, `worker validate-seed --project ...
--task ... --seed-run ... --allow-host-execution` captures prerequisite evidence.
After **separate** inference and generated-code authorization and human release,
`worker run --project ... --run-dir ... --model ... --authorization-file ...
--trusted-authorization-sha256 ... --allow-model-inference
--allow-host-execution` uses the existing runner. Do not invoke either execution
command under this implementation request. Use a disposable environment: file
tool scope is not OS/network isolation.

## Evidence and failure attribution

Per-task `canonical-handoffs/T0x/canonical-handoff.json` records actual starting
hashes, assigned task, previous handoff origin and operator release reference.
Original role evidence, acceptance records and `handoff-link.json` are retained.
`summary.json` distinguishes controlled track, Worker mode, seed/bundle/input
hashes, scope failures, Worker failures, infrastructure problems and blocked
predecessors. Infrastructure and predecessor blocks have unknown assessment
outcomes and no scored deterministic denominator. Independent acceptance is
provisional until human review; no qualification or promotion is automatic.

The existing JSON/CSV/XLSX writer receives additive mode, bundle/seed/authorization
hash and failure-attribution columns. Historical missing fields stay null.
T13 still owns the broader comparison/metric catalog; this batch does not claim
model/configuration comparability from a model tag alone.

## Validation and updating the permanent checkout

Deterministic tests cover twelve isolated input slots, independent copies, scope
enforcement before assessment, model/synthetic provenance rejection, stale seeds,
failed prerequisites, unsolved-target signoff, infrastructure attribution,
cumulative candidate continuation, failure retention and shared writer parity.
Tests inject fake sessions/assessors and never execute generated candidate Python.
The foundation workflow runs Windows/Linux on Python 3.10/3.12, frozen guards,
calibration-record checks and handoff validation.

The latest remote baseline for this batch was `1d52238` on
`benchmark/flashnext-all-roles-v1`. Work is published separately on
`development/batch4-worker-qualification`. The permanent machine branch and its
repaired Flash-Next runtime have not been edited or launched.

Safest update: fetch, inspect local changes and compare commits without changing
the permanent checkout. Create another checkout of the development branch for
review. When deliberately updating the permanent checkout, save its local changes,
review each Batch 4 commit and cherry-pick those commits in order onto the existing
machine branch. Do not reset, replace its branch, or copy machine configuration.
Resolve conflicts by preserving repaired runtime/configuration; inspect the diff
before continuing. Run only metadata validation/deterministic tests. Do not start
Flash-Next or execute candidate code as part of updating the checkout.
