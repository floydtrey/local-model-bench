from __future__ import annotations

import argparse
import ast
import contextlib
import csv
import io
import json
import pathlib
import sys
import tempfile
from unittest.mock import patch


def invoke(cli, argv: list[str]) -> tuple[int | None, str, str, BaseException | None]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    error: BaseException | None = None
    code: int | None = None

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            result = cli.main(argv)
            code = 0 if result is None else int(result)
        except SystemExit as exc:
            if exc.code is None:
                code = 0
            elif isinstance(exc.code, int):
                code = exc.code
            else:
                print(str(exc.code), file=sys.stderr)
                code = 1
        except BaseException as exc:
            error = exc

    return code, stdout.getvalue(), stderr.getvalue(), error


def fake_items(include_inactive: bool = False):
    from inventory.models import InventoryItem

    active = InventoryItem("A-100", 'Widget, "Deluxe"', 4, True)
    inactive = InventoryItem("B-200", "Spare Part", 2, False)
    return [active, inactive] if include_inactive else [active]


def csv_rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def imports_csv_module(source: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "csv" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module == "csv":
            return True
    return False


def parser_surface(cli) -> None:
    parser = cli.build_parser()

    default = parser.parse_args(["export-csv"])
    assert default.command == "export-csv", "export-csv command was not selected"
    assert default.include_inactive is False, "--include-inactive must default false"
    assert default.output is None, "--output must default to None"

    configured = parser.parse_args(
        ["export-csv", "--include-inactive", "--output", "items.csv"]
    )
    assert configured.command == "export-csv"
    assert configured.include_inactive is True, "--include-inactive did not parse true"
    assert configured.output == "items.csv", "--output path was not preserved"


def existing_list_behavior(cli) -> None:
    code, stdout, stderr, error = invoke(cli, ["list"])
    assert error is None, repr(error)
    assert code == 0, f"list returned {code!r}"
    assert stderr == "", f"list wrote stderr: {stderr!r}"
    assert stdout == "A-100\tWidget\t4\ttrue\nC-300\tCable\t7\ttrue\n", (
        f"list output changed: {stdout!r}"
    )


def stdout_export(cli, include_inactive: bool) -> tuple[list[bool], str, str, int | None]:
    calls: list[bool] = []

    def side_effect(include_inactive: bool = False):
        calls.append(include_inactive)
        return fake_items(include_inactive)

    argv = ["export-csv"]
    if include_inactive:
        argv.append("--include-inactive")

    with patch("inventory.cli.list_items", side_effect=side_effect):
        code, stdout, stderr, error = invoke(cli, argv)

    assert error is None, repr(error)
    return calls, stdout, stderr, code


def check_default_filter(cli) -> None:
    calls, stdout, stderr, code = stdout_export(cli, False)
    assert calls == [False], f"list_items calls were {calls!r}"
    assert code == 0, f"export returned {code!r}"
    assert stderr == "", f"export wrote stderr: {stderr!r}"
    assert stdout, "export produced no stdout CSV"


def check_inactive_filter(cli) -> None:
    calls, _, stderr, code = stdout_export(cli, True)
    assert calls == [True], f"list_items calls were {calls!r}"
    assert code == 0, f"export returned {code!r}"
    assert stderr == "", f"export wrote stderr: {stderr!r}"


def check_csv_schema_stdout(cli) -> None:
    _, stdout, stderr, code = stdout_export(cli, True)
    assert code == 0, f"export returned {code!r}"
    assert stderr == "", f"export wrote stderr: {stderr!r}"
    assert csv_rows(stdout) == [
        ["sku", "name", "quantity", "active"],
        ["A-100", 'Widget, "Deluxe"', "4", "true"],
        ["B-200", "Spare Part", "2", "false"],
    ], f"unexpected CSV rows: {csv_rows(stdout)!r}"


def check_stdout_default(cli) -> None:
    _, stdout, stderr, code = stdout_export(cli, False)
    assert code == 0, f"export returned {code!r}"
    assert stderr == "", f"export wrote stderr: {stderr!r}"
    assert csv_rows(stdout) == [
        ["sku", "name", "quantity", "active"],
        ["A-100", 'Widget, "Deluxe"', "4", "true"],
    ], f"unexpected stdout CSV: {csv_rows(stdout)!r}"


def check_no_early_csv() -> None:
    source = pathlib.Path("inventory/cli.py").read_text(encoding="utf-8")
    assert not imports_csv_module(source), "standard-library csv imported during Task 1"


def check_no_early_export_behavior(cli) -> None:
    calls: list[bool] = []

    def side_effect(include_inactive: bool = False):
        calls.append(include_inactive)
        return fake_items(include_inactive)

    with patch("inventory.cli.list_items", side_effect=side_effect):
        invoke(cli, ["export-csv"])

    assert calls == [], f"Task 1 performed inventory retrieval early: {calls!r}"


def check_uses_csv() -> None:
    source = pathlib.Path("inventory/cli.py").read_text(encoding="utf-8")
    assert imports_csv_module(source), "standard-library csv module is not used"


def check_no_early_file_output(cli) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = pathlib.Path(tmp) / "too-early.csv"
        with patch("inventory.cli.list_items", side_effect=fake_items):
            invoke(cli, ["export-csv", "--output", str(output)])
        assert not output.exists(), "Task 2 successfully created the --output file"


def file_export(cli) -> tuple[int | None, str, str, BaseException | None, list[list[str]]]:
    with tempfile.TemporaryDirectory() as tmp:
        output = pathlib.Path(tmp) / "inventory.csv"
        with patch("inventory.cli.list_items", side_effect=fake_items):
            code, stdout, stderr, error = invoke(
                cli, ["export-csv", "--include-inactive", "--output", str(output)]
            )

        rows = []
        if output.is_file():
            rows = csv_rows(output.read_text(encoding="utf-8"))
        return code, stdout, stderr, error, rows


def check_file_output(cli) -> None:
    code, _, stderr, error, rows = file_export(cli)
    assert error is None, repr(error)
    assert code == 0, f"file export returned {code!r}"
    assert stderr == "", f"file export wrote stderr: {stderr!r}"
    assert rows, "requested output file was not created with CSV content"


def check_no_stdout_on_file(cli) -> None:
    code, stdout, stderr, error, _ = file_export(cli)
    assert error is None, repr(error)
    assert code == 0, f"file export returned {code!r}"
    assert stderr == "", f"file export wrote stderr: {stderr!r}"
    assert stdout == "", f"file export leaked stdout CSV: {stdout!r}"


def check_csv_schema_file(cli) -> None:
    code, _, stderr, error, rows = file_export(cli)
    assert error is None, repr(error)
    assert code == 0, f"file export returned {code!r}"
    assert stderr == "", f"file export wrote stderr: {stderr!r}"
    assert rows == [
        ["sku", "name", "quantity", "active"],
        ["A-100", 'Widget, "Deluxe"', "4", "true"],
        ["B-200", "Spare Part", "2", "false"],
    ], f"unexpected file CSV rows: {rows!r}"


def check_file_error(cli) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = pathlib.Path(tmp) / "missing-parent" / "inventory.csv"
        with patch("inventory.cli.list_items", side_effect=fake_items):
            code, stdout, stderr, error = invoke(
                cli, ["export-csv", "--output", str(output)]
            )

        assert error is None, f"file error escaped the CLI: {error!r}"
        assert code is not None and code != 0, f"file error returned {code!r}"
        assert stdout == "", f"file error wrote CSV to stdout: {stdout!r}"
        assert stderr.strip(), "file error produced no stderr message"
        assert not output.exists(), "failed output path unexpectedly exists"


def check_filtering_preserved(cli) -> None:
    calls: list[bool] = []

    def side_effect(include_inactive: bool = False):
        calls.append(include_inactive)
        return fake_items(include_inactive)

    with patch("inventory.cli.list_items", side_effect=side_effect):
        code1, _, _, error1 = invoke(cli, ["export-csv"])
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "inventory.csv"
            code2, _, _, error2 = invoke(
                cli, ["export-csv", "--include-inactive", "--output", str(output)]
            )

    assert error1 is None and error2 is None, f"errors: {error1!r}, {error2!r}"
    assert code1 == 0 and code2 == 0, f"codes: {code1!r}, {code2!r}"
    assert calls == [False, True], f"list_items calls were {calls!r}"


def run_check(failures: list[dict[str, str]], check_id: str, fn) -> None:
    try:
        fn()
    except BaseException as exc:
        message = str(exc).strip()
        if not message:
            message = repr(exc)
        failures.append(
            {
                "check_id": check_id,
                "observed": f"{type(exc).__name__}: {message}",
            }
        )


def load_cli(failures: list[dict[str, str]]):
    try:
        from inventory import cli

        return cli
    except BaseException as exc:
        message = str(exc).strip() or repr(exc)
        failures.append(
            {
                "check_id": "I04-IMPORT",
                "observed": f"{type(exc).__name__}: {message}",
            }
        )
        return None


def verify(stage: int) -> dict:
    failures: list[dict[str, str]] = []
    cli = load_cli(failures)
    if cli is None:
        return {"stage": stage, "passed": False, "failures": failures}

    if stage == 1:
        run_check(failures, "I04-T1-PARSER-SURFACE", lambda: parser_surface(cli))
        run_check(failures, "I04-T1-LIST-REGRESSION", lambda: existing_list_behavior(cli))
        run_check(failures, "I04-T1-NO-EARLY-CSV", check_no_early_csv)
        run_check(
            failures,
            "I04-T1-NO-EARLY-EXPORT",
            lambda: check_no_early_export_behavior(cli),
        )

    elif stage == 2:
        run_check(failures, "I04-T2-PARSER-SURFACE", lambda: parser_surface(cli))
        run_check(failures, "I04-T2-DEFAULT-FILTER", lambda: check_default_filter(cli))
        run_check(failures, "I04-T2-INACTIVE-FILTER", lambda: check_inactive_filter(cli))
        run_check(failures, "I04-T2-CSV-SCHEMA", lambda: check_csv_schema_stdout(cli))
        run_check(failures, "I04-T2-STDOUT", lambda: check_stdout_default(cli))
        run_check(failures, "I04-T2-USES-CSV-MODULE", check_uses_csv)
        run_check(
            failures,
            "I04-T2-NO-EARLY-FILE-OUTPUT",
            lambda: check_no_early_file_output(cli),
        )
        run_check(failures, "I04-T2-LIST-REGRESSION", lambda: existing_list_behavior(cli))

    elif stage == 3:
        run_check(failures, "I04-T3-PARSER-SURFACE", lambda: parser_surface(cli))
        run_check(failures, "I04-T3-STDOUT-PRESERVED", lambda: check_stdout_default(cli))
        run_check(failures, "I04-T3-FILE-OUTPUT", lambda: check_file_output(cli))
        run_check(
            failures,
            "I04-T3-NO-STDOUT-ON-FILE",
            lambda: check_no_stdout_on_file(cli),
        )
        run_check(failures, "I04-T3-FILE-ERROR", lambda: check_file_error(cli))
        run_check(failures, "I04-T3-CSV-SCHEMA", lambda: check_csv_schema_file(cli))
        run_check(failures, "I04-T3-FILTERING", lambda: check_filtering_preserved(cli))
        run_check(failures, "I04-T3-LIST-REGRESSION", lambda: existing_list_behavior(cli))

    else:
        raise ValueError(f"unsupported stage: {stage}")

    return {"stage": stage, "passed": not failures, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", type=int, choices=(1, 2, 3))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = verify(args.stage)

    if args.json:
        print(json.dumps(result, sort_keys=True))
    elif result["passed"]:
        print(f"INTENT04_STAGE_{args.stage}_PASS")
    else:
        for failure in result["failures"]:
            print(f"{failure['check_id']}: {failure['observed']}")

    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
