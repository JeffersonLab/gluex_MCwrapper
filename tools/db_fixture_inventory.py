#!/usr/bin/env python3
"""Inventory an MCwrapper database using read-only SELECT statements."""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from tools.cluster_probe import validate_defaults_file


SCHEMA_VERSION = 1
IDENTIFIER = re.compile(r"^[A-Za-z0-9_$]+$")
STATE_COLUMNS = frozenset(
    {
        "dataverified",
        "is_dispatched",
        "isactive",
        "notified",
        "state",
        "status",
        "tested",
    }
)

TABLE_QUERY = """
SELECT TABLE_NAME, TABLE_ROWS
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_NAME
""".strip()

RELATIONSHIP_QUERY = """
SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
""".strip()

COLUMN_QUERY = """
SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
ORDER BY TABLE_NAME, ORDINAL_POSITION
""".strip()


def validate_identifier(value: str, description: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError("{} contains unsupported characters".format(description))
    return value


def mysql_query(defaults_file: Path, database: str, query: str) -> List[List[str]]:
    defaults_file = validate_defaults_file(defaults_file)
    database = validate_identifier(database, "database name")
    mysql = shutil.which("mysql")
    if mysql is None:
        raise RuntimeError("mysql client is unavailable")
    process = subprocess.run(
        [
            mysql,
            "--defaults-extra-file={}".format(defaults_file),
            "--database={}".format(database),
            "--batch",
            "--raw",
            "--skip-column-names",
            "--execute",
            query,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError("read-only database inventory query failed")
    if not process.stdout:
        return []
    return [line.split("\t") for line in process.stdout.splitlines()]


def state_count_query(table: str, column: str) -> str:
    table = validate_identifier(table, "table name")
    column = validate_identifier(column, "column name")
    return (
        "SELECT COALESCE(CAST(`{column}` AS CHAR), '<NULL>'), COUNT(*) "
        "FROM `{table}` GROUP BY `{column}` ORDER BY 1"
    ).format(table=table, column=column)


def build_inventory(defaults_file: Path, database: str) -> Mapping[str, Any]:
    tables = mysql_query(defaults_file, database, TABLE_QUERY)
    relationships = mysql_query(defaults_file, database, RELATIONSHIP_QUERY)
    columns = mysql_query(defaults_file, database, COLUMN_QUERY)

    state_counts: Dict[str, Mapping[str, int]] = {}
    for table, column, _data_type, _nullable in columns:
        if column.lower() not in STATE_COLUMNS:
            continue
        rows = mysql_query(defaults_file, database, state_count_query(table, column))
        state_counts["{}.{}".format(table, column)] = {
            value: int(count) for value, count in rows
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "database": database,
        "tables": [
            {"name": table, "estimated_rows": None if rows == "NULL" else int(rows)}
            for table, rows in tables
        ],
        "columns": [
            {
                "table": table,
                "name": column,
                "data_type": data_type,
                "nullable": nullable == "YES",
            }
            for table, column, data_type, nullable in columns
        ],
        "relationships": [
            {
                "table": table,
                "column": column,
                "referenced_table": referenced_table,
                "referenced_column": referenced_column,
            }
            for table, column, referenced_table, referenced_column in relationships
        ],
        "state_counts": state_counts,
    }


def render_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql-defaults-file", required=True, type=Path)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        payload = build_inventory(args.mysql_defaults_file, args.database)
        args.output.write_text(render_json(payload), encoding="utf-8")
    except (OSError, RuntimeError, ValueError) as error:
        print("database fixture inventory failed: {}".format(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
