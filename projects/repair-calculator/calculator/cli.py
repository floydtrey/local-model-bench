from __future__ import annotations

import argparse

from .core import average


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("values", nargs="+", type=float)
    args = parser.parse_args(argv)
    print(average(args.values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
