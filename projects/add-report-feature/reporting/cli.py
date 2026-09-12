from __future__ import annotations

import argparse

from .domain import summarize
from .render import render_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("values", nargs="+", type=float)
    return parser


def produce(argv: list[str] | None = None) -> str:
    args = build_parser().parse_args(argv)
    return render_text(summarize(args.values))


def main(argv: list[str] | None = None) -> int:
    print(produce(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
