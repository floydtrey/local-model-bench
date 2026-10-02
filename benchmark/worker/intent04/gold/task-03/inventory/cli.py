import argparse
import csv
import sys

from .service import list_items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inventory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list")

    export_parser = subparsers.add_parser("export-csv")
    export_parser.add_argument("--include-inactive", action="store_true")
    export_parser.add_argument("--output")
    return parser


def _write_csv(items, stream) -> None:
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["sku", "name", "quantity", "active"])
    for item in items:
        writer.writerow(
            [item.sku, item.name, item.quantity, str(item.active).lower()]
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "list":
        for item in list_items():
            print(
                f"{item.sku}\t{item.name}\t{item.quantity}\t"
                f"{str(item.active).lower()}"
            )
        return 0

    if args.command == "export-csv":
        items = list_items(include_inactive=args.include_inactive)
        if args.output is None:
            _write_csv(items, sys.stdout)
            return 0

        try:
            with open(args.output, "w", encoding="utf-8", newline="") as stream:
                _write_csv(items, stream)
        except OSError as exc:
            print(f"error: unable to write CSV: {exc}", file=sys.stderr)
            return 1
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
