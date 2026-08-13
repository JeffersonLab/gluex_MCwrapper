"""Shared format and validation helpers for sanitized database fixtures."""

import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
from typing import Any, Dict, Iterable, List, Mapping, Sequence


ARCHIVE_SCHEMA_VERSION = 1
TABLE_ORDER = ("Users", "Project", "Jobs", "Attempts", "Generator_perfiles")
FOREIGN_KEYS = (
    ("Project", "user_id", "Users", "ID"),
    ("Jobs", "Project_ID", "Project", "ID"),
    ("Attempts", "Job_ID", "Jobs", "ID"),
)
FORBIDDEN_PATTERNS = (
    ("credential marker", re.compile(r"(?i)\b(?:password|passwd|secret|credential)\b\s*[:=]")),
    ("database URL", re.compile(r"(?i)\b(?:mysql|mariadb)://")),
    ("JLab hostname", re.compile(r"(?i)\b[\w.-]*jlab\.org\b")),
    (
        "production path",
        re.compile(r"(?i)(?:/osgpool/|/work/osgpool/|/lustre\d*/|/mss/|/u/group/|/home/[^/]+/)"),
    ),
)
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


class FixtureValidationError(ValueError):
    pass


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def json_lines(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_archive(
    output: Path,
    schema_sql: str,
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    selections: Mapping[str, Sequence[int]],
) -> None:
    members: Dict[str, bytes] = {"schema.sql": schema_sql.encode("utf-8")}
    for table in TABLE_ORDER:
        members["tables/{}.jsonl".format(table)] = json_lines(tables.get(table, ()))
    manifest = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "tables": {
            table: {
                "rows": len(tables.get(table, ())),
                "sha256": sha256(members["tables/{}.jsonl".format(table)]),
            }
            for table in TABLE_ORDER
        },
        "schema_sha256": sha256(members["schema.sql"]),
        "selections": {name: list(ids) for name, ids in sorted(selections.items())},
    }
    members["manifest.json"] = canonical_json(manifest)

    with tarfile.open(str(output), "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for name in sorted(members):
            data = members[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o600
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))


def _read_members(path: Path) -> Mapping[str, bytes]:
    expected = {"manifest.json", "schema.sql"}.union(
        "tables/{}.jsonl".format(table) for table in TABLE_ORDER
    )
    with tarfile.open(str(path), "r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        if names != expected:
            raise FixtureValidationError(
                "archive members differ from the required fixture format"
            )
        if any(not member.isfile() or member.name.startswith("/") or ".." in Path(member.name).parts for member in members):
            raise FixtureValidationError("archive contains an unsafe member")
        return {
            member.name: archive.extractfile(member).read()  # type: ignore[union-attr]
            for member in members
        }


def _scan_text(name: str, text: str) -> None:
    for description, pattern in FORBIDDEN_PATTERNS:
        if pattern.search(text):
            raise FixtureValidationError("{} contains {}".format(name, description))
    for email in EMAIL.findall(text):
        if not email.lower().endswith("@example.invalid"):
            raise FixtureValidationError("{} contains a real email domain".format(name))


def validate_archive(path: Path) -> Mapping[str, Any]:
    members = _read_members(path)
    for name, data in members.items():
        try:
            _scan_text(name, data.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise FixtureValidationError("{} is not UTF-8".format(name)) from error

    manifest = json.loads(members["manifest.json"])
    if manifest.get("schema_version") != ARCHIVE_SCHEMA_VERSION:
        raise FixtureValidationError("unsupported fixture schema version")
    if set(manifest.get("tables", {})) != set(TABLE_ORDER):
        raise FixtureValidationError("manifest contains unexpected tables")
    if sha256(members["schema.sql"]) != manifest.get("schema_sha256"):
        raise FixtureValidationError("schema hash mismatch")

    rows_by_table: Dict[str, List[Mapping[str, Any]]] = {}
    for table in TABLE_ORDER:
        name = "tables/{}.jsonl".format(table)
        data = members[name]
        metadata = manifest["tables"][table]
        if sha256(data) != metadata.get("sha256"):
            raise FixtureValidationError("{} hash mismatch".format(table))
        try:
            rows = [json.loads(line) for line in data.splitlines()]
        except json.JSONDecodeError as error:
            raise FixtureValidationError("{} contains invalid JSON Lines".format(table)) from error
        if len(rows) != metadata.get("rows"):
            raise FixtureValidationError("{} row count mismatch".format(table))
        ids = [row.get("ID") for row in rows]
        if len(ids) != len(set(ids)):
            raise FixtureValidationError("{} has duplicate primary keys".format(table))
        rows_by_table[table] = rows

    for child, child_column, parent, parent_column in FOREIGN_KEYS:
        parent_values = {row.get(parent_column) for row in rows_by_table[parent]}
        for row in rows_by_table[child]:
            value = row.get(child_column)
            if value is not None and value not in parent_values:
                raise FixtureValidationError(
                    "broken foreign key {}.{} -> {}.{}".format(
                        child, child_column, parent, parent_column
                    )
                )
    return manifest
