# T05–T06 implementation record

Date: 2026-10-08 (America/Chicago). Audited base:
`370e8e03422452108b6f97c66e3e2cb672a8f3d4` on
`benchmark/flashnext-all-roles-v1`.

## Delivered

- T05: two content-pinned candidate views, explicit allowlists, planning-specific
  README, removal of task-number/provenance leakage, full inline source context,
  fresh existing role sessions without filesystem or test tools, link/reparse
  checks and pre-dispatch run validation.
- T06: R01–R06 and S01–S06 outcome rubric from existing traceability metadata,
  evidence-bound human adjudication, separate execution/diagnostic/outcome states,
  free-prose imports, ten authored calibration controls and the inherited review
  writer's additive case/evidence columns.
- CLI: `python -m localbench.qualification_v2` provides `prepare`, `assess`,
  `calibrate`, and consent-gated text-only `run`.
- CI: full deterministic suite on Windows/Linux; qualification and frozen-source
  checks on both platforms with Python 3.10/3.12. No model inference in CI.

The original v1 packet trees, historical role suite/source snapshots and
`assistant001.campaign`, both project packet adapters and `OllamaSessions` are
unchanged. Regression coverage explicitly preserves the old scaffolded prompt.
The new source views are additive benchmark inputs, not a new execution system.

## Local deterministic evidence

Windows, Python 3.12:

| Check | Verified outcome |
|---|---|
| `python -m unittest discover -s tests -v` | 420 tests; OK, 2 platform skips |
| `python -m unittest discover -s tests -p "test_qualification_v2*.py" -v` | 28 tests; OK, 1 platform skip |
| `python -m localbench.assistant001 validate` | Original packet integrity verified; 6 tasks; no execution |
| `python -m localbench.assistant002 validate` | Original packet integrity verified; 6 tasks, 96 checks; no execution |
| `python -m localbench.qualification_v2 calibrate` | 10 authored record controls pass; six historical Planner IDs retained |
| CLI prepare/import-assess | Candidate-only run created; imported plan remains NOT_ASSESSED; existing JSON/CSV/XLSX package written |

Local skips: POSIX process-group behavior and unavailable Windows symbolic-link
creation. The Windows junction regression passed. Linux CI exercises symlinks
and POSIX behavior. Temporary directories were redirected to the writable
workspace; the full local suite required the process sandbox's filesystem and
subprocess restrictions to be lifted. These are deterministic engineering tests,
including fixture HTTP responses, not real inference or generated-project runs.

The first full run exposed three pre-existing failures in unchanged paths:
Windows `time.monotonic()` resolved only 15.625 ms, yielding zero duration for
short HTTP/campaign checks; elapsed measurement now uses the monotonic
high-resolution `perf_counter`. A host-evidence test still expected four records
although its fixture includes an independent second stability capture. It now
checks four execution-host copies plus that fifth capture, two identities and
identical host facts. The subsequent full run passed. The final evidence-path
normalization was rechecked in the focused suite; remote CI checks the pushed tree.

Remote CI status must be read from the checks on the implementation commit;
local results do not stand in for Windows/Linux hosted CI.

The first hosted full-suite run also exposed two existing lifecycle tests using
the machine-specific CUDA directory despite mocking the child process. Both now
reuse the existing `fake_artifacts` helper, including synthetic CUDA files. The
production dependency guards remain unchanged. This explains why the local full
suite passed while clean Windows/Linux hosts initially failed. The focused
runtime regression is rerun locally, followed by full hosted CI on the correction.

## Acceptance limits

T05 implementation is verified deterministically. T06's implementation and
authored record controls are verified, but **independent human substantive
calibration/signoff remains pending**. Authored expected judgments are not claimed
as completed human calibration. No model has been qualified or assigned a role.
No real model tests were run, no candidate project code was enabled for execution,
and no subsequent roles were dispatched. Owner benchmark-design acceptance is
retained; formal reference authorization remains T09 and the existing reference
traces remain `OWNER_REVIEW_PENDING`. All Results-tab task IDs, scope and
dependencies from the previous backlog update are preserved.

See [the workflow, evidence schema and exact commands](PLANNER_T05_T06.md).
