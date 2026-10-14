#!/usr/bin/env python3
"""Monitor OSG attempts and mark those with all expected output files as complete."""

# Originally written by Thomas Britton, March 2017.

import os
import pwd
import random
import shlex
import socket
import subprocess
import sys
import time
from multiprocessing import Process
from pathlib import Path
from typing import Any, List, Mapping, Sequence, TypeVar

import MySQLdb
from mc_status import DATA_UNVERIFIED, AttemptStatus, ExitCode, ProjectStatus

HOST_NAME = str(socket.gethostname())
DB_HOST = "hallddb.jlab.org"
DB_USER = "mcuser"
DB_NAME = "gluex_mc"
ALLOWED_USERS = ("tbritton", "mcwrap")
WORKER_COUNT = 10
PELICAN_SERVER = "osdf://jlab-osdf/gluex/osgpool/REQUESTEDMC_OUTPUT/"
REMOTE_OUTPUT_ROOTS = (
    "/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/",
    "/mss/halld/gluex_simulations/REQUESTED_MC/",
    "/work/halld/gluex_simulations/REQUESTED_MC/",
)

try:
    database_connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
    database_cursor = database_connection.cursor(MySQLdb.cursors.DictCursor)
except BaseException:
    print(
        "WARNING: CANNOT CONNECT TO DATABASE.  JOBS WILL NOT BE CONTROLLED OR MONITORED"
    )

runner_name = pwd.getpwuid(os.getuid())[0]
if runner_name not in ALLOWED_USERS:
    print("ERROR: You must be tbritton or mcwrap to run this script")
    sys.exit(1)

Item = TypeVar("Item")


def remote_file_exists(host: str, path: str) -> bool:
    """Return whether the remote file check succeeds over SSH."""
    status = subprocess.call(["ssh", host, f"test -f {shlex.quote(path)}"])
    if status == 0:
        return True
    if status == 1:
        return False
    raise Exception("SSH failed")


class OutputFileLocator:
    """Check expected output files through Pelican, local storage, and SSH."""

    def __init__(self, user_name: str) -> None:
        self._user_name = user_name

    def exists(self, root_location: str, expected_file: str) -> bool:
        """Check file existence in configured storage locations, in search order."""
        subdirectory = "hddm"
        if expected_file.split(".")[-1] == "root":
            subdirectory = "root/monitoring_hists"

        os.environ["BEARER_TOKEN_FILE"] = "/var/run/user/10967/bt_u10967"
        os.environ["XDG_RUNTIME_DIR"] = "/run/user/10967"
        token_setup = "eval `ssh-agent`; /usr/bin/ssh-add;"
        agent_cleanup = "; ssh-agent -k"
        relative_path = f"{root_location}/{subdirectory}/{expected_file}"
        file_check = f"pelican object ls {PELICAN_SERVER}{relative_path}"
        command = f"{token_setup}{file_check}{agent_cleanup}"
        print(command)
        environment = os.environ.copy()
        process = subprocess.Popen(
            command,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=-1,
            shell=True,
            close_fds=True,
        )
        output, errors = process.communicate()
        print("check for file:", file_check)
        pelican_found = f"Failure getting {PELICAN_SERVER}" not in errors.decode(
            "utf-8"
        ) and expected_file in output.decode("utf-8")
        if pelican_found:
            print("FILE FOUND VIA PELICAN")

        local_path = (
            Path("/osgpool/halld")
            / self._user_name
            / "REQUESTEDMC_OUTPUT"
            / relative_path.lstrip("/")
        )
        found = (
            local_path.is_file()
            or any(
                remote_file_exists(
                    f"{self._user_name}@dtn1902", f"{root}{relative_path}"
                )
                for root in REMOTE_OUTPUT_ROOTS
            )
            or pelican_found
        )
        if not found:
            print(f"{relative_path}   NOT FOUND")
        print("File found?", found)
        return found


def expected_output_files(
    job: Mapping[str, Any], project: Mapping[str, Any]
) -> List[str]:
    """Build output filenames from the job and project save flags."""
    standard_name = (
        f"{str(job['RunNumber']).zfill(6)}_{str(job['FileNumber']).zfill(3)}"
    )
    if project["Generator"] != "file:":
        standard_name = f"{project['Generator']}_{standard_name}"
    postprocessor_suffix = ""
    if project["GenPostProcessing"] is not None and project["GenPostProcessing"] != "":
        print("Postprocessing:", project["GenPostProcessing"])
        postprocessor_suffix = f"_{project['GenPostProcessing'].split(':')[0]}"

    files = []
    if (
        str(project["RunGeneration"]) == "1"
        and str(project["SaveGeneration"]) == "1"
        and str(project["Generator"]) != "particle_gun"
    ):
        files.append(f"{standard_name}{postprocessor_suffix}.hddm")
    if str(project["RunGeant"]) == "1" and str(project["SaveGeant"]) == "1":
        files.append(
            f"{standard_name}_geant{project['GeantVersion']}{postprocessor_suffix}.hddm"
        )
    if str(project["RunSmear"]) == "1" and str(project["SaveSmear"]) == "1":
        files.append(
            f"{standard_name}_geant{project['GeantVersion']}"
            f"_smeared{postprocessor_suffix}.hddm"
        )
    if (
        str(project["RunReconstruction"]) == "1"
        and str(project["SaveReconstruction"]) == "1"
    ):
        files.append(f"dana_rest_{standard_name}{postprocessor_suffix}.hddm")
        files.append(f"hd_root_{standard_name}{postprocessor_suffix}.root")
    return files


