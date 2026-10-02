import argparse

from .service import list_items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inventory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "list":
        for item in list_items():
            print(
                f"{item.sku}\t{item.name}\t{item.quantity}\t"
                f"{str(item.active).lower()}"
            )
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
