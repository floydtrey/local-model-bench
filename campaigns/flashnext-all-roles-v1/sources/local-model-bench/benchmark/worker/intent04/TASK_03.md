# Intent 04 — Worker Task 3

Implement `--output` file handling and output-file error behavior for `export-csv`.

Prerequisite: Task 2.

Required behavior:
- when `--output` is omitted, preserve Task 2 stdout behavior;
- when `--output <path>` is supplied, write the CSV to that file;
- successful file export writes no CSV data to stdout;
- if the output file cannot be opened or written, print a clear error to stderr and return/exit non-zero;
- preserve the existing `list` command and all prior export behavior.

Authority for this task:
- modify `inventory/cli.py` only;
- do not add or modify tests yet.
