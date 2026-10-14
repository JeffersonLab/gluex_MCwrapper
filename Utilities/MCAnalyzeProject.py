#!/usr/bin/env python3
"""Analyze project attempts and export Plotly distributions and failure charts."""

import argparse
import datetime
import sys
from pathlib import Path
from typing import Any, List, Sequence, Union

import MySQLdb
import pandas as pd
import plotly
import plotly.express as px
from mc_status import ExitCode, ProjectStatus

DB_HOST = "hallddb.jlab.org"
DB_USER = "mcuser"
DB_NAME = "gluex_mc"
EXIT_CODE_LABELS = {
    ExitCode.RANDOM_TRIGGER_NOT_FOUND: "Random trigger not found",
    ExitCode.RANDOM_TRIGGER_DOES_NOT_EXIST: "Random trigger does not exist",
    ExitCode.OUTPUT_NOT_RETURNED: "Output data not returned",
    None: "Still Running",
    ExitCode.SUCCESS: "Successfully completed",
}

ProjectId = Union[int, str]

database_connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
database_cursor = database_connection.cursor(MySQLdb.cursors.DictCursor)


def weighted_average(counts: Sequence[int]) -> float:
    """Compute and print the mean of values represented by frequency counts."""
    total_count = sum(counts)
    weighted_total = sum(value * count for value, count in enumerate(counts))
    if total_count != 0:
        average = float(weighted_total) / float(total_count)
        print("Avg number of attempts: ", average)
        return average
    print("Can't compute Average as it is nan")
    return 0.0


def _count_frequencies(values: Sequence[int]) -> List[int]:
    """Count integer values, including a zero bin for empty input."""
    maximum = max(0, max(values, default=0))
    counts = [0] * (maximum + 1)
    for value in values:
        counts[value] += 1
    return counts


