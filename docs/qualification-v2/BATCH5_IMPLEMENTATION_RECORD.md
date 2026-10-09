# Batch 5 implementation and acceptance record

Scope: T11/T12 only, based on
`dbee96628d6ed9248f0ed747d02aeed940a8ddd5` from
`development/batch4-worker-qualification`. New development branch:
`development/batch5-tester-reviewer-qualification`.

Implemented: 16 frozen Tester and 20 frozen Reviewer cases, 108 authored
response/adjudication controls, independent human role-quality adjudication,
candidate disclosure isolation, bounded Tester writes, exact artifact/execution
bindings and narrow projections through the existing review writer.
See [case inventory, expected outcomes and operating boundaries](TESTER_REVIEWER_T11_T12.md).

## Acceptance evidence

- Baseline: Windows Python 3.12, `python -m unittest discover -s tests -v`:
  **450 tests, OK, 2 existing skips**, 107.581 seconds.
- Targeted new subsystem: `python -m unittest discover -s tests -p
  test_qualification_v2_verification.py -v`: **15 tests, OK**, including all
  108 authored controls and trusted fixture sensitivity checks.
- Full post-change Windows Python 3.12 suite: **465 tests, OK, 2 existing skips**,
  133.381 seconds. The targeted suite also passed after retaining the additional
  raw execution artifacts. Remote Windows/Linux Python 3.10/3.12 matrix results
  will be recorded after the implementation commit is tested.
- Reference/defect captures: the existing independent assessors executed the
  complete 79-check A001 and 96-check A002 inventories on correct, single-defect,
  multiple-defect and incomplete authored fixtures. Correct fixtures passed;
  defective/incomplete fixtures failed. Frozen raw result/log hashes and reported
  observations are retained in `verification-v1/` with explicit provenance.
- No inference, untrusted model-generated Python, Flash-Next launch/repair/tuning,
  native pipeline execution, permanent checkout update, or model promotion.

## Changes and preserved boundaries

New implementation files: `verification_packet.py`, `verification.py`,
`verification_assessment.py`, `verification_calibration.py`, `verification_cli.py`
under `src/localbench/qualification_v2/`; new test module
`tests/test_qualification_v2_verification.py`; maintainer freeze builder
`tools/build-verification-fixtures.py`; frozen evidence/control files under
`docs/qualification-v2/verification-v1/`; this record and the T11/T12 guide.

Modified existing files: qualification CLI dispatch, existing role test capture
(before/after hashes only), existing review writer (additive projections),
byte-preservation attributes for new frozen evidence, existing foundation CI workflow, and backlog.
No T05–T10 implementation is rewritten. No original v1 project packet, historical
role prompt, historical benchmark evidence, or machine-specific runtime is changed.

## Outstanding gates

Independent substantive human review of case truth and calibration annotations;
human adjudication of every real role trial; separately authorized inference and
generated-code execution in a disposable environment; provenance and independent
assessment of real Worker-produced cases when available. Hash binding does not
authenticate reviewer identity. No result automatically qualifies or assigns a model.
T13/T16 and capability expansion remain not started by this batch.

The permanent installation remains on its repaired machine branch at
`da2fb728135b58370e87cb91711f44f5225f8a62`. Later integration must preserve that
branch's startup/runtime repairs. Fetch and review in a separate checkout, back up
local work, then deliberately cherry-pick Batch 5 commits onto the machine branch;
never reset/overwrite the permanent checkout. Run only offline checks during that
update. The detailed safe procedure is in the T11/T12 guide.
