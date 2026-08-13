#!/usr/bin/env python3
"""Export a bounded, anonymized, referentially complete MCwrapper fixture."""

import argparse
from datetime import date, datetime, timedelta
import hashlib
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from tools.cluster_probe import validate_defaults_file
from tools.fixture_archive import TABLE_ORDER, validate_archive, write_archive


PROJECT_SELECTORS = {
    "queued": "SELECT ID FROM Project WHERE Is_Dispatched = 0 ORDER BY ID LIMIT 2",
    "dispatched": """SELECT p.ID FROM Project p WHERE p.Is_Dispatched > 0
        AND p.Completed_Time IS NULL
        AND EXISTS (SELECT 1 FROM Jobs j WHERE j.Project_ID=p.ID)
        AND NOT EXISTS (SELECT 1 FROM Jobs j JOIN Attempts a ON a.Job_ID=j.ID WHERE j.Project_ID=p.ID)
        ORDER BY p.ID LIMIT 2""",
    "running": """SELECT DISTINCT p.ID FROM Project p JOIN Jobs j ON j.Project_ID=p.ID
        JOIN Attempts a ON a.Job_ID=j.ID
        WHERE a.Status IN ('1','2','dispatched','undispatched') ORDER BY p.ID LIMIT 2""",
    "failed": """SELECT DISTINCT p.ID FROM Project p JOIN Jobs j ON j.Project_ID=p.ID
        JOIN Attempts a ON a.Job_ID=j.ID
        WHERE (a.ExitCode IS NOT NULL AND a.ExitCode <> 0)
           OR a.Status IN ('failed','problem','6') ORDER BY p.ID LIMIT 2""",
    "retried": """SELECT DISTINCT p.ID FROM Project p JOIN Jobs j ON j.Project_ID=p.ID
        JOIN Attempts a ON a.Job_ID=j.ID GROUP BY p.ID, j.ID HAVING COUNT(a.ID) >= 2
        ORDER BY p.ID LIMIT 2""",
    "completed": """SELECT DISTINCT p.ID FROM Project p JOIN Jobs j ON j.Project_ID=p.ID
        JOIN Attempts a ON a.Job_ID=j.ID
        WHERE a.Status IN ('4','succeeded') AND a.ExitCode=0 ORDER BY p.ID LIMIT 2""",
    "bundled": "SELECT ID FROM Project WHERE Tested IN (100,400) ORDER BY ID LIMIT 2",
    "notified": "SELECT ID FROM Project WHERE Notified=1 ORDER BY ID LIMIT 2",
}
TEXT_FIELDS = {
    "Project": {"Config_Stub", "RCDBQuery", "ReactionLines", "Comments"},
    "Attempts": {"ProgramFailed"},
}
PATH_FIELDS = {
    "Project": {"Generator_Config", "OutputLocation", "FinalDestination"},
    "Randoms": {"Path"},
}
HOST_FIELDS = {
    "Project": {"UIp"},
    "Attempts": {"SubmitHost", "RunningLocation", "RunIP"},
}


def _fetch(cursor: Any, query: str, args: Sequence[Any] = ()) -> List[Mapping[str, Any]]:
    cursor.execute(query, args)
    return list(cursor.fetchall())


def _in_clause(values: Sequence[Any]) -> Tuple[str, Tuple[Any, ...]]:
    if not values:
        return "(NULL)", ()
    return "({})".format(",".join(["%s"] * len(values))), tuple(values)


def collect_rows(cursor: Any) -> Tuple[Mapping[str, List[Mapping[str, Any]]], Mapping[str, List[Any]]]:
    selections = {
        name: [row["ID"] for row in _fetch(cursor, query)]
        for name, query in PROJECT_SELECTORS.items()
    }
    project_ids = sorted({value for values in selections.values() for value in values})
    project_clause, project_args = _in_clause(project_ids)
    projects = _fetch(cursor, "SELECT * FROM Project WHERE ID IN {} ORDER BY ID".format(project_clause), project_args)

    jobs = []
    for project_id in project_ids:
        jobs.extend(
            _fetch(
                cursor,
                """SELECT j.* FROM Jobs j WHERE j.Project_ID=%s
                ORDER BY (SELECT COUNT(*) FROM Attempts a WHERE a.Job_ID=j.ID) DESC, j.ID
                LIMIT 4""",
                (project_id,),
            )
        )
    job_ids = [row["ID"] for row in jobs]
    attempts = []
    for job_id in job_ids:
        selected = _fetch(
            cursor,
            "SELECT * FROM Attempts WHERE Job_ID=%s ORDER BY ID DESC LIMIT 4",
            (job_id,),
        )
        attempts.extend(reversed(selected))

    user_ids = sorted({row["user_id"] for row in projects if row.get("user_id") is not None})
    user_clause, user_args = _in_clause(user_ids)
    users = _fetch(cursor, "SELECT * FROM Users WHERE ID IN {} ORDER BY ID".format(user_clause), user_args)
    generator_perfiles = _fetch(cursor, "SELECT * FROM Generator_perfiles ORDER BY ID")
    return {
        "Users": users,
        "Project": projects,
        "Jobs": jobs,
        "Attempts": attempts,
        "Generator_perfiles": generator_perfiles,
    }, selections


