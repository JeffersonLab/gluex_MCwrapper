#!/usr/bin/env python3
"""Run the MC transfer script with process guards and database status tracking."""

# Originally written by Thomas Britton, March 2017.

import socket
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import MySQLdb
from mc_status import RunStatus

DB_HOST = "hallddb.jlab.org"
DB_USER = "mcuser"
DB_NAME = "gluex_mc"
MCWRAPPER_BOT_HOME = "/scigroup/mcwrapper/gluex_MCwrapper/"
MOVER_SCRIPT = Path(MCWRAPPER_BOT_HOME) / "Utilities" / "MCMover.csh"
ALLSTOP_FILE = Path("/osgpool/halld/tbritton") / ".ALLSTOP"
PROCESS_COUNT_COMMAND = (
    "echo `ps all -u tbritton | grep MCMover.py | grep -v grep | wc -l`"
)

try:
    database_connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
    database_cursor = database_connection.cursor(MySQLdb.cursors.DictCursor)
except BaseException:
    print(
        "WARNING: CANNOT CONNECT TO DATABASE.  JOBS WILL NOT BE CONTROLLED OR MONITORED"
    )


def run_transfer_script() -> None:
    """Run the transfer script and print its captured output."""
    print(MOVER_SCRIPT)
    output = subprocess.check_output([str(MOVER_SCRIPT)], shell=True)
    print(output)


class MoverRun:
    """Record a transfer run and its outcome using the supplied database session."""

    def __init__(
        self,
        connection: "MySQLdb.connections.Connection",
        cursor: "MySQLdb.cursors.DictCursor",
    ) -> None:
        self._connection = connection
        self._cursor = cursor

    def run(self) -> None:
        """Record the start, run the transfer, and record success or failure."""
        self._cursor.execute(
            "INSERT INTO MCMover (Host, StartTime, Status) "
            f"VALUES ('{socket.gethostname()}', NOW(), '{RunStatus.RUNNING}')"
        )
        self._connection.commit()
        self._cursor.execute("SELECT MAX(ID) FROM MCMover;")
        run_rows = self._cursor.fetchall()

        try:
            run_transfer_script()
            self._record_outcome(run_rows[0]["MAX(ID)"], succeeded=True)
        except BaseException:
            # Record failures caused by exceptions, including process interruptions.
            self._record_outcome(run_rows[0]["MAX(ID)"], succeeded=False)

    def _record_outcome(self, run_id: int, succeeded: bool) -> None:
        """Update the run status, setting EndTime only for successful transfers."""
        status = RunStatus.SUCCESS if succeeded else RunStatus.FAIL
        end_time_assignment = "EndTime = NOW(), " if succeeded else ""
        self._cursor.execute(
            f"UPDATE MCMover SET {end_time_assignment}Status = '{status}' "
            f"where ID = {run_id}"
        )
        self._connection.commit()


def _count_running_movers() -> int:
    """Count mover processes owned by tbritton."""
    output = subprocess.check_output([PROCESS_COUNT_COMMAND], shell=True)
    return int(output)


def main(argv: Sequence[str]) -> None:
    """Run when allowed; any argument overrides only the process-count limit."""
    override_process_limit = bool(argv)
    process_count = _count_running_movers()
    print(process_count)

    stop_requested = ALLSTOP_FILE.is_file()
    if stop_requested:
        print("ALL STOP DETECTED")

    if (process_count < 2 or override_process_limit) and not stop_requested:
        MoverRun(database_connection, database_cursor).run()

    database_connection.close()


if __name__ == "__main__":
    main(sys.argv[1:])
