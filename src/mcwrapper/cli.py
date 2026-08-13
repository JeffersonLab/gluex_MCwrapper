"""Command-line entry point for the modern MCwrapper package."""

import argparse
from typing import Optional, Sequence


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command-line parser without performing side effects."""
    return argparse.ArgumentParser(
        prog="mcwrapper",
        description="Plan and run GlueX Monte Carlo workflows.",
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse command-line arguments and return a process exit status."""
    parser = build_parser()
    parser.parse_args(argv)
    return 0