def _token(value: Any) -> str:
    return "[redacted:{}]".format(hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12])


def sanitize_rows(
    source: Mapping[str, Sequence[Mapping[str, Any]]]
) -> Tuple[Mapping[str, List[Mapping[str, Any]]], Mapping[str, Mapping[Any, int]]]:
    id_maps = {
        table: {row["ID"]: index for index, row in enumerate(source.get(table, ()), 1)}
        for table in TABLE_ORDER
    }
    timestamp_values = sorted(
        {
            value
            for rows in source.values()
            for row in rows
            for value in row.values()
            if isinstance(value, (date, datetime))
        },
        key=str,
    )
    timestamp_map = {
        value: datetime(2000, 1, 1) + timedelta(minutes=index)
        for index, value in enumerate(timestamp_values)
    }
    foreign_keys = {
        ("Project", "user_id"): "Users",
        ("Jobs", "Project_ID"): "Project",
        ("Attempts", "Job_ID"): "Jobs",
    }
    sanitized: Dict[str, List[Mapping[str, Any]]] = {}
    for table in TABLE_ORDER:
        clean_rows = []
        for row in source.get(table, ()):
            clean: Dict[str, Any] = {}
            new_id = id_maps[table][row["ID"]]
            for column, value in row.items():
                if column == "ID":
                    clean[column] = new_id
                elif (table, column) in foreign_keys:
                    clean[column] = None if value is None else id_maps[foreign_keys[(table, column)]][value]
                elif isinstance(value, (date, datetime)):
                    clean[column] = timestamp_map[value].isoformat(sep=" ")
                elif value is None:
                    clean[column] = None
                elif table == "Users" and column == "name":
                    clean[column] = "user-{}".format(new_id)
                elif table == "Project" and column in {"Submitter", "UName"}:
                    clean[column] = "user-{}".format(new_id)
                elif table == "Project" and column == "Email":
                    clean[column] = "user-{}@example.invalid".format(new_id)
                elif column in TEXT_FIELDS.get(table, set()):
                    clean[column] = _token(value)
                elif column in PATH_FIELDS.get(table, set()) or (isinstance(value, str) and value.startswith("/")):
                    clean[column] = "/fixture/{}/{}/{}".format(table.lower(), column.lower(), new_id)
                elif column in HOST_FIELDS.get(table, set()):
                    clean[column] = "host-{}.example.invalid".format(new_id)
                elif table == "Attempts" and column == "BatchJobID":
                    clean[column] = "batch-{}".format(new_id)
                elif isinstance(value, bytes):
                    clean[column] = value.decode("utf-8", errors="replace")
                else:
                    clean[column] = value
            clean_rows.append(clean)
        sanitized[table] = clean_rows
    return sanitized, id_maps


def schema_sql(cursor: Any) -> str:
    statements = []
    for table in TABLE_ORDER:
        cursor.execute("SHOW CREATE TABLE `{}`".format(table))
        row = cursor.fetchone()
        statement = row.get("Create Table") if isinstance(row, dict) else row[1]
        statement = re.sub(r" AUTO_INCREMENT=\d+", "", statement)
        statements.append(statement.rstrip(";") + ";")
    return "\n\n".join(statements) + "\n"


def export(defaults_file: Path, database: str, output: Path) -> None:
    defaults_file = validate_defaults_file(defaults_file)
    if not re.fullmatch(r"[A-Za-z0-9_$]+", database):
        raise ValueError("database name contains unsupported characters")
    try:
        import MySQLdb
        import MySQLdb.cursors
    except ImportError as error:
        raise RuntimeError("mysqlclient is required for fixture export") from error
    connection = MySQLdb.connect(
        read_default_file=str(defaults_file),
        db=database,
        cursorclass=MySQLdb.cursors.DictCursor,
    )
    try:
        cursor = connection.cursor()
        cursor.execute("SET SESSION TRANSACTION READ ONLY")
        cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
        source, selections = collect_rows(cursor)
        schema = schema_sql(cursor)
        sanitized, id_maps = sanitize_rows(source)
        clean_selections = {
            name: [id_maps["Project"][value] for value in values if value in id_maps["Project"]]
            for name, values in selections.items()
        }
        write_archive(output, schema, sanitized, clean_selections)
        validate_archive(output)
        connection.rollback()
    finally:
        connection.close()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql-defaults-file", required=True, type=Path)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        export(args.mysql_defaults_file, args.database, args.output)
    except (OSError, RuntimeError, ValueError) as error:
        print("fixture export failed: {}".format(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
