# Intent 04 — Worker Task 4

Add the required CLI regression coverage in `tests/test_cli.py`.

Prerequisites: Tasks 1–3.

Add tests covering:
- stdout CSV export;
- file CSV export;
- `--include-inactive`;
- CSV escaping for names containing commas or quotes;
- output-file failure, including stderr and non-zero status.

Acceptance:
- all new CLI tests pass;
- all existing CLI tests continue to pass;
- existing service tests continue to pass unchanged.

Authority for this task:
- modify `tests/test_cli.py` only;
- do not modify production code, service tests, project intent, or approved plan.
