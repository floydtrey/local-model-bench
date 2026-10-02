# Intent 04 — Worker Task 2

Implement inventory retrieval and CSV formatting for `export-csv`.

Prerequisite: Task 1.

Required behavior for this task:
- call the existing `list_items(include_inactive=...)` service;
- default to `include_inactive=False`;
- use `include_inactive=True` when `--include-inactive` is present;
- use Python's standard-library `csv` module;
- write CSV to stdout for the no-`--output` path;
- exact column order: `sku,name,quantity,active`;
- include one header row;
- encode `active` as lowercase `true` / `false`;
- correctly escape commas and quotes.

Authority for this task:
- modify `inventory/cli.py` only;
- do not implement `--output` file writing or output-file error handling yet;
- do not add or modify tests yet.
