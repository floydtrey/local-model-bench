# Intent 04 — Plan Task 4 (Tester-owned)

This task is preserved from the approved Plan B, but it is **not part of Worker qualification**.

The pipeline architecture assigns test determination, test creation when needed, and test execution/diagnosis to the Tester role. A Worker candidate must not be invalidated because it is weak at authoring regression tests.

## Tester assignment

Add the required CLI regression coverage in `tests/test_cli.py`.

Prerequisites: Worker Tasks 1–3.

Cover:
- stdout CSV export;
- file CSV export;
- `--include-inactive`;
- CSV escaping for names containing commas or quotes;
- output-file failure, including stderr and non-zero status.

Acceptance:
- all new CLI tests pass;
- all existing CLI tests continue to pass;
- existing service tests continue to pass unchanged.

Authority:
- modify `tests/test_cli.py` only;
- do not modify production code, service tests, project intent, or approved plan.

This file is retained for future Tester-role qualification. The Worker Test 02 runner must not execute or score it.
