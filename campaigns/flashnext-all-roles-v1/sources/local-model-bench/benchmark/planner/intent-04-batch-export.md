# Planner Intent 04 — batch CSV export

A Python inventory service already supports listing inventory items through an internal service layer. The project now needs a CSV export command that reuses that existing service logic.

Current project facts:
- CLI entry point: `src/inventory/cli.py`
- Inventory service: `src/inventory/service.py`
- Item model: `src/inventory/models.py`
- Existing CLI tests: `tests/test_cli.py`
- Existing service tests: `tests/test_service.py`
- The service exposes `list_items(include_inactive: bool = False) -> list[InventoryItem]`.
- `InventoryItem` fields are `sku`, `name`, `quantity`, and `active`.
- The current CLI already has a `list` subcommand.
- The CLI uses Python's standard-library `argparse`.
- The project targets Python 3.11.
- Existing CLI commands write normal results to stdout and errors to stderr.

Requested change:
Add an `export-csv` subcommand.

Required behavior:
- By default, export only active items by calling `list_items(include_inactive=False)`.
- Add an optional `--include-inactive` flag. When present, call `list_items(include_inactive=True)`.
- Add an optional `--output <path>` argument.
- If `--output` is omitted, write CSV to stdout.
- If `--output` is supplied, write the CSV to that file and do not write CSV data to stdout.
- The CSV columns, in this exact order, are: `sku,name,quantity,active`.
- Include one header row.
- Encode `active` as lowercase `true` or `false`.
- Use the standard-library `csv` module so names containing commas or quotes are escaped correctly.
- If the output file cannot be opened or written, print a clear error to stderr and exit non-zero.
- Do not duplicate inventory lookup/filtering logic in the CLI; use `list_items`.

Constraints:
- Do not add third-party dependencies.
- Do not change the existing `list` subcommand behavior.
- Do not change `InventoryItem` or the `list_items` public signature.
- Add or update CLI tests for stdout export, file export, `--include-inactive`, CSV escaping, and output-file failure.
- Existing service tests must continue to pass unchanged.
