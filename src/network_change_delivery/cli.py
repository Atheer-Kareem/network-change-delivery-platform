"""Command-line interface for the platform shell."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from importlib.metadata import version


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="ncdp",
        description="Network Change Delivery Platform",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('network-change-delivery')}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return its exit status."""
    parser = build_parser()
    arguments = list(argv) if argv is not None else None
    if arguments == []:
        parser.print_help()
        return 0
    if arguments is None:
        import sys

        if len(sys.argv) == 1:
            parser.print_help()
            return 0
    parser.parse_args(arguments)
    return 0
