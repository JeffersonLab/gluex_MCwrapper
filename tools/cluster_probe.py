#!/usr/bin/env python3
"""Collect a redacted, read-only snapshot of an MCwrapper cluster host."""

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence


SCHEMA_VERSION = 1
PACKAGE_NAMES = (
    "mysqlclient",
    "rcdb",
    "ccdb",
    "hddm",
    "numpy",
    "pandas",
    "polars",
)
SCHEDULER_EXECUTABLES = (
    "condor_submit",
    "jsub",
    "sbatch",
    "squeue",
    "swif",
    "swif2",
)
ACCESS_PATHS = (
    "/cvmfs",
    "/group/halld",
    "/mss/halld",
    "/osgpool/halld",
    "/scratch/mcwrap",
    "/scigroup/mcwrapper",
    "/work/osgpool/halld",
)
RELEVANT_ENVIRONMENT_NAMES = (
    "BEARER_TOKEN_FILE",
    "BUILD_SCRIPTS",
    "CCDB_CONNECTION",
    "HALLD_VERSIONS",
    "HD_UTILITIES_HOME",
    "JANA_CALIB_CONTEXT",
    "JANA_CALIB_URL",
    "JANA_GEOMETRY_URL",
    "MCWRAPPER_CENTRAL",
    "RANDOMS_OSDF",
    "RCDB_CONNECTION",
    "SINGULARITY_BIND",
    "SINGULARITY_NAME",
    "XDG_RUNTIME_DIR",
    "XRD_RANDOMS_URL",
)


def validate_defaults_file(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    mode = stat.S_IMODE(resolved.stat().st_mode)
    if mode != 0o600:
        raise ValueError("MySQL defaults file must have mode 0600")
    if not resolved.is_file():
        raise ValueError("MySQL defaults path must be a regular file")
    return resolved


def package_versions(names: Iterable[str]) -> Dict[str, Optional[str]]:
    versions = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def executable_capabilities(names: Iterable[str]) -> Dict[str, bool]:
    return {name: shutil.which(name) is not None for name in names}


def path_capabilities(paths: Iterable[str]) -> Dict[str, Mapping[str, bool]]:
    return {
        path: {
            "exists": os.path.exists(path),
            "readable": os.access(path, os.R_OK),
            "writable": os.access(path, os.W_OK),
        }
        for path in paths
    }


def sql_mode(defaults_file: Optional[Path]) -> Optional[str]:
    if defaults_file is None:
        return None
    defaults_file = validate_defaults_file(defaults_file)
    mysql = shutil.which("mysql")
    if mysql is None:
        raise RuntimeError("mysql client is unavailable")
    process = subprocess.run(
        [
            mysql,
            "--defaults-extra-file={}".format(defaults_file),
            "--batch",
            "--skip-column-names",
            "--execute",
            "SELECT @@SESSION.sql_mode",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError("read-only SQL-mode probe failed")
    return process.stdout.strip()


def collect_probe(
    environment: Mapping[str, str] = os.environ,
    defaults_file: Optional[Path] = None,
) -> Mapping[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "platform": {
            "machine": platform.machine(),
            "system": platform.system(),
            "release": platform.release(),
        },
        "packages": package_versions(PACKAGE_NAMES),
        "scheduler_executables": executable_capabilities(SCHEDULER_EXECUTABLES),
        "mysql_client_available": shutil.which("mysql") is not None,
        "sql_mode": sql_mode(defaults_file),
        "paths": path_capabilities(ACCESS_PATHS),
        "environment_names": sorted(
            name for name in RELEVANT_ENVIRONMENT_NAMES if name in environment
        ),
    }


def render_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mysql-defaults-file",
        type=Path,
        help="optional mode-0600 defaults file used only for SELECT @@SESSION.sql_mode",
    )
    parser.add_argument("--output", type=Path, help="write JSON to this file")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        output = render_json(collect_probe(defaults_file=args.mysql_defaults_file))
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
    except (OSError, RuntimeError, ValueError) as error:
        print("cluster probe failed: {}".format(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
