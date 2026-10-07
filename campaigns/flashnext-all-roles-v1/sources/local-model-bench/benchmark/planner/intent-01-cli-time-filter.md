# Planner Intent 01 — CLI time filter

A small Python command-line tool reads JSONL event records and prints a text summary.

Current project facts:
- CLI entry point: `src/log_summary/cli.py`
- Existing tests: `tests/test_cli.py`
- Each event record already contains an ISO 8601 `timestamp` field.
- The current command summarizes every valid event in the input file.
- Invalid JSONL records are currently skipped and that behavior must not change.

Requested change:
Add an optional `--since <ISO-8601 timestamp>` argument. When supplied, only events whose timestamp is equal to or later than `--since` should contribute to the summary. When omitted, behavior must remain unchanged.

Constraints:
- Do not add third-party dependencies.
- Preserve the existing output format.
- Invalid `--since` input must produce a clear CLI error and a non-zero exit status.
- Add or update tests for the new behavior.