class ProjectAnalyzer:
    """Query project activity and export charts using the supplied cursor."""

    def __init__(
        self,
        cursor: "MySQLdb.cursors.DictCursor",
        output_dir: str = "./MCAnalyze_out/",
    ) -> None:
        self._cursor = cursor
        self._output_prefix = output_dir

    def analyze_start_distribution(
        self, project_id: ProjectId, make_plot: bool, extra_constraint: str = ""
    ) -> None:
        """Print the distribution of recorded job starts and optionally plot it."""
        self._analyze_distribution(project_id, make_plot, extra_constraint, starts=True)

    def analyze_attempt_distribution(
        self, project_id: ProjectId, make_plot: bool, extra_constraint: str = ""
    ) -> float:
        """Print the attempt distribution, optionally plot it, and return its mean."""
        counts = self._analyze_distribution(
            project_id, make_plot, extra_constraint, starts=False
        )
        return weighted_average(counts)

    def _project_selection(
        self, project_id: ProjectId, extra_constraint: str, comparison: str = "="
    ) -> str:
        """Build a Project subquery with an optional caller-supplied filter."""
        query = f"SELECT ID FROM Project where ID {comparison} {project_id}"
        if extra_constraint != "":
            query = f"{query} && {extra_constraint}"
        return query

    def _analyze_distribution(
        self,
        project_id: ProjectId,
        make_plot: bool,
        extra_constraint: str,
        starts: bool,
    ) -> List[int]:
        print("Getting the distributions of attempts for project", project_id)
        if starts:
            selection = "NumStarts as Starts"
            condition = "NumStarts is NOT NULL && "
            value_key = plot_column = "Starts"
            file_prefix = "StartsDistribution_"
        else:
            selection = "COUNT(*) as AttemptsCount"
            condition = ""
            value_key = "AttemptsCount"
            plot_column = "Attempts_Count"
            file_prefix = "CountDistribution_"
        query = (
            f"SELECT {selection} from Attempts where {condition}Job_ID in "
            "(SELECT ID from Jobs where Project_ID IN ("
            f"{self._project_selection(project_id, extra_constraint)}"
            ")) GROUP BY Job_ID;"
        )
        print(query)
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        print("Obtained", len(rows), "Entries")
        values = [row[value_key] for row in rows]
        counts = _count_frequencies(values)
        if make_plot:
            frame = pd.DataFrame(values, columns=[plot_column])
            figure = px.histogram(frame, x=plot_column, nbins=len(counts))
            self._write_plot(figure, f"{file_prefix}{project_id}")
        print(counts)
        return counts

    def _write_plot(
        self,
        figure: "plotly.graph_objs.Figure",
        file_name: str,
        image_name: str = "",
    ) -> None:
        """Write an HTML plot with PNG export settings."""
        plotly.offline.plot(
            figure,
            filename=str(self._plot_path(f"{file_name}.html")),
            image="png",
            image_filename=str(self._plot_path(image_name or file_name)),
        )

    def _plot_path(self, name: str) -> Path:
        """Apply the literal export prefix before pathlib normalizes the result."""
        return Path(f"{self._output_prefix}{name}")

    def plot_failure_breakdown(
        self,
        project_id: ProjectId,
        extra_constraint: str = "",
        file_name: str = "failurePie_Total",
    ) -> None:
        """Plot failure programs and exit codes for the selected project range."""
        print("Getting the Failure Pie for project ", project_id)
        project_selection = self._project_selection(
            project_id, extra_constraint, comparison=">"
        )
        query = (
            "SELECT ProgramFailed as pf, COUNT(*) as AttemptsCount from Attempts "
            "where ProgramFailed is not NULL && Job_ID in "
            "(SELECT ID from Jobs where Project_ID IN ("
            f"{project_selection})) GROUP BY ProgramFailed;"
        )
        print(query)
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        print("Obtained", len(rows), "Entries")
        failures = pd.DataFrame(rows)
        if len(rows) == 0:
            failures = pd.DataFrame(columns=["pf", "AttemptsCount"])
        print("df created")

        exit_code_query = (
            "SELECT ExitCode as pf, COUNT(*) as AttemptsCount from Attempts "
            "where ProgramFailed is NULL && Job_ID in "
            "(SELECT ID from Jobs where Project_ID IN ("
            f"{project_selection})) GROUP BY ExitCode;"
        )
        self._cursor.execute(exit_code_query)
        exit_code_rows = self._cursor.fetchall()
        for row in exit_code_rows:
            row["pf"] = EXIT_CODE_LABELS.get(row["pf"], row["pf"])
        print(exit_code_rows)
        exit_codes = pd.DataFrame(exit_code_rows)
        print("df2 created")
        combined = pd.concat([failures, exit_codes])
        print("concat completed")

        title = "Failure Blame For "
        if int(project_id) == 0:
            title = f"{title}All Projects"
        if extra_constraint != "":
            title = f"{title} passing {extra_constraint}"
        attempt_count = (
            failures["AttemptsCount"].sum() + exit_codes["AttemptsCount"].sum()
        )
        title = f"{title} ({attempt_count} Attempts) "
        figure = px.pie(combined, values="AttemptsCount", names="pf", title=title)
        figure.update_traces(textposition="inside", textinfo="percent+label")
        self._write_plot(figure, file_name)

    def analyze(
        self, project_id: str, xaxis_key: str, extra_constraint: str = ""
    ) -> None:
        """Analyze one project or a filtered collection of projects."""
        if int(project_id) != 0:
            print("Analyzing project #", project_id)
            self.analyze_attempt_distribution(project_id, True)
            self.analyze_start_distribution(project_id, True)
            self.plot_failure_breakdown(
                0, f"ID = {project_id}", f"failurePie_Proj{project_id}"
            )
        else:
            self._analyze_all_projects(project_id, xaxis_key, extra_constraint)

    def _analyze_all_projects(
        self, project_id: str, xaxis_key: str, extra_constraint: str
    ) -> None:
        print("Total analysis")
        query = f"SELECT * FROM Project WHERE Tested > {ProjectStatus.UNTESTED} "
        if extra_constraint != "":
            query = f"{query} && {extra_constraint}"
        query = f"{query} Order by ID asc"
        print(query)
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        projects = pd.DataFrame(rows)
        x_values: List[Any] = []
        averages: List[float] = []
        for row in rows:
            x_values.append(row[xaxis_key] if row[xaxis_key] else "NA")
            averages.append(self.analyze_attempt_distribution(row["ID"], False))
        projects["avg_attempts_per_jobs"] = averages
        title = "All Projects Status>0"
        if extra_constraint != "":
            title = f"Projects passing {extra_constraint}"
        if str(x_values[0]).isnumeric() or isinstance(x_values[0], datetime.datetime):
            figure = px.scatter(x=x_values, y=averages)
            figure.update_layout(
                yaxis_type="log",
                xaxis_title=xaxis_key,
                yaxis_title="avg_attempts_per_jobs",
                title=title,
            )
        else:
            figure = px.histogram(
                projects, x=xaxis_key, y="avg_attempts_per_jobs", histfunc="avg"
            )
        self._write_plot(
            figure, "CountDistribution_Total", "AvgCountDistribution_Total"
        )
        print("XAxis:", xaxis_key)
        if "Set" not in xaxis_key:
            self.plot_failure_breakdown(project_id, extra_constraint)
            return

        self._cursor.execute(f"SELECT DISTINCT {xaxis_key} FROM Project")
        rows = self._cursor.fetchall()
        for row in rows:
            print(row)
            key = row[xaxis_key] if row[xaxis_key] is not None else "NULL"
            print("KEY:", key)
            if key != "NULL":
                constraint = f'{xaxis_key} = "{key}"'
            else:
                constraint = f"{xaxis_key} is {key}"
            self.plot_failure_breakdown(project_id, constraint, f"FailurePie_{key}")


def _analysis_output_directory(prefix: str) -> Path:
    """Append MCAnalyze_out to the -o prefix to form the output directory."""
    return Path(f"{prefix}MCAnalyze_out")


def _parse_args() -> argparse.Namespace:
    """Parse project selection, plot constraints, and the output prefix."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-P",
        "--projectID",
        dest="project_id",
        metavar="PROJECTID",
        required=True,
        help="The ID number of the project to be analyzed",
    )
    parser.add_argument(
        "-x",
        "--xaxis",
        dest="xaxis_key",
        metavar="XAXIS",
        required=False,
        help="the x axis key for the avg attempts per job",
    )
    parser.add_argument(
        "-e",
        "--extraConstraint",
        dest="extra_constraint",
        metavar="EXTRACONSTRAINT",
        required=False,
        default="",
        help="an added constraint agains the Project table",
    )
    parser.add_argument(
        "-o",
        "--outputloc",
        dest="output_dir",
        metavar="OUTPUTLOC",
        required=False,
        type=_analysis_output_directory,
        default="./",
        help="path to the output directory",
    )
    return parser.parse_args()


def main(argv: Sequence[str]) -> None:
    """Analyze projects selected by the process command line."""
    args = _parse_args()
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(error, file=sys.stderr)
    analyzer = ProjectAnalyzer(database_cursor, f"{args.output_dir}/")
    analyzer.analyze(args.project_id, args.xaxis_key, args.extra_constraint)


if __name__ == "__main__":
    main(sys.argv[1:])
