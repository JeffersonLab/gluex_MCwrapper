#!/usr/bin/env python3
"""Query MC project statistics and display Matplotlib charts."""

import datetime
import re
import sys
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import matplotlib.pyplot as plt
import MySQLdb
import pandas as pd
from mc_status import PROJECT_NOTIFIED

DB_HOST = "hallddb.jlab.org"
DB_USER = "mcuser"
DB_NAME = "gluex_mc"
START_DATE = datetime.date(2024, 1, 1)
SIZE_MULTIPLIERS = {"K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "E": 1e15}
LOCATION_GROUPS = ("JLab", "UConn", "FSU", "Glasgow", "IU", "ComputeCanada", "Other")

database_connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
database_cursor = database_connection.cursor(MySQLdb.cursors.DictCursor)


def _output_size_bytes(value: str) -> float:
    """Convert size strings using two-character suffixes and unit multipliers."""
    prefix = value[-2:-1]
    amount = float(value[:-2])
    if prefix in SIZE_MULTIPLIERS:
        return amount * SIZE_MULTIPLIERS[prefix]
    return 0.0


def _weekly_requested_events(
    rows: Sequence[Mapping[str, Any]],
) -> List[Tuple[datetime.date, int]]:
    """Accumulate requested events and emit a point at each week transition."""
    points: List[Tuple[datetime.date, int]] = []
    previous_week = -1
    running_total = 0
    for row in rows:
        submitted = row["Submit_Time"]
        running_total += row["NumEvents"]
        week = submitted.isocalendar()[1]
        if week != previous_week:
            points.append((submitted, running_total))
            running_total = 0
            previous_week = week
    return points


def _location_group(location: str) -> str:
    """Classify a hostname using ordered site patterns."""
    if "jlab.org" in location:
        return "JLab"
    if "uconn.edu" in location:
        return "UConn"
    if "fsu.edu" in location:
        return "FSU"
    if "beowulf.cluster" in location or re.search(r"@wn-d|h\d{2}-\d{3}", location):
        return "Glasgow"
    if "iu.edu" in location or "IU-Jetstream2" in location:
        return "IU"
    if "computecanada.ca" in location:
        return "ComputeCanada"
    return "Other"


def _weekly_location_counts(
    start_times: Sequence[datetime.date], start_date: datetime.date
) -> List[Tuple[datetime.date, int]]:
    """Count job starts by ISO week, inserting zero-count bins for gaps."""
    if not start_times:
        return []
    points: List[Tuple[datetime.date, int]] = []
    previous_week = (start_date - datetime.timedelta(weeks=1)).isocalendar()[1]
    running_count = 0
    for started in start_times:
        year, week, _day = started.isocalendar()
        if week - previous_week < 0:
            while week - previous_week < 0:
                points.append(
                    (
                        datetime.date.fromisocalendar(year - 1, previous_week, 1),
                        running_count,
                    )
                )
                running_count = 0
                if previous_week == 52:
                    previous_week = 0
                previous_week += 1
            running_count = 0

        if week - previous_week > 1:
            while week - previous_week > 0:
                points.append(
                    (
                        datetime.date.fromisocalendar(year, previous_week, 1),
                        running_count,
                    )
                )
                running_count = 0
                previous_week += 1
            running_count = 0
            previous_week = week

        if week - previous_week == 1:
            points.append(
                (datetime.date.fromisocalendar(year, previous_week, 1), running_count)
            )
            running_count = 0
            previous_week = week
        running_count += 1

    final_year = start_times[-1].isocalendar()[0]
    points.append(
        (datetime.date.fromisocalendar(final_year, previous_week, 1), running_count)
    )
    return points


class MCStatistics:
    """Query statistics and display charts using the supplied database cursor."""

    def __init__(self, cursor: "MySQLdb.cursors.DictCursor") -> None:
        self._cursor = cursor

    def print_total_output_size(self) -> None:
        """Print the total output size in decimal terabytes."""
        self._cursor.execute("SELECT TotalSizeOut From Project;")
        rows = self._cursor.fetchall()
        total_bytes = 0.0
        for project in rows:
            if project["TotalSizeOut"] is None:
                continue
            total_bytes += _output_size_bytes(str(project["TotalSizeOut"]))
        print(total_bytes / 1e12)
        print("T")

    def show_user_project_shares(self, graph: bool = True) -> None:
        """Print per-user project and event totals, optionally displaying pie charts."""
        query = (
            "SELECT UName, NumEvents From Project "
            "WHERE Submit_Time > DATE('2024-01-01') "
            f"AND Notified = {PROJECT_NOTIFIED} ORDER BY Submit_Time;"
        )
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        user_totals: Dict[str, Tuple[int, int]] = {}
        total_events = 0
        for project in rows:
            total_events += project["NumEvents"]
            user = project["UName"]
            project_count, event_count = user_totals.get(user, (0, 0))
            user_totals[user] = (project_count + 1, event_count + project["NumEvents"])
        print(user_totals)
        users = pd.DataFrame.from_dict(
            user_totals, orient="index", columns=["NumProj", "NumEvents"]
        )
        print(users)
        project_total: float = 0
        sizes = []
        labels = []
        for user, (project_count, event_count) in user_totals.items():
            sizes.append(event_count)
            labels.append(user)
            project_total += float(project_count)
        print(len(user_totals), project_total, total_events)

        if graph:
            users.plot.pie(subplots=True, figsize=(10, 5))
            _figure, axis = plt.subplots()
            axis.pie(
                sizes,
                labels=labels,
                autopct="%1.1f%%",
                shadow=True,
                startangle=90,
                radius=10000,
                labeldistance=1.1,
            )
            axis.axis("equal")
            plt.show()

    def plot_attempt_wall_times(self) -> None:
        """Plot elapsed times for attempts with both start and completion times."""
        query = (
            "SELECT UNIX_TIMESTAMP(Start_Time), UNIX_TIMESTAMP(Completed_Time) "
            "From Attempts;"
        )
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        wall_times = []
        for attempt in rows:
            completed = attempt["UNIX_TIMESTAMP(Completed_Time)"]
            started = attempt["UNIX_TIMESTAMP(Start_Time)"]
            if completed is None or started is None:
                continue
            wall_times.append(completed - started)
        _figure, axis = plt.subplots(1, 1)
        axis.hist(wall_times, bins=50, color="lightblue")
        plt.show()

    def plot_attempt_start_times(self) -> None:
        """Print recorded CPU time and plot attempt start times."""
        query = (
            "SELECT UNIX_TIMESTAMP(Start_Time), CPUTime "
            "From Attempts where CPUTime != 0;"
        )
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        total_cpu_time = datetime.timedelta(0)
        start_times = []
        for attempt in rows:
            start_times.append(attempt["UNIX_TIMESTAMP(Start_Time)"])
            total_cpu_time += attempt["CPUTime"]
        print(total_cpu_time)
        _figure, axis = plt.subplots(1, 1)
        axis.hist(start_times, bins=6, color="lightblue")
        plt.show()

    def plot_usage_timeline(self) -> None:
        """Plot requested event counts aggregated at week transitions."""
        query = (
            "SELECT UName, Submit_Time, NumEvents FROM Project "
            "WHERE Submit_Time > DATE('2024-01-01') "
            f"AND Notified = {PROJECT_NOTIFIED} ORDER BY Submit_Time;"
        )
        self._cursor.execute(query)
        points = _weekly_requested_events(self._cursor.fetchall())
        dates = [submitted for submitted, events in points]
        totals = [events for submitted, events in points]
        plt.plot(dates, totals)
        plt.xlabel("Time")
        plt.ylabel("NumEvents")
        plt.title("Number of events requested per week")
        plt.legend()
        plt.show()

    def plot_running_locations(self) -> None:
        """Display site-share and weekly job-count charts."""
        query = (
            "SELECT RunningLocation, Start_Time, WallTime, CPUTime, RAMUsed, ExitCode "
            f"FROM Attempts WHERE Start_Time > DATE('{START_DATE.isoformat()}') "
            "ORDER BY Start_Time;"
        )
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        groups: Dict[str, List[Mapping[str, Any]]] = {
            site: [] for site in LOCATION_GROUPS
        }
        for attempt in rows:
            groups[_location_group(attempt["RunningLocation"])].append(attempt)
        for site, attempts in groups.items():
            print(site, len(attempts))
        sizes = [len(attempts) for attempts in groups.values() if attempts]
        labels = [site for site, attempts in groups.items() if attempts]
        _figure, axis = plt.subplots()
        axis.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90)
        axis.axis("equal")
        plt.title("Number of jobs per running location")
        plt.show()

        for site, attempts in groups.items():
            if not attempts:
                continue
            start_times = [attempt["Start_Time"] for attempt in attempts]
            points = _weekly_location_counts(start_times, START_DATE)
            dates = [started for started, job_count in points]
            counts = [job_count for started, job_count in points]
            plt.plot(dates, counts, label=site)
            print(site, dates, counts)
        plt.xlabel("Time")
        plt.ylabel("NumJobs")
        plt.title("Percentage of jobs run per week per OSG location")
        plt.legend()
        plt.show()


def main(argv: Sequence[str]) -> None:
    """Display user and running-location charts."""
    statistics = MCStatistics(database_cursor)
    statistics.show_user_project_shares(True)
    statistics.plot_running_locations()
    database_connection.close()


if __name__ == "__main__":
    main(sys.argv[1:])
