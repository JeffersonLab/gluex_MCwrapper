#!/usr/bin/env python3
"""Report statistics for MCwrapper projects submitted in a calendar year."""

import argparse
import sys
from contextlib import closing
from typing import TYPE_CHECKING, Any, Dict, NamedTuple, Sequence

from mc_status import JOB_ACTIVE

if TYPE_CHECKING:
    import MySQLdb


DB_HOST = "hallddb.jlab.org"
DB_USER = "mcuser"
DB_NAME = "gluex_mc"

QUERIES: Dict[str, str] = {
    "projects": (
        "SELECT COUNT(*) AS project_count, SUM(NumEvents) AS requested_events, "
        "COUNT(DISTINCT UName) AS unique_users FROM Project "
        "WHERE Submit_Time >= %s AND Submit_Time < %s"
    ),
    "active_jobs": (
        "SELECT COUNT(*) AS active_jobs FROM Jobs "
        "INNER JOIN Project ON Jobs.Project_ID = Project.ID "
        "WHERE Project.Submit_Time >= %s AND Project.Submit_Time < %s "
        f"AND Jobs.IsActive = {JOB_ACTIVE}"
    ),
    "cpu_time": (
        "SELECT SUM(TIME_TO_SEC(Attempts.CPUTime)) AS cpu_seconds FROM Attempts "
        "INNER JOIN Jobs ON Jobs.ID = Attempts.Job_ID "
        "INNER JOIN Project ON Project.ID = Jobs.Project_ID "
        "WHERE Project.Submit_Time >= %s AND Project.Submit_Time < %s"
    ),
    "average_attempts": (
        "SELECT AVG(attempt_count) AS average_attempts FROM "
        "(SELECT COUNT(Attempts.ID) AS attempt_count FROM Jobs "
        "INNER JOIN Project ON Project.ID = Jobs.Project_ID "
        "LEFT JOIN Attempts ON Attempts.Job_ID = Jobs.ID "
        f"WHERE Jobs.IsActive = {JOB_ACTIVE} AND Project.Submit_Time >= %s "
        "AND Project.Submit_Time < %s GROUP BY Jobs.ID) AS attempt_counts"
    ),
}


class YearlyStatistics(NamedTuple):
    """Summary of projects and their recorded activity, with CPU time in seconds."""

    year: int
    project_count: int
    requested_events: int
    active_jobs: int
    cpu_seconds: float
    unique_users: int
    average_attempts: float

    @classmethod
    def from_cursor(
        cls, cursor: "MySQLdb.cursors.DictCursor", year: int
    ) -> "YearlyStatistics":
        """Read aggregates, including zero-attempt jobs in the active-job average."""
        if not 1 <= year <= 9998:
            raise ValueError("year must be between 1 and 9998")
        date_range = (f"{year:04d}-01-01", f"{year + 1:04d}-01-01")
        results: Dict[str, Any] = {}
        for name, query in QUERIES.items():
            cursor.execute(query, date_range)
            results[name] = cursor.fetchone()

        projects = results["projects"]
        return cls(
            year=year,
            project_count=int(projects["project_count"]),
            requested_events=int(projects["requested_events"] or 0),
            active_jobs=int(results["active_jobs"]["active_jobs"]),
            cpu_seconds=float(results["cpu_time"]["cpu_seconds"] or 0),
            unique_users=int(projects["unique_users"]),
            average_attempts=float(
                results["average_attempts"]["average_attempts"] or 0
            ),
        )

    def format_report(self) -> str:
        """Format a plain-text report with explicit units and aligned values."""
        rows = [
            ("Projects", f"{self.project_count:,}"),
            ("Requested events", f"{self.requested_events:,}"),
            ("Active jobs (current)", f"{self.active_jobs:,}"),
            ("CPU hours (all attempts)", f"{self.cpu_seconds / 3600:,.2f}"),
            ("Unique submitters", f"{self.unique_users:,}"),
            ("Avg attempts per active job", f"{self.average_attempts:.2f}"),
        ]
        label_width = max(len(label) for label, value in rows)
        value_width = max(len(value) for label, value in rows)
        lines = [
            f"MCwrapper statistics for {self.year}",
            (
                f"Projects submitted: {self.year:04d}-01-01 <= Submit_Time "
                f"< {self.year + 1:04d}-01-01"
            ),
            "",
        ]
        lines.extend(
            f"{label:<{label_width}}  {value:>{value_width}}" for label, value in rows
        )
        lines.extend(
            ["", "Jobs and CPU time include all recorded activity for these projects."]
        )
        return "\n".join(lines)


def _parse_year(value: str) -> int:
    """Validate a year whose following January can be used as an upper bound."""
    try:
        year = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("year must be an integer")
    if not 1 <= year <= 9998:
        raise argparse.ArgumentTypeError("year must be between 1 and 9998")
    return year


def main(argv: Sequence[str]) -> None:
    """Read yearly statistics and print a report, closing database resources."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("year", type=_parse_year, help="project submission year")
    args = parser.parse_args(argv)

    try:
        import MySQLdb
    except ImportError:
        parser.exit(1, "error: MySQLdb (mysqlclient) is required to read statistics.\n")

    try:
        with closing(
            MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
        ) as connection:
            with closing(connection.cursor(MySQLdb.cursors.DictCursor)) as cursor:
                statistics = YearlyStatistics.from_cursor(cursor, args.year)
    except MySQLdb.Error as error:
        parser.exit(1, f"error: unable to read yearly statistics: {error}\n")

    print(statistics.format_report())


if __name__ == "__main__":
    main(sys.argv[1:])
