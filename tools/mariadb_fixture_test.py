#!/usr/bin/env python3
"""Load a verified fixture into one isolated, disposable MariaDB container."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time
from typing import Any, Mapping, Optional, Sequence
import uuid

from tools.fixture_archive import TABLE_ORDER, validate_archive


DATABASE = "mcwrapper_fixture_test"
CONTAINER_PREFIX = "mcwrapper-fixture-test-"
ROOT_PASSWORD = "fixture-only-password"
_isolated_popen = subprocess.Popen


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    encoded = str(value).encode("utf-8").hex()
    return "CONVERT(0x{} USING utf8mb4)".format(encoded)


def load_sql(archive: Path) -> str:
    validate_archive(archive)
    with tarfile.open(str(archive), "r:gz") as stream:
        schema = stream.extractfile("schema.sql").read().decode("utf-8")
        statements = [
            "CREATE DATABASE `{}`;".format(DATABASE),
            "USE `{}`;".format(DATABASE),
            schema,
        ]
        for table in TABLE_ORDER:
            member = stream.extractfile("tables/{}.jsonl".format(table))
            for line in member:
                row = json.loads(line)
                columns = ", ".join("`{}`".format(column) for column in row)
                values = ", ".join(sql_literal(value) for value in row.values())
                statements.append(
                    "INSERT INTO `{}` ({}) VALUES ({});".format(
                        table, columns, values
                    )
                )
        return "\n".join(statements) + "\n"


def _docker(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
    command = ["docker"] + list(argv)
    input_text = kwargs.pop("input", None)
    process = _isolated_popen(
        command,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **kwargs
    )
    stdout, stderr = process.communicate(input_text)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def run_mariadb_archive(archive: Path, image: str = "mariadb:11") -> Mapping[str, int]:
    manifest = validate_archive(archive)
    name = CONTAINER_PREFIX + uuid.uuid4().hex[:12]
    started = False
    try:
        process = _docker(
            [
                "run",
                "--detach",
                "--rm",
                "--name",
                name,
                "--network",
                "none",
                "--env",
                "MARIADB_ROOT_PASSWORD={}".format(ROOT_PASSWORD),
                image,
            ]
        )
        if process.returncode != 0:
            raise RuntimeError("failed to start disposable MariaDB container")
        started = True
        for _attempt in range(60):
            ready = _docker(
                [
                    "exec",
                    name,
                    "mariadb",
                    "-uroot",
                    "-p{}".format(ROOT_PASSWORD),
                    "--execute",
                    "SELECT 1",
                ]
            )
            if ready.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("disposable MariaDB did not become ready")

        loaded = _docker(
            ["exec", "-i", name, "mariadb", "-uroot", "-p{}".format(ROOT_PASSWORD)],
            input=load_sql(archive),
        )
        if loaded.returncode != 0:
            diagnostic = loaded.stderr.strip().splitlines()[-1:] or ["unknown error"]
            raise RuntimeError(
                "fixture failed to load into disposable MariaDB: {}".format(
                    diagnostic[0]
                )
            )

        counts = {}
        for table in TABLE_ORDER:
            query = "SELECT COUNT(*) FROM `{}`.`{}`;".format(DATABASE, table)
            result = _docker(
                [
                    "exec",
                    name,
                    "mariadb",
                    "-uroot",
                    "-p{}".format(ROOT_PASSWORD),
                    "--batch",
                    "--skip-column-names",
                    "--execute",
                    query,
                ]
            )
            if result.returncode != 0:
                raise RuntimeError("fixture row-count query failed")
            counts[table] = int(result.stdout.strip())
        expected = {
            table: metadata["rows"] for table, metadata in manifest["tables"].items()
        }
        if counts != expected:
            raise RuntimeError("loaded row counts differ from fixture manifest")
        return counts
    finally:
        if started:
            _docker(["rm", "--force", name])


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--image", default="mariadb:11")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        counts = run_mariadb_archive(args.archive, args.image)
    except (OSError, RuntimeError, ValueError) as error:
        print("MariaDB fixture test failed: {}".format(error), file=sys.stderr)
        return 2
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
