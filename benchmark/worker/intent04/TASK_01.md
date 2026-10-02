# Intent 04 — Worker Task 1

Register the `export-csv` subcommand in `inventory/cli.py`.

Required parser surface:
- subcommand: `export-csv`
- optional flag: `--include-inactive`, default false
- optional argument: `--output <path>`

Acceptance for this task:
- the parser recognizes `export-csv`;
- `--include-inactive` parses as true when present and false otherwise;
- `--output` preserves the supplied path.

Authority for this task:
- modify `inventory/cli.py` only;
- do not implement inventory retrieval, CSV formatting, file-output behavior, error handling, or tests yet;
- those behaviors belong to later approved tasks.
