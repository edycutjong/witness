"""Witness command line. P1a: a version stub; `why`, `check`, `export` and `demo` land in P1b."""

from __future__ import annotations

import argparse
import sys

from . import __version__


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="witness", description=__doc__)
    ap.add_argument("--version", action="store_true", help="print the Witness and relate-db versions")
    args = ap.parse_args(argv)
    if args.version:
        try:
            import relate

            rv = relate.__version__
        except Exception:  # noqa: BLE001
            rv = "not installed"
        print(f"witness {__version__} (relate-db {rv})")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
