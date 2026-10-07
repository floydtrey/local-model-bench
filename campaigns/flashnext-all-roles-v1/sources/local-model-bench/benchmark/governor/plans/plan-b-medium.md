### Task List

**Task 1: Register `export-csv` subcommand in `src/inventory/cli.py`**
- **Prerequisites:** None.
- **Description:** Add an `export-csv` subcommand to the existing CLI using `argparse`. The subcommand must include:
    - An optional flag `--include-inactive` (defaulting to `False`).
    - An optional argument `--output <path>`.
- **Acceptance Condition:** The CLI recognizes `export-csv` as a valid command and successfully parses the `--include-inactive` flag and `--output` argument without error.

**Task 2: Implement data retrieval and CSV formatting for `export-csv`**
- **Prerequisites:** Task 1.
- **Description:** Implement the logic for the `export-csv` subcommand:
    - Call `list_items(include_inactive=...)` from `src/inventory/service.py` using the value provided by the `--include-inactive` flag.
    - Format the resulting `InventoryItem` objects into CSV format using the standard-library `csv` module.
    - Ensure the CSV includes a header row and the columns are in the exact order: `sku,name,quantity,active`.
    - Encode the `active` field as a lowercase string: `true` or `false`.
    - Ensure the output is prepared for either stdout or a file.
- **Acceptance Condition:** Calling `export-csv` without an `--output` argument produces a CSV-formatted string to stdout containing the correct headers, column order, and lowercase boolean values for the `active` column.

**Task 3: Implement output handling and error logic for `export-csv`**
- **Prerequisites:** Task 2.
- **Description:** Finalize the output logic for the `export-csv` subcommand:
    - If `--output` is omitted, write the CSV data to `stdout`.
    - If `--output` is provided, write the CSV data to the specified file path and ensure no CSV data is written to `stdout`.
    - Wrap the file writing operation in a try/except block. If the file cannot be opened or written, print a clear error message to `stderr` and exit the program with a non-zero status code.
- **Acceptance Condition:**
    - Providing a valid path to `--output` successfully creates a file with the correct CSV content and produces no output on `stdout`.
    - Providing an invalid or inaccessible path to `--output` prints an error message to `stderr` and exits with a non-zero status code.

**Task 4: Add tests for `export-csv` subcommand**
- **Prerequisites:** Task 1, Task 2, Task 3.
- **Description:** Update `tests/test_cli.py` to include tests for the following scenarios:
    - Successful export to `stdout` (default behavior).
    - Successful export to a file using `--output`.
    - Filtering behavior when using the `--include-inactive` flag.
    - Correct CSV escaping for items containing commas or quotes in the `name` field.
    - Error handling when the `--output` path is invalid (verifying `stderr` output and non-zero exit).
- **Acceptance Condition:** All new tests in `tests/test_cli.py` pass, and all existing tests in `tests/test_cli.py` and `tests/test_service.py` continue to pass.
