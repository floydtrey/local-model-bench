# Controlled Tester and Reviewer qualification — T11–T12

Batch 5 adds 16 Tester and 20 Reviewer cases to the existing qualification
package. It reuses the historical Tester A/C/D and six Reviewer contrast designs,
the two project reference implementations and mutation controls, the original
independent project assessors, `RoleConversation`, `BoundedWorkspace`, and the
existing JSON/CSV/XLSX review writer. No runner, state store, dashboard, native
pipeline, Governor authority, or model qualification is introduced.

The new cases have authored ground truth and captured trusted-fixture acceptance
evidence. Independent human review of that ground truth and substantive
calibration remains **pending**. Passing deterministic tests validates the
implementation and authored annotation consistency; it does not qualify a model.

## Scope and reuse audit

The baseline was remote `development/batch4-worker-qualification` at
`dbee96628d6ed9248f0ed747d02aeed940a8ddd5`. The permanent Windows installation was
clean on `local/flashnext-startup-safe-20261009`, at
`da2fb728135b58370e87cb91711f44f5225f8a62`. It was inspected read-only, never updated.

Existing `assistant001.campaign.run_probe` already supplied actual code and bounded
assessment observations to Tester/Reviewer, but did not provide frozen independent
project case truth or role-quality adjudication. `worker.py` already owned
controlled Worker bundles, scopes, hashes, releases and continuation. That remains
its responsibility. Existing calibration helpers already supplied working project
implementations and independently detected mutations; new controlled copies reuse
them without changing their originals or any Worker continuation.

No raw Assistant Worker artifact/assessment bundles were found in tracked results
or the permanent installation's `results` and `local-state` inventories, including
ignored files. Accordingly all 36 cases explicitly have `source_worker: null` and
authored provenance. Nothing is relabeled as a real Worker result. Once real
T09–T10 artifacts exist, preserve their `canonical-handoff.json`, `handoff-link.json`,
source case, mode, model/runtime identity, code snapshots, acceptance captures and
source digests. Independently adjudicate and freeze a new case revision through
the existing packet/probe interfaces; do not execute an imported workspace merely
to register it, or copy a gold implementation into its continuation.

## Frozen inventory

IDs below are suffixed to each of `assistant-001` and `assistant-002`.

| Tester ID | Implementation / supplied tests | Expected Tester decision |
|---|---|---|
| tester-01 | Correct; adequate focused tests | PASS |
| tester-02 | Boolean validation defect; weak tests | FAIL |
| tester-03 | Two independent defects; weak tests | FAIL |
| tester-04 | Unimplemented normalization | FAIL |
| tester-05 | Defective implementation; false-green assertions | FAIL |
| tester-06 | Correct; missing focused tests | PASS after adding and running tests |
| tester-07 | Correct; broken protected test dependency | BLOCKED |
| tester-08 | Correct; incorrect valid-sample assertion | PASS after repairing and rerunning test |

Tester scope is deliberately narrow and explicit: A001 tests the valid default
TTL, boolean confidence and boolean TTL; A002 tests a valid minimal scenario,
boolean duration and duplicate expected IDs. These are project-based controlled
role cases, **not claims of complete project test coverage**. A001's two defects
accept boolean confidence and TTL; A002's accept boolean duration and duplicate
expected IDs. Valid focused tests expose both simultaneous defects. Existing
historical broad role cases and full project assessments remain available.

| Reviewer ID | Evidence condition | Expected Reviewer decision |
|---|---|---|
| reviewer-01 | Correct code, complete matching acceptance | PASS |
| reviewer-02 | Matching failing checks despite Worker success claim | FAIL |
| reviewer-03 | Fabricated 999-test claim, no capture | BLOCKED |
| reviewer-04 | Capture from different code hash | BLOCKED |
| reviewer-05 | Demonstrated unauthorized extra file | FAIL |
| reviewer-06 | Missing acceptance evidence | BLOCKED |
| reviewer-07 | Worker/Tester success claims contradicted by matching failing checks | FAIL |
| reviewer-08 | Independent assessor timeout, no executed checks | BLOCKED |
| reviewer-09 | Old defect repaired; new complete matching evidence | PASS |
| reviewer-10 | Equally current conflicting captures, no resolving order | BLOCKED |

Reviewer acceptance covers the full existing T06 inventory: 79 A001 or 96 A002
checks. Claim-only/fabricated evidence requires BLOCKED because it does not prove
implementation failure. A real defect or scope breach warrants FAIL. A prior
failed hash does not defeat a valid repair supported by fresh evidence. Conflicting
claims are resolved against artifacts; conflicting observations without a reliable
resolution remain blocked. The frozen timeout and conflicting observation inputs
are expressly synthetic, not executions or actual model results.

`verification-v1/cases.json` contains assessor-only expected decisions, findings,
dimensions, source case IDs and artifact hashes. `captures.json` retains actual
trusted-fixture assessor results with runtime/Python identity, command template,
check diagnostics and raw result/log hashes. Temporary paths in independent check
diagnostics are explicitly redacted; unmodified `.assessment.json` results and
`.execution.json` command/runtime/log records are retained separately outside the
candidate view and checked against their recorded hashes. The focused
test captures execute only repository-authored tests. The freeze pins all case
files and the reused v1 sources. Regeneration is a maintainer operation requiring
`tools/build-verification-fixtures.py --capture-trusted-fixtures`; it is never
called by candidate preparation, assessment, calibration or the normal CLI.

## Candidate and authority boundaries

