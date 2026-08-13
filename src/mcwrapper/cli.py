"""Command-line entry point for the modern MCwrapper package."""

import argparse
import json
import sys
from typing import Optional, Sequence

from mcwrapper.contracts import ExecutionPolicy, ExitCode, MutationRefusedError


PROFILE_NAMES = ("read-only", "development", "production")


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command-line parser without performing side effects."""
    parser = argparse.ArgumentParser(
        prog="mcwrapper",
        description="Plan and run GlueX Monte Carlo workflows.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_NAMES,
        default="read-only",
        help="runtime profile (default: read-only)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="allow mutation when used with a mutation-capable profile",
    )
    return parser


def _write_safety_refusal(message: str, output_format: str) -> None:
    if output_format == "json":
        payload = {
            "error": {
                "code": "mutation_not_authorized",
                "message": message,
            }
        }
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=sys.stderr)
    else:
        print(f"mcwrapper: error: {message}", file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse command-line arguments and return a process exit status."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    policy = ExecutionPolicy(profile=arguments.profile, execute=arguments.execute)

    # Supplying --execute is itself an explicit request to leave dry-run mode.
    # Reject an incomplete request before a future subcommand can reach an adapter.
    if policy.execute:
        try:
            policy.require_mutation()
        except MutationRefusedError as exc:
            _write_safety_refusal(str(exc), arguments.format)
            return int(ExitCode.SAFETY_REFUSAL)

    return int(ExitCode.SUCCESS)
