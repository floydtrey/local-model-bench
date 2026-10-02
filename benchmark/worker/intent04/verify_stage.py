from __future__ import annotations

import argparse
import ast
import contextlib
import csv
import io
import pathlib
import sys
import tempfile
from unittest.mock import patch

from inventory.cli import build_parser, main
from inventory.models import InventoryItem


def invoke(argv: list[str]) -> tuple[int | None, str, str, BaseException | None]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    error: BaseException | None = None
    code: int | None = None

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            result = main(argv)
            code = 0 if result is None else int(result)
        except SystemExit as exc:
            code = 0 if exc.code is None else int(exc.code)
        except BaseException as exc:  # diagnostic verifier; preserve the exception as evidence
            error = exc

    return code, stdout.getvalue(), stderr.getvalue(), error


def fake_items(include_inactive: bool = False) -> list[InventoryItem]:
    active = InventoryItem("A-100", 'Widget, "Deluxe"', 4, True)
    inactive = InventoryItem("B-200", "Spare Part", 2, False)
    return [active, inactive] if include_inactive else [active]


def csv_rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def verify_parser_surface() -> None:
    parser = build_parser()

    default = parser.parse_args(["export-csv"])
    assert default.command == "export-csv"
    assert default.include_inactive is False
    assert default.output is None

    configured = parser.parse_args(
        ["export-csv", "--include-inactive", "--output", "items.csv"]
    )
    assert configured.command == "export-csv"
    assert configured.include_inactive is True
    assert configured.output == "items.csv"


def verify_stdout_export() -> None:
    calls: list[bool] = []

    def side_effect(include_inactive: bool = False) -> list[InventoryItem]:
        calls.append(include_inactive)
        return fake_items(include_inactive)

    with patch("inventory.cli.list_items", side_effect=side_effect):
        code, stdout, stderr, error = invoke(["export-csv"])

    assert error is None, repr(error)
    assert code == 0
    assert stderr == ""
    assert calls == [False]
    assert csv_rows(stdout) == [
        ["sku", "name", "quantity", "active"],
        ["A-100", 'Widget, "Deluxe"', "4", "true"],
    ]

    calls.clear()
    with patch("inventory.cli.list_items", side_effect=side_effect):
        code, stdout, stderr, error = invoke(["export-csv", "--include-inactive"])

    assert error is None, repr(error)
    assert code == 0
    assert stderr == ""
    assert calls == [True]
    assert csv_rows(stdout) == [
        ["sku", "name", "quantity", "active"],
        ["A-100", 'Widget, "Deluxe"', "4", "true"],
        ["B-200", "Spare Part", "2", "false"],
    ]


def verify_file_export() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = pathlib.Path(tmp) / "inventory.csv"
        with patch("inventory.cli.list_items", side_effect=fake_items):
            code, stdout, stderr, error = invoke(
                ["export-csv", "--include-inactive", "--output", str(output)]
            )

        assert error is None, repr(error)
        assert code == 0
        assert stdout == ""
        assert stderr == ""
        assert output.is_file()
        assert csv_rows(output.read_text(encoding="utf-8")) == [
            ["sku", "name", "quantity", "active"],
            ["A-100", 'Widget, "Deluxe"', "4", "true"],
            ["B-200", "Spare Part", "2", "false"],
        ]


def verify_output_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = pathlib.Path(tmp) / "missing-parent" / "inventory.csv"
        with patch("inventory.cli.list_items", side_effect=fake_items):
            code, stdout, stderr, error = invoke(
                ["export-csv", "--output", str(output)]
            )

        assert error is None, repr(error)
        assert code is not None and code != 0
        assert stdout == ""
        assert stderr.strip()
        assert not output.exists()


def verify_existing_list_behavior() -> None:
    code, stdout, stderr, error = invoke(["list"])
    assert error is None, repr(error)
    assert code == 0
    assert stderr == ""
    assert stdout == "A-100\tWidget\t4\ttrue\nC-300\tCable\t7\ttrue\n"


def imports_csv_module(source: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "csv" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module == "csv":
            return True
    return False


def verify_stage_1() -> None:
    verify_parser_surface()
    verify_existing_list_behavior()

    source = pathlib.Path("inventory/cli.py").read_text(encoding="utf-8")
    assert not imports_csv_module(source), "Task 1 performed Task 2 CSV work early"


def verify_stage_2() -> None:
    verify_parser_surface()
    verify_stdout_export()
    verify_existing_list_behavior()

    source = pathlib.Path("inventory/cli.py").read_text(encoding="utf-8")
    assert imports_csv_module(source), "Task 2 must use the standard-library csv module"

    # Task 3 owns file-output behavior. Passing --output after Task 2 may be
    # ignored or rejected, but it must not successfully create the requested file.
    with tempfile.TemporaryDirectory() as tmp:
        output = pathlib.Path(tmp) / "too-early.csv"
        with patch("inventory.cli.list_items", side_effect=fake_items):
            invoke(["export-csv", "--output", str(output)])
        assert not output.exists(), "Task 2 performed Task 3 file-output work early"


def verify_stage_3() -> None:
    verify_parser_surface()
    verify_stdout_export()
    verify_file_export()
    verify_output_failure()
    verify_existing_list_behavior()


def verify_stage_4() -> None:
    verify_stage_3()

    source_path = pathlib.Path("tests/test_cli.py")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    test_names = [
        node.name.lower()
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]

    assert len(test_names) >= 7, "Task 4 must add at least five CLI regression tests"
    assert "export-csv" in source
    assert "--output" in source
    assert "--include-inactive" in source

    def has_name(*terms: str) -> bool:
        return any(any(term in name for term in terms) for name in test_names)

    assert has_name("stdout", "standard_output", "console"), (
        "missing recognizable stdout-export test"
    )
    assert has_name("file", "output"), "missing recognizable file-export test"
    assert has_name("inactive"), "missing recognizable include-inactive test"
    assert has_name("escape", "comma", "quote"), "missing recognizable CSV escaping test"
    assert has_name("fail", "error", "invalid", "unwritable"), (
        "missing recognizable output-file failure test"
    )


def main_verify() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", type=int, choices=(1, 2, 3, 4))
    args = parser.parse_args()

    {
        1: verify_stage_1,
        2: verify_stage_2,
        3: verify_stage_3,
        4: verify_stage_4,
    }[args.stage]()

    print(f"INTENT04_STAGE_{args.stage}_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_verify())
