#!/usr/bin/env python3
"""Launch the MC dispatcher with account checks and database status tracking."""

# Originally written by Thomas Britton, March 2017.

import os
import pwd
import socket
import subprocess
import sys
from typing import Sequence

import MySQLdb

DB_HOST = "hallddb.jlab.org"
DB_USER = "mcuser"
DB_NAME = "gluex_mc"
ALLOWED_USERS = ("tbritton", "mcwrap")

runner_name = pwd.getpwuid(os.getuid())[0]
if runner_name not in ALLOWED_USERS:
    print("ERROR: You must be tbritton or mcwrap to run this script")
    sys.exit(1)

try:
    database_connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
    database_cursor = database_connection.cursor(MySQLdb.cursors.DictCursor)
except BaseException:
    print(
        "WARNING: CANNOT CONNECT TO DATABASE.  JOBS WILL NOT BE CONTROLLED OR MONITORED"
    )


class DroneRun:
    """Record a dispatcher run and its outcome using an existing database session."""

    def __init__(
        self,
        connection: "MySQLdb.connections.Connection",
        cursor: "MySQLdb.cursors.DictCursor",
    ) -> None:
        self._connection = connection
        self._cursor = cursor

    def run(self) -> None:
        """Record the start, launch the dispatcher, and record its outcome."""
        self._cursor.execute(
            "INSERT INTO MCDrone (Host,StartTime,Status) "
            f"VALUES ('{socket.gethostname()}', NOW(), 'Running' )"
        )
        self._connection.commit()
        self._cursor.execute("SELECT MAX(ID) FROM MCDrone;")
        run_rows = self._cursor.fetchall()

        try:
            print("TRYING")
            self._run_dispatcher(run_rows[0]["MAX(ID)"])
            self._record_outcome(run_rows[0]["MAX(ID)"], succeeded=True)
        except Exception as error:
            print(error)
            self._record_outcome(run_rows[0]["MAX(ID)"], succeeded=False)

    def _run_dispatcher(self, run_id: int) -> None:
        """Launch autolaunch mode and print its captured standard output."""
        try:
            command = (
                os.environ["MCWRAPPER_CENTRAL"]
                + "/Utilities/MCDispatcher.py autolaunch"
            )
            print(command)
            output, _stderr = subprocess.Popen(
                command.split(" "),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ,
            ).communicate()
            print(output)
        except subprocess.CalledProcessError:
            self._record_outcome(run_id, succeeded=False)
            sys.exit(1)

    def _record_outcome(self, run_id: int, succeeded: bool) -> None:
        """Update the run status, setting EndTime only for successful dispatches."""
        status = "Success" if succeeded else "Fail"
        end_time_assignment = "EndTime=NOW(), " if succeeded else ""
        self._cursor.execute(
            f"UPDATE MCDrone SET {end_time_assignment}Status='{status}' "
            f"where ID={run_id}"
        )
        self._connection.commit()


def _count_running_drones(user_name: str) -> int:
    """Count drone processes for the user using the existing shell command."""
    command = f"echo `ps all -u {user_name} | grep MCDrone.py | grep -v grep | wc -l`"
    output = subprocess.check_output([command], shell=True).strip()
    return int(output)


def main(argv: Sequence[str]) -> None:
    """Run when allowed; any argument overrides only the process-count limit."""
    override_process_limit = bool(argv)
    process_count = _count_running_drones(runner_name)
    print(process_count)

    stop_requested = os.path.isfile(f"/osgpool/halld/{runner_name}/.ALLSTOP")
    if stop_requested:
        print("ALL STOP DETECTED")

    print("number of running processes", process_count)
    if (process_count < 2 or override_process_limit) and not stop_requested:
        print("RUNNING")
        DroneRun(database_connection, database_cursor).run()
        database_connection.close()


if __name__ == "__main__":
    main(sys.argv[1:])
