#!/usr/bin/env python3
"""Verify a sanitized MCwrapper fixture archive before it is committed or loaded."""

import argparse
from pathlib import Path
import sys
from typing import Optional, Sequence

from tools.fixture_archive import FixtureValidationError, validate_archive


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        manifest = validate_archive(args.archive)
    except (OSError, FixtureValidationError) as error:
        print("fixture verification failed: {}".format(error), file=sys.stderr)
        return 2
    total = sum(table["rows"] for table in manifest["tables"].values())
    print("fixture archive is valid: {} rows".format(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