class JobCompletionChecker:
    """Check job outputs and commit completed-attempt status updates."""

    def __init__(
        self, lookup_cursor: "MySQLdb.cursors.DictCursor", user_name: str
    ) -> None:
        self._lookup_cursor = lookup_cursor
        self._user_name = user_name
        self._file_locator = OutputFileLocator(user_name)

    def check(self, assignments: Sequence[Mapping[str, Any]]) -> None:
        """Look up attempts and update status in separate database sessions."""
        connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
        update_cursor = connection.cursor(MySQLdb.cursors.DictCursor)
        output_root = Path("/osgpool/halld") / self._user_name / "REQUESTEDMC_OUTPUT"
        print(f"checking {len(assignments)}")
        for attempt in assignments:
            self._lookup_cursor.execute(
                f"SELECT * from Jobs where ID = {attempt['Job_ID']}"
            )
            job = self._lookup_cursor.fetchall()[0]
            self._lookup_cursor.execute(
                f"SELECT * From Project Where ID = {job['Project_ID']}"
            )
            project = self._lookup_cursor.fetchall()[0]
            location = project["OutputLocation"]
            output_path = (
                Path(location) if location.endswith("/") else Path(location).parent
            )
            for _root, directories, _files in os.walk(output_root / output_path.name):
                directories[:] = [
                    directory for directory in directories if directory[0] != "."
                ]
            if project["Tested"] in (
                ProjectStatus.STOPPED,
                ProjectStatus.CANCEL_REQUESTED,
            ):
                continue
            root_location = project["OutputLocation"].split("REQUESTED_MC")[1]
            if job["DataVerified"] != DATA_UNVERIFIED:
                continue
            files = expected_output_files(job, project)
            all_files_found = all(
                self._file_locator.exists(root_location, file_name)
                for file_name in files
            )
            if all_files_found:
                query = (
                    f"UPDATE Attempts Set Status = {AttemptStatus.OUTPUTS_FOUND}, "
                    f"ExitCode = {ExitCode.SUCCESS} "
                    f"where ID = {attempt['ID']}"
                )
                print(query)
                update_cursor.execute(query)
                connection.commit()


def check_job_files_for_completion(assignments: Sequence[Mapping[str, Any]]) -> None:
    """Module-level multiprocessing entry point for completion checks."""
    JobCompletionChecker(database_cursor, runner_name).check(assignments)


def split_round_robin(items: Sequence[Item], parts: int) -> List[List[Item]]:
    """Distribute items across worker assignments in round-robin order."""
    assignments: List[List[Item]] = [[] for _ in range(parts)]
    for index, item in enumerate(items):
        assignments[index % parts].append(item)
    return assignments


class JobObserver:
    """Fetch eligible attempts and schedule their completion-check workers."""

    def __init__(self, cursor: "MySQLdb.cursors.DictCursor", host_name: str) -> None:
        self._cursor = cursor
        self._host_name = host_name

    def run(self) -> None:
        """Monitor repeatedly; print exceptions and stop when an iteration fails."""
        while True:
            try:
                self._monitor_once()
            except Exception as error:
                print(error)
                break

    def _monitor_once(self) -> None:
        query = (
            "SELECT * from Attempts WHERE BatchSystem = 'OSG' "
            f'&& SubmitHost = "{self._host_name}" '
            f"&& Status != '{AttemptStatus.COMPLETED}' "
            f"&& Status != '{AttemptStatus.REMOVED}' "
            f"&& Status != '{AttemptStatus.INACTIVE}' "
            f"&& Status != '{AttemptStatus.HELD}' "
            f"&& Status != '{AttemptStatus.OUTPUTS_FOUND}';"
        )
        self._cursor.execute(query)
        jobs = list(self._cursor.fetchall())
        random.shuffle(jobs)
        assignments = split_round_robin(jobs, WORKER_COUNT)
        workers = []
        for index, assignment in enumerate(assignments):
            time.sleep(random.randint(1, WORKER_COUNT))
            print(f"block {index}")
            print(len(assignment))
            if assignment:
                worker = Process(
                    target=check_job_files_for_completion, args=(assignment,)
                )
                worker.daemon = True
                workers.append(worker)
        for worker in workers:
            time.sleep(random.randint(1, WORKER_COUNT))
            worker.start()
        for worker in workers:
            if worker.is_alive():
                worker.join()


def _count_running_observers(user_name: str) -> int:
    """Count observer processes owned by the supplied user."""
    command = (
        f"echo `ps all -u {user_name} | grep MCObserver.py | grep -v grep | wc -l`"
    )
    return int(subprocess.check_output([command], shell=True))


def main(argv: Sequence[str]) -> None:
    """Observe attempts when permitted; any argument overrides the process limit."""
    override_process_limit = bool(argv)
    process_count = _count_running_observers(runner_name)
    print(process_count)
    if process_count < 2 or override_process_limit:
        JobObserver(database_cursor, HOST_NAME).run()
    database_connection.close()


if __name__ == "__main__":
    main(sys.argv[1:])
