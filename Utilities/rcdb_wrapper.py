"""Print run numbers and selected RCDB condition values as JSON."""

import argparse
import json
import os

import rcdb


def main(query: str, min_run: int, max_run: int) -> None:
    """Query RCDB and print the resulting table, including run numbers."""
    provider = rcdb.RCDBProvider(os.environ.get("RCDB_CONNECTION"))
    selected_runs = provider.select_runs(str(query), min_run, max_run)
    table = selected_runs.get_values(["event_count", "polarimeter_converter"], True)
    print(json.dumps(table))


def _parse_args() -> argparse.Namespace:
    """Parse the query and inclusive run range from the command line."""
    parser = argparse.ArgumentParser(
        description="Python script to return an RCDB query."
    )
    parser.add_argument("rcdb_query", type=str, help="RCBD Query")
    parser.add_argument("min_runnumber", type=int, help="Min Run Number")
    parser.add_argument("max_runnumber", type=int, help="Max Run Number")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(args.rcdb_query, args.min_runnumber, args.max_runnumber)
