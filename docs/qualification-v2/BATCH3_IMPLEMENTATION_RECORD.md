# T07–T08 implementation evidence

Date: 2026-10-09. Starting branch revision:
`dd04a8883ea18fc49f135320b65a7f4551f98c7d`.

## Scope and provenance

The existing T01/T02 contracts, reference plans, separate Planner implementation,
historical Governor loader, role harness and evidence writer were inspected.
The batch adds only the controlled Governor packet/assessment adapter and its
fixtures, tests and writer columns. It creates no runtime backend or downstream
execution path. See [implementation and review limits](GOVERNOR_T07_T08.md).

Canonical Governor source inspected:
`234b482916463c08875120ca22ce1c7e84e4e33c`. Exact private local document hashes
were verified against `git show` bytes at that revision. The public metadata
contains hashes and references only. Private canonical content and assembled
prompts remain outside the public checkout.

- Case freeze SHA-256:
  `5ec7f5d7b041a075671c0f18a49da87baa3341686082f497bd9a8c20001c96ad`.
- Calibration manifest SHA-256:
  `2fec21c02810dbebda5bfa795dae76b0aa1b85cf9ffe73061c83415eb836babf`.
- 28 project-specific cases: 14 per project, each with exact plan, synthetic
  conditions, expected decision, rationale, material restrictions and pending review.
- 16 authored calibration controls. Correctly justified approval/denial/escalation
  are distinguishable from unsafe approval, blanket denial, false escalation and
  omitted material approval conditions.
- All calibration prompt bindings were recomputed against the actual private
  canonical bytes without saving those prompts in this repository.

## Deterministic verification

Local Windows / Python 3.12:

| Check | Evidence |
|---|---|
| Full deterministic suite before final evidence/path hardening | 436 tests, PASS, 2 platform skips |
| Final qualification suite, including final hardening | 45 tests, PASS, 1 platform skip |
| Governor coverage within final qualification suite | 17 tests, PASS |
| Frozen calibration records | 16 controls, PASS for integrity/annotation consistency only |
| Actual-private-source preparation, verification and imported-prose report smoke | PASS; outcome NOT_ASSESSED; no inference |
| T05/T06 files and calibration, v1 packets and historical suite | No changes; existing frozen-source guards pass |

The Windows symlink privilege skip is covered by an actual junction regression.
The full-suite POSIX process-group test is platform-specific. Local test temp
files were placed in a writable directory outside the public checkout. The
sandbox could not create Windows junctions; the deterministic test run used
normal host permissions for those temporary test paths. This did not enable
model inference or generated candidate execution.

The final tests cover all case packet identities, canonical/source drift,
rehashed-manifest rejection, private Git-tree placement and descendant junction
redirection, prompt/metadata/workspace injection, actual role-engine tool denial,
session freshness, consent gating, failed transport evidence, semantic review
bindings and missing/ambiguous outputs, critical unsafe approvals, inherited
CSV/JSON/XLSX output, import exclusion, sealed runtime/configuration verification,
summary tampering, duplicate trial exclusion, symmetric comparison and different
thinking-mode separation. Exact canonical private documents are not needed in CI.

The existing CI workflows cover:

- Qualification foundation: Windows/Linux × Python 3.10/3.12, now including the
  Governor calibration command.
- Full deterministic suite: Windows/Linux × Python 3.12.
- Assistant-001 and Assistant-002 regressions: each Windows/Linux × Python 3.10/3.12.
- GUI and launchers: Windows / Python 3.12 / real Tkinter with fake benchmarks.

Push-triggered workflows and the remaining workflow-dispatch runs are to be
verified on the implementation commit. Their exact run URLs and final conclusions
belong to the completion report; the local results above do not imply remote CI
success before those runs finish.

## Honest remaining limits

**Independent substantive scenario review and human calibration/signoff are
pending.** An authored oracle, a self-review or a structurally valid annotation
is not independent human approval. The requested reviewed reference milestone
cannot honestly be labeled complete until that separate review occurs.
All frozen records and reports retain this pending status; T07/T08 progress is
IMPLEMENTED, not acceptance-complete. Model qualification is not complete.

No real inference, generated candidate Python, actual Owner authentication,
protected role assignment, Worker launch, production transfer, deployment,
native DSH qualification or T09 release was performed or granted. Model prose
does not become authority. T05/T06 calibration fixtures are left for their
separate review chat.
