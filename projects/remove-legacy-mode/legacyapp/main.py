from __future__ import annotations

import argparse

from .legacy import legacy_format


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--legacy", action="store_true")
    return parser


def produce(argv: list[str] | None = None) -> str:
    args = build_parser().parse_args(argv)
    if args.legacy:
        return legacy_format(args.name)
    return f"Hello, {args.name}!"
