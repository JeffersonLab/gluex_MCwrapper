"""Merge MCwrapper HDDM files using the halld hddm-py interfaces."""

import argparse
import sys
from typing import Sequence

import hddm_r
import hddm_s


def merge(files: Sequence[str], out: str) -> None:
    """Merge records in order, choosing the interface from the first file name."""
    interface = hddm_r if "rest" in files[0] else hddm_s
    output_stream = interface.ostream(out)
    output_stream.compression = interface.k_z_compression
    for input_path in files:
        for entry in interface.istream(input_path):
            output_stream.write(entry)


def main(args: argparse.Namespace) -> None:
    """Merge the input files specified by the command-line arguments."""
    merge(args.files, args.output)


def _parse_args() -> argparse.Namespace:
    """Parse the output path followed by one or more input paths."""
    parser = argparse.ArgumentParser(
        description="Bundle and move MCwrapper outputs to another directory."
    )
    parser.add_argument("output")
    parser.add_argument("files", nargs="+")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main(_parse_args()))