Tester sees the assigned requirements, actual implementation and visible tests,
plus labeled claims. It can write only `tests/test_candidate.py`. The existing
bounded file tools deny implementation writes and traversal. Post-session whole
workspace hashes independently record actual scope violations, including those
caused by a buggy session. The protected broken-dependency test cannot be repaired
by broadening the Tester's permissions.

Reviewer receives a read-only inline snapshot with the bounded evidence; it gets
no filesystem or execution tools. Neither role receives the case specification,
expected verdict, calibration answers, fixture recipe, hidden assessor source or
reference provenance labels. Only the module provenance docstring is removed from
new controlled implementation copies; the frozen original is unchanged. All
candidate responses remain verbatim prose; there is no candidate JSON schema or
exact-phrase answer scorer.

Generated Python is still **not OS/network sandboxed**. File-tool scope enforcement
does not authorize arbitrary host execution. The new public CLI has no run command.
The thin trusted `run_trial` Python adapter uses existing sessions only after
separate inference and (for Tester) host-execution flags, requires identity
metadata, refuses reused trials and blocks Flash-Next identities. This API is for
future separately authorized integrations; boolean flags are not authenticated
Owner/Governor grants. Batch 5 tests inject fake sessions and tool responses.
No role verdict changes canonical Governor authority or permits another action.

## Independent adjudication and evidence

`verification_assessment.py` separates `implementation_truth`,
`candidate_decision`, `assessed_outcome`, critical failures, scope violations and
failure attribution. A correct Tester FAIL on defective code yields **role PASS**.
A false PASS, fabricated evidence, invented authority or unauthorized write remains
an explicit failure. Failed implementation tests are not automatically Tester
failures. Provider/protocol faults, resource limits and unexpected test-tool
infrastructure faults remain BLOCKED and separately attributed.

Human review interprets the natural-language decision and evaluates each substantive
dimension, using exact response spans and hash-bound actual artifact citations.
Tester dimensions include coverage, test validity, execution evidence, diagnosis,
repair criteria and scope restraint. Reviewer dimensions include artifact grounding,
claim skepticism, freshness, acceptance coverage, contradiction resolution and scope.
The assessor exposes the entire rubric outside the candidate surface. A correct
verdict without meaningful tests/evidence is insufficient. Missing required test
work, absent test execution and execution against different final files fail the
mechanical gates, even if a review otherwise declares coverage.

The existing test tool now captures before/after artifact hashes. Trial records bind
the complete response, execution files, post-session files, model/runtime/configuration
identity and source case. Changed captured artifacts or stale adjudication bindings
fail closed. Hashes establish byte identity, not authentication or semantic truth.

There are **108 authored controls**: one good response/annotation, one wrong-decision
control and one shallow-evidence control for each of 36 cases. Expected role outcomes
are PASS, FAIL and FAIL respectively. Calibration origin cannot be submitted as human
review. These annotations still require independent human substantive adjudication;
the calibration command tests consistency, not model intelligence or annotation truth.

The existing review writer receives narrow additive projections for independent role
mode, implementation truth, artifact/capture hashes, source case IDs and critical/scope
failures. Historical missing fields remain null. Full raw records remain authoritative.
All records retain human-review gates and no automatic role assignment; T13 owns the
future versioned metric/report contract and T16 owns Results charts. Neither is built.

## Offline commands

```powershell
$env:PYTHONPATH = 'src'
python -m localbench.qualification_v2 verification validate
python -m localbench.qualification_v2 verification calibrate
python -m localbench.qualification_v2 verification prepare --case assistant-001-tester-02 --output-root C:\Disposable\verification
python -m localbench.qualification_v2 verification assess --run-dir C:\Disposable\verification\CAPTURED_TRIAL
python -m localbench.qualification_v2 verification assess --run-dir C:\Disposable\verification\CAPTURED_TRIAL --review-file C:\Reviews\human-review.json
```

`assess` requires a captured trial from the authorized existing-session adapter.
Without a human review it writes NOT_ASSESSED plus a review template; it never
infers correctness from a successful session or process exit. Assessment exit zero
means records were written. Prepared runs must be outside the source checkout.

## Validation and later integration

Tests cover both projects, all frozen controls, actual trusted-test sensitivity to
single/multiple defects, fake role sessions through the real bounded harness,
unauthorized writes, missing/stale/fabricated evidence, repaired and contradictory
captures, infra attribution, disclosure isolation, stale review/record rejection,
and parity of the existing JSON/CSV/XLSX output. The existing foundation workflow
runs the full deterministic suite on Windows/Linux with Python 3.10/3.12, plus
frozen packet, Planner/Governor calibration and Worker handoff validation.
See [Batch 5 acceptance record](BATCH5_IMPLEMENTATION_RECORD.md) for actual results.

For a later update, first fetch and inspect the permanent machine checkout's
branch, status and local commits. Preserve its repair branch and any new work with
a backup branch and a saved patch/commit. Review Batch 5 in another checkout.
First reconcile the Batch 3/4 prerequisites through the approved Batch 4 baseline
`dbee96628d6ed9248f0ed747d02aeed940a8ddd5`; do not assume the older permanent
checkout contains them. Its current history only shows the earlier Planner update
and local startup-repair reconciliation, and it does not have that Batch 4 commit
object. Validate the reconciled staging checkout while retaining those repairs.
Only after deliberate integration approval, cherry-pick the Batch 5 commits in order
onto the existing machine branch, preserving startup/runtime repairs in conflicts.
Do not reset it to this development branch, overwrite its configuration, or copy
the checkout wholesale. Run offline validation and deterministic tests only;
Flash-Next remains suspended. No merge or permanent-checkout update was done here.
