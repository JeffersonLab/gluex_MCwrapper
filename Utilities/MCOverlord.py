#!/usr/bin/env python3
"""Monitor scheduler attempts and finalize MC projects after output verification.

Written by Thomas Britton, 2017.
"""

import json
import os
import pwd
import random
import shlex
import shutil
import smtplib
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from multiprocessing import Process
from pathlib import Path, PurePosixPath
from subprocess import PIPE, Popen
from typing import Any, List, Mapping, Optional, Sequence, Union

import MySQLdb
from mc_status import (
    DATA_UNVERIFIED,
    DATA_VERIFIED,
    JOB_ACTIVE,
    JOB_INACTIVE,
    PROJECT_NOTIFIED,
    AttemptStatus,
    ExitCode,
    ProjectStatus,
    RunStatus,
)

HOST_NAME = socket.gethostname()
DB_HOST = "hallddb.jlab.org"
DB_USER = "mcuser"
DB_NAME = "gluex_mc"
ALLOWED_USERS = ("tbritton", "mcwrap")
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


def _duration_text(duration: timedelta) -> str:
    """Format the duration's seconds component as HH:MM:SS."""
    return time.strftime("%H:%M:%S", time.gmtime(duration.seconds))


def _milliseconds_timestamp(value: Union[int, float, str]) -> datetime:
    """Convert scheduler milliseconds since the Unix epoch to local time."""
    return datetime.fromtimestamp(float(value) / 1000.0)


def _random_trigger_path(background: str, run_number: Union[int, str]) -> Path:
    """Build the local staging path for a run's random-trigger input."""
    return (
        Path("/work/osgpool/halld/random_triggers")
        / background.lstrip("/")
        / f"run{str(run_number).zfill(6)}_random.hddm"
    )


def remote_file_exists(host: str, path: str) -> bool:
    """Test whether a remote file exists; raise an exception for SSH failures."""
    status = subprocess.call(["ssh", host, f"test -f {shlex.quote(path)}"])
    if status == 0:
        return True
    if status == 1:
        return False
    raise Exception("SSH failed")


class OutputFileLocator:
    """Find project outputs through Pelican and local staging paths."""

    def __init__(self, user_name: str) -> None:
        self._user_name = user_name

    def find(self, root_location: str, expected_file: str) -> bool:
        """Check an expected filename in Pelican and local staging storage."""
        found = False
        root_location = Path(root_location).name
        if not root_location:
            raise IndexError("list index out of range")
        subloc = "hddm"
        parse_exp_file = expected_file.split(".")
        if parse_exp_file[len(parse_exp_file) - 1] == "root":
            subloc = "root/monitoring_hists"
        os.environ["BEARER_TOKEN_FILE"] = "/var/run/user/10967/bt_u10967"
        os.environ["XDG_RUNTIME_DIR"] = "/run/user/10967"
        pelican_server = "osdf://jlab-osdf/gluex/osgpool/REQUESTEDMC_OUTPUT/"
        file_check = (
            f"pelican object ls {pelican_server}{root_location}/{subloc}/"
            f"{expected_file}"
        )
        print(file_check)
        my_env = os.environ.copy()
        p = Popen(
            file_check,
            env=my_env,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            bufsize=-1,
            shell=True,
            close_fds=True,
        )
        output, errors = p.communicate()
        print("check for file:", file_check)
        pelican_found = False
        if f"Failure getting {pelican_server}" not in str(
            errors, "utf-8"
        ) and expected_file in str(output, "utf-8"):
            print("FILE FOUND VIA PELICAN")
            pelican_found = True
        local_path = (
            Path("/osgpool/halld")
            / self._user_name
            / "REQUESTEDMC_OUTPUT"
            / root_location
            / subloc
            / expected_file
        )
        if pelican_found or local_path.is_file():
            found = True
        else:
            print(f"{root_location}/{subloc}/{expected_file}   NOT FOUND")
        print("FILE FOUND?", found)
        return found


def remove_empty_directories(root_location: str) -> None:
    """Remove empty directories and recursively remove paths containing .hdds."""
    try:
        root_path = Path(root_location)
        sublocs = list(root_path.iterdir())
    except Exception as e:
        print(e)
        return
    if len(sublocs) > 0:
        for subloc in sublocs:
            if subloc.is_dir():
                remove_empty_directories(str(subloc))
    try:
        if ".hdds" in root_location:
            print("Removing ", root_location)
            shutil.rmtree(root_path)
        else:
            print("Removing ", root_location)
            root_path.rmdir()
    except Exception as e:
        print(e)
        pass


class ProjectCompletionChecker:
    """Verify completed jobs, advance project states, and record notifications."""

    def __init__(self, user_name: str, host_name: str) -> None:
        self._user_name = user_name
        self._host_name = host_name
        self._file_locator = OutputFileLocator(user_name)

    def check(self, projects: Sequence[Mapping[str, Any]]) -> None:
        """Verify outputs and finalize projects after jobs and transfers complete."""
        project_ids = "".join(f"{project['ID']}," for project in projects)
        print("checking ", project_ids, "for completion")
        self._connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
        self._cursor = self._connection.cursor(MySQLdb.cursors.DictCursor)
        output_root = Path("/osgpool/halld") / self._user_name / "REQUESTEDMC_OUTPUT"
        for proj in projects:
            self._check_project(proj, output_root)

    def _check_project(self, proj: Mapping[str, Any], output_root: Path) -> None:
        """Check job outputs, transfer counts, and project completion conditions."""
        location = proj["OutputLocation"]
        project_path = (
            Path(location) if location.endswith("/") else Path(location).parent
        )
        files = []
        dirs = []
        print("WALKING:", project_path.name)
        # The transfer count uses visible files in the final visited directory.
        for _root, dirs, files in os.walk(output_root / project_path.name):
            files = [f for f in files if not f[0] == "."]
            dirs[:] = [d for d in dirs if not d[0] == "."]
        filtered_files = []
        for f in files:
            if ".log" not in f:
                filtered_files.append(f)
        files = filtered_files
        files_to_move = len(files)
        print("Files to move:", files)
        completed_jobs_query = (
            "SELECT * FROM Jobs "
            "INNER JOIN Attempts "
            "ON Attempts.job_id = Jobs.id "
            f"WHERE Project_ID = {proj['ID']!s} "
            f"&& IsActive = {JOB_ACTIVE} "
            f"AND Attempts.ExitCode = {ExitCode.SUCCESS} "
            f"&& (Attempts.Status = '{AttemptStatus.COMPLETED}' "
            "|| Attempts.Status = 'succeeded') "
            "&& Attempts.ExitCode IS NOT NULL "
            "AND Attempts.id = ("
            "SELECT MAX(id) FROM Attempts Attempts2 "
            "WHERE Attempts2.job_id = Jobs.id);"
        )
        self._cursor.execute(completed_jobs_query)
        fulfilled_jobs = self._cursor.fetchall()
        if (
            proj["Tested"] == ProjectStatus.STOPPED
            or proj["Tested"] == ProjectStatus.CANCEL_REQUESTED
        ):
            return
        root_location = proj["OutputLocation"].split("REQUESTED_MC")[1]
        nullify_list = []
        print("CHECKING FILES", proj["ID"])
        for job in fulfilled_jobs:
            if job["DataVerified"] != DATA_UNVERIFIED:
                continue
            standard_name = (
                f"{str(job['RunNumber']).zfill(6)}_{str(job['FileNumber']).zfill(3)}"
            )
            if proj["Generator"] != "file:":
                standard_name = f"{proj['Generator']}_{standard_name}"
            postproc_append = ""
            if (
                proj["GenPostProcessing"] is not None
                and proj["GenPostProcessing"] != ""
            ):
                postproc_append = f"_{proj['GenPostProcessing'].split(':')[0]}"
            expected_returned_files = []
            if (
                str(proj["RunGeneration"]) == "1"
                and str(proj["SaveGeneration"]) == "1"
                and (str(proj["Generator"]) != "particle_gun")
            ):
                expected_returned_files.append(f"{standard_name}{postproc_append}.hddm")
            if str(proj["RunGeant"]) == "1" and str(proj["SaveGeant"]) == "1":
                expected_returned_files.append(
                    f"{standard_name}{postproc_append}_geant"
                    f"{proj['GeantVersion']!s}.hddm"
                )
            if str(proj["RunSmear"]) == "1" and str(proj["SaveSmear"]) == "1":
                expected_returned_files.append(
                    f"{standard_name}{postproc_append}_geant"
                    f"{proj['GeantVersion']!s}_smeared.hddm"
                )
            if (
                str(proj["RunReconstruction"]) == "1"
                and str(proj["SaveReconstruction"]) == "1"
            ):
                expected_returned_files.append(
                    f"dana_rest_{standard_name}{postproc_append}.hddm"
                )
                expected_returned_files.append(
                    f"hd_root_{standard_name}{postproc_append}.root"
                )
            all_outputs_found = True
            files_not_found = []
            for expected_file in expected_returned_files:
                print("checking for", expected_file, "@", root_location)
                found = self._file_locator.find(root_location, expected_file)
                if not found:
                    print(f"{expected_file}   NOT FOUND!!!!")
                    files_not_found.append(expected_file)
                    all_outputs_found = False
                    break
            if not all_outputs_found:
                print("FLAG LAST ATTEMPT AS SPECIAL FAIL 404")
                attempt_query = (
                    "SELECT * FROM Attempts "
                    f'WHERE SubmitHost = "{self._host_name}" '
                    f"&& Job_ID = {job['ID']!s} "
                    "ORDER BY ID DESC;"
                )
                self._cursor.execute(attempt_query)
                attempt_to_update = self._cursor.fetchall()[0]
                update_q = (
                    "UPDATE Attempts "
                    f"SET ExitCode = {ExitCode.OUTPUT_NOT_RETURNED} "
                    f"WHERE ID = {attempt_to_update['ID']!s}"
                )
                print(update_q)
                self._cursor.execute(update_q)
                self._connection.commit()
                failed_prog_string = (
                    f"[{','.join(files_not_found)}]" if files_not_found else ""
                )
                if failed_prog_string != "":
                    flist_update_q = (
                        "UPDATE Attempts "
                        f'SET ProgramFailed = "{failed_prog_string}" '
                        f"WHERE ID = {attempt_to_update['ID']!s}"
                    )
                    print(flist_update_q)
                    self._cursor.execute(flist_update_q)
                    self._connection.commit()
                nullify_list.append(job["ID"])
            else:
                dataverified_update = (
                    f"UPDATE Jobs SET DataVerified = {DATA_VERIFIED} "
                    f"WHERE ID = {job['ID']!s}"
                )
                self._cursor.execute(dataverified_update)
                self._connection.commit()
        active_jobs_query = (
            "SELECT ID FROM Jobs "
            f"WHERE Project_ID = {proj['ID']!s} "
            f"&& IsActive = {JOB_ACTIVE};"
        )
        self._cursor.execute(active_jobs_query)
        all_active_jobs = self._cursor.fetchall()
        print("=====================")
        print("Project ID:", proj["ID"])
        print("Output location:", proj["OutputLocation"])
        print("Jobs Fulfilled:", len(fulfilled_jobs) - len(nullify_list))
        print("Total jobs:", len(all_active_jobs))
        print(f"TO MOVE: {files_to_move!s}")
        print("---------------------")
        if len(all_active_jobs) == 0:
            return
        total_submitted = (
            f"SELECT SUM(NumEvts) FROM Jobs WHERE Project_ID = {proj['ID']!s}"
        )
        self._cursor.execute(total_submitted)
        submitted_events = self._cursor.fetchall()
        print("Number of events submitted:", submitted_events[0]["SUM(NumEvts)"])
        print("Number of events requested:", proj["NumEvents"])
        print(
            "All jobs fulfilled?",
            len(fulfilled_jobs) - len(nullify_list) == len(all_active_jobs),
        )
        print("Are there any jobs?", len(all_active_jobs) != 0)
        print("All files moved?", files_to_move == 0)
        print(
            "Total Project fullfilled?",
            submitted_events[0]["SUM(NumEvts)"]
            >= proj["NumEvents"] - len(all_active_jobs),
        )
        print("=====================")
        if (
            len(fulfilled_jobs) - len(nullify_list) == len(all_active_jobs)
            and len(all_active_jobs) != 0
            and (files_to_move == 0)
            and (
                submitted_events[0]["SUM(NumEvts)"]
                >= proj["NumEvents"] - len(all_active_jobs)
            )
        ):
            print(proj["ID"], "DONE")
            self._connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
            self._cursor = self._connection.cursor(MySQLdb.cursors.DictCursor)
            if (
                proj["Tested"] != ProjectStatus.BUNDLED
                and proj["Tested"] != ProjectStatus.BUNDLING
                and (proj["Tested"] != ProjectStatus.DECLARED_BUNDLING)
                and (proj["Tested"] != ProjectStatus.DECLARED_BUNDLE_PENDING)
                and (proj["Tested"] != ProjectStatus.DECLARED_BUNDLED)
                and (proj["Tested"] != ProjectStatus.BUNDLE_PENDING)
            ):
                update_project_status_tobundle_q = (
                    f"UPDATE Project SET Tested = {ProjectStatus.BUNDLE_PENDING} "
                    f"WHERE ID = {proj['ID']!s};"
                )
                self._cursor.execute(update_project_status_tobundle_q)
                self._connection.commit()
            if proj["Tested"] == ProjectStatus.BUNDLED:
                self._request_scrub(proj["ID"])
                self._connection = MySQLdb.connect(
                    host=DB_HOST, user=DB_USER, db=DB_NAME
                )
                self._cursor = self._connection.cursor(MySQLdb.cursors.DictCursor)
                get_final_complete_time = (
                    "SELECT MAX(Completed_Time) FROM Attempts "
                    "WHERE Job_ID IN ("
                    "SELECT ID FROM Jobs "
                    f"WHERE Project_ID = {proj['ID']!s});"
                )
                print(get_final_complete_time)
                self._cursor.execute(get_final_complete_time)
                final_time_res = self._cursor.fetchall()
                print("Final Time", final_time_res[0]["MAX(Completed_Time)"])
                final_completion_time = final_time_res[0]["MAX(Completed_Time)"]
                project_update = (
                    "UPDATE Project "
                    f"SET Completed_Time = '{final_completion_time!s}', "
                    f"Tested = {ProjectStatus.READY} "
                    f"WHERE ID = {proj['ID']!s};"
                )
                print(project_update)
                self._cursor.execute(project_update)
                self._connection.commit()
                msg = EmailMessage()
                final_location = proj["OutputLocation"].replace(
                    "/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/",
                    "/work/osgpool/halld/REQUESTED_MC/",
                )
                msg.set_content(
                    f"Your Project ID {proj['ID']!s} has been completed.  While "
                    "awaiting copy to tape output may be found here:\n"
                    f"{final_location!s}\n\nAfter successful copy the data may "
                    "be accessed from tape/cache through typical methods."
                )
                msg["Subject"] = f"GlueX MC Request #{proj['ID']!s} Completed"
                msg["From"] = "MCwrapper-bot"
                msg["To"] = str(proj["Email"])
                s = smtplib.SMTP("localhost")
                s.send_message(msg)
                s.quit()
                sql_notified = (
                    f"UPDATE Project SET Notified = {PROJECT_NOTIFIED} "
                    f"WHERE ID = {proj['ID']!s}"
                )
                self._cursor.execute(sql_notified)
                self._connection.commit()
                data_location = output_root / root_location.lstrip("/")
                print("Data Location:", data_location)
                print("Cleaning up empty folders")
                remove_empty_directories(str(data_location))
        else:
            print("NOT DONE")

    @staticmethod
    def _request_scrub(project_id: Union[int, str]) -> None:
        """Upload a scrub marker and remove the local marker after the attempt."""
        marker = Path(str(project_id))
        command = (
            f"pelican object put {marker} "
            f"osdf://jlab-osdf/gluex/osgpool/to_be_scrubbed/{marker}"
        )
        print(command)
        try:
            marker.touch()
        except OSError as error:
            print(error)
        try:
            subprocess.call(command, shell=True)
        except Exception as error:
            print(error)
        finally:
            try:
                marker.unlink()
            except OSError as error:
                print(error)


def check_swif2() -> None:
    """Open a database session for SWIF2 monitoring."""
    dbcnx_swif = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
    dbcnx_swif.cursor(MySQLdb.cursors.DictCursor)


class SwifMonitor:
    """Read SWIF workflow attempts and record scheduler resource and exit data."""

    def __init__(
        self, lookup_cursor: "MySQLdb.cursors.DictCursor", host_name: str
    ) -> None:
        self._lookup_cursor = lookup_cursor
        self._host_name = host_name

    def check(self, workflows: Sequence[Mapping[str, Any]]) -> None:
        """Update database attempts from SWIF workflow status reports."""
        dbcnx_swif = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
        dbcursor_swif = dbcnx_swif.cursor(MySQLdb.cursors.DictCursor)
        all_wk_flows = workflows
        proj_i_ds = []
        for workflow in all_wk_flows:
            location = workflow["OutputLocation"]
            project_path = (
                Path(location) if location.endswith("/") else Path(location).parent
            )
            wkflowname = project_path.name
            proj_id = workflow["ID"]
            proj_i_ds.append(proj_id)
            try:
                statuscommand = (
                    f"/site/bin/swif status -workflow proj{proj_id!s}_"
                    f"{wkflowname!s} -jobs -display json"
                )
                print(statuscommand)
                json_outputstr = subprocess.check_output(statuscommand.split(" "))
            except Exception as e:
                print(e)
                continue
            returned_jobs = json.loads(str(json_outputstr, "utf-8"))
            print(len(returned_jobs))
            for job in returned_jobs["jobs"]:
                check_query = (
                    "SELECT Job_ID, Status, ExitCode FROM Attempts "
                    f"WHERE BatchJobID = {job['id']!s} "
                    f'&& SubmitHost = "{self._host_name}"'
                )
                self._lookup_cursor.execute(check_query)
                recorded_job_status = self._lookup_cursor.fetchall()
                print(recorded_job_status)
                if (
                    recorded_job_status[0]["Status"] == "succeeded"
                    and recorded_job_status[0]["ExitCode"] == 0
                    or recorded_job_status[0]["Status"] == AttemptStatus.INACTIVE
                ):
                    print("continuing")
                    continue
                if int(job["num_attempts"]) == 0:
                    attempt_update = (
                        f'UPDATE Attempts SET Status = "{job["status"]!s}" '
                        f"WHERE BatchJobID = {job['id']!s} "
                        f'&& SubmitHost = "{self._host_name}"'
                    )
                    print(attempt_update)
                    dbcursor_swif.execute(attempt_update)
                    dbcnx_swif.commit()
                else:
                    logged_attempts_query = (
                        "SELECT ID FROM Attempts "
                        f"WHERE BatchJobID = {job['id']!s} "
                        f'&& SubmitHost = "{self._host_name}" '
                        "ORDER BY ID"
                    )
                    dbcursor_swif.execute(logged_attempts_query)
                    logged_attempts = dbcursor_swif.fetchall()
                    attempt_index = 0
                    for attempt in job["attempts"]:
                        wall_time = timedelta(seconds=0)
                        cpu_time = timedelta(seconds=0)
                        start_time = datetime.fromtimestamp(0.0 / float(1000))
                        ram_used = "0"
                        exit_code = ExitCode.SUCCESS
                        if "exitcode" in attempt or job["status"] == "succeeded":
                            if "exitcode" in attempt:
                                exit_code = attempt["exitcode"]
                        else:
                            exit_code = -1
                        if job["status"] == "succeeded":
                            print("SUCCESS")
                        completed_time = "NULL"
                        if (
                            job["status"] == "problem" or job["status"] == "succeeded"
                        ) and "auger_ts_complete" in attempt:
                            completed_time = attempt["auger_ts_complete"]
                        if "auger_wall_sec" in attempt:
                            wall_time = timedelta(seconds=attempt["auger_wall_sec"])
                        if "auger_ts_active" in attempt:
                            start_time = _milliseconds_timestamp(
                                attempt["auger_ts_active"]
                            )
                        if "auger_cpu_sec" in attempt:
                            cpu_time = timedelta(seconds=attempt["auger_cpu_sec"])
                        if "auger_vmem_kb" in attempt:
                            ram_used = str(float(attempt["auger_vmem_kb"]) / 1000.0)
                        if attempt_index == len(logged_attempts):
                            print("FOUND AN ATTEMPT EXTERNALLY CREATED")
                            job_link_query = (
                                "SELECT Job_ID FROM Attempts "
                                f"WHERE BatchJobID = {job['id']!s} "
                                f'&& SubmitHost = "{self._host_name}"'
                            )
                            dbcursor_swif.execute(job_link_query)
                            link_to_job = dbcursor_swif.fetchall()
                            if len(link_to_job) == 0:
                                continue
                            submit_time = 0.0
                            if "auger_ts_submitted" in attempt:
                                submit_time = float(attempt["auger_ts_submitted"])
                            submitted_time = _milliseconds_timestamp(submit_time)
                            requested_ram = float(attempt["ram_bytes"]) / 1000000000.0
                            add_found_attempt = (
                                "INSERT INTO Attempts (Job_ID, Creation_Time, "
                                "BatchSystem, SubmitHost, BatchJobID, "
                                "ThreadsRequested, RAMRequested, Start_Time) "
                                f"VALUES ({link_to_job[0]['Job_ID']}, "
                                f"'{self._host_name}', 'SWIF', {submitted_time}, "
                                f"{attempt['job_id']}, {attempt['cpu_cores']}, "
                                f"'{requested_ram}GB', '{start_time}')"
                            )
                            dbcursor_swif.execute(add_found_attempt)
                            dbcnx_swif.commit()
                            logged_attempts_query = (
                                "SELECT ID FROM Attempts "
                                f"WHERE BatchJobID = {job['id']!s} "
                                f'&& SubmitHost = "{self._host_name}" '
                                "ORDER BY ID"
                            )
                            dbcursor_swif.execute(logged_attempts_query)
                            logged_attempts = dbcursor_swif.fetchall()
                        if "auger_ts_complete" not in attempt:
                            completed_time = "NULL"
                        if "exitcode" not in attempt:
                            exit_code = "NULL"
                        if str(exit_code) == str(ExitCode.BEAM_FLUX_EMPTY):
                            print("Beam properties integral 0 in given energy range")
                            deactivate_job = (
                                f"UPDATE Jobs SET IsActive = {JOB_INACTIVE} "
                                f"WHERE ID = {recorded_job_status[0]['Job_ID']!s};"
                            )
                            dbcursor_swif.execute(deactivate_job)
                            dbcnx_swif.commit()
                        if str(exit_code) == str(
                            ExitCode.RANDOM_TRIGGER_NOT_FOUND
                        ) or str(exit_code) == str(
                            ExitCode.RANDOM_TRIGGER_INITIALIZATION_FAILED
                        ):
                            exit_code = self._check_random_trigger(
                                recorded_job_status[0]["Job_ID"],
                                exit_code,
                                dbcnx_swif,
                                dbcursor_swif,
                            )
                        running_location = "NULL"
                        if "auger_node" in attempt:
                            running_location = attempt["auger_node"]
                        attempt_update = (
                            f'UPDATE Attempts SET Status = "{job["status"]!s}", '
                            f"ExitCode = {exit_code!s}, "
                            f"RunningLocation = '{running_location!s}', "
                            f"WallTime = '{_duration_text(wall_time)}', "
                            f"Start_Time = '{start_time!s}', "
                            f"CPUTime = '{_duration_text(cpu_time)}', "
                            f"RAMUsed = '{ram_used}' "
                            f"WHERE BatchJobID = {job['id']!s} "
                            f"&& ID = {logged_attempts[attempt_index]['ID']!s}"
                        )
                        if completed_time != "NULL":
                            completed_at = _milliseconds_timestamp(
                                attempt["auger_ts_complete"]
                            )
                            attempt_update = (
                                "UPDATE Attempts "
                                f'SET Status = "{job["status"]!s}", '
                                f"ExitCode = {exit_code!s}, "
                                f"Completed_Time = '{completed_at!s}', "
                                f"RunningLocation = '{running_location!s}', "
                                f"WallTime = '{_duration_text(wall_time)}', "
                                f"Start_Time = '{start_time!s}', "
                                f"CPUTime = '{_duration_text(cpu_time)}', "
                                f"RAMUsed = '{ram_used}' "
                                f"WHERE BatchJobID = {job['id']!s} "
                                f"&& ID = {logged_attempts[attempt_index]['ID']!s}"
                            )
                        dbcursor_swif.execute(attempt_update)
                        dbcnx_swif.commit()
                        attempt_index += 1

    def _check_random_trigger(
        self,
        job_id: Union[int, str],
        exit_code: Union[int, str],
        connection: "MySQLdb.connections.Connection",
        cursor: "MySQLdb.cursors.DictCursor",
    ) -> Union[int, str]:
        """Classify a missing random-trigger input and deactivate unsupported runs."""
        print("EXIT CODE 232 DETECTED")
        cursor.execute(f"SELECT RunNumber, Project_ID FROM Jobs WHERE ID = {job_id}")
        jobs = cursor.fetchall()
        if len(jobs) != 1:
            return exit_code
        run_number = jobs[0]["RunNumber"]
        cursor.execute(f"SELECT BKG FROM Project WHERE ID = {jobs[0]['Project_ID']}")
        backgrounds = cursor.fetchall()
        if len(backgrounds) != 1:
            return exit_code
        print(backgrounds)
        background_parts = backgrounds[0]["BKG"].split(":")
        print(len(background_parts))
        if len(background_parts) == 1:
            return exit_code
        random_path = _random_trigger_path(background_parts[1], run_number)
        if random_path.is_file():
            print(f"found file locally: {random_path}")
            return ExitCode.RANDOM_TRIGGER_AVAILABLE
        print("6 job stat")
        cursor.execute(
            f"UPDATE Jobs SET IsActive = {JOB_INACTIVE} WHERE ID = {job_id};"
        )
        connection.commit()
        return exit_code


class ProjectSizeUpdater:
    """Measure project storage through SSH and update reported output sizes."""

    def __init__(
        self,
        connection: "MySQLdb.connections.Connection",
        cursor: "MySQLdb.cursors.DictCursor",
        user_name: str,
    ) -> None:
        self._connection = connection
        self._cursor = cursor
        self._user_name = user_name

    def update(self) -> None:
        """Update sizes for unfinished projects, using configured final destinations."""
        get_untotaled = (
            "SELECT ID FROM Project "
            "WHERE Completed_Time IS NULL "
            "&& Is_Dispatched != '0' "
            f"&& Tested != '{ProjectStatus.DECLARED_COMPLETE}' "
            f"&& Tested != '{ProjectStatus.CANCEL_REQUESTED}' "
            "&& Notified IS NULL;"
        )
        self._cursor.execute(get_untotaled)
        projects = self._cursor.fetchall()
        for pr in projects:
            id = pr["ID"]
            queryget_loc = f"SELECT * FROM Project WHERE ID = {id!s};"
            self._cursor.execute(queryget_loc)
            project = self._cursor.fetchall()
            location = project[0]["OutputLocation"].replace(
                "/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/",
                "/work/osgpool/halld/REQUESTEDMC_OUTPUT/",
            )
            if project[0]["FinalDestination"]:
                location = project[0]["FinalDestination"]
            try:
                statuscommand = (
                    f'ssh {self._user_name}@ifarm2401 du -sh --exclude "..*" '
                    f"--total {location}"
                )
                raw_output_str = subprocess.check_output([statuscommand], shell=True)
                total_out_line = raw_output_str.decode().splitlines()[-1].strip()
                size_str = total_out_line.split()[0]
                update_project_size_out = (
                    f'UPDATE Project SET TotalSizeOut = "{size_str}" WHERE ID = {id!s}'
                )
                print(update_project_size_out)
                self._cursor.execute(update_project_size_out)
                self._connection.commit()
            except BaseException:
                print("passing")
                pass


class OsgMonitor:
    """Monitor Condor queue and history records and classify missing inputs."""

    def __init__(self, user_name: str, host_name: str) -> None:
        self._user_name = user_name
        self._host_name = host_name

    def check(self, jobs: Sequence[Mapping[str, Any]]) -> None:
        """Update assigned attempts from Condor queue or history reports."""
        dbcnx_osg = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
        dbcursor_osg = dbcnx_osg.cursor(MySQLdb.cursors.DictCursor)
        alljobs = jobs
        count = 0
        update_rate = 0.25
        if len(alljobs) == 0:
            return
        for job in alljobs:
            count += 1
            modulo = int(len(jobs) * update_rate)
            if modulo == 0:
                modulo = 10
            if count % modulo == 0:
                print(f"{os.getpid()!s} : {count!s}")
            statuscommand = f"condor_q {job['BatchJobID']!s} -json"
            try:
                json_outputstr = subprocess.check_output(statuscommand.split(" "))
            except Exception as e:
                print("Error:", statuscommand)
                print("Error:", e)
                continue
            if str(json_outputstr, "utf-8") != "":
                self._check_queue_report(job, json_outputstr, dbcnx_osg, dbcursor_osg)
            else:
                self._check_history(job, dbcnx_osg, dbcursor_osg)
        print("FINISHED CHECKING OSG")

    def _check_queue_report(
        self,
        job: Mapping[str, Any],
        json_outputstr: bytes,
        connection: "MySQLdb.connections.Connection",
        cursor: "MySQLdb.cursors.DictCursor",
    ) -> None:
        """Record a Condor queue report and deactivate jobs with missing held inputs."""
        json_jobar = json.loads(str(json_outputstr, "utf-8"))
        if json_jobar == []:
            return
        json_job = json_jobar[0]
        exit_code = "NULL"
        num_starts = str(json_job["NumJobStarts"])
        if json_job["JobStatus"] != AttemptStatus.REMOVED and "ExitCode" in json_job:
            exit_code = str(json_job["ExitCode"])
        if json_job["JobStatus"] == AttemptStatus.RUNNING:
            exit_code = "NULL"
        completed_time = "NULL"
        if (
            json_job["JobStatus"] >= AttemptStatus.REMOVED
            and "JobFinishedHookDone" in json_job
        ):
            completed_time = json_job["JobFinishedHookDone"]
        wall_time = timedelta(seconds=json_job["RemoteWallClockTime"])
        cpu_time = timedelta(seconds=json_job["RemoteUserCpu"])
        start_time = 0
        if "JobStartDate" in json_job:
            start_time = json_job["JobStartDate"]
        ram_used = str(float(json_job["ImageSize_RAW"]) / float(1024))
        trans_in_size = json_job["TransferInputSizeMB"]
        remote_host = "NA"
        if "RemoteHost" in json_job:
            remote_host = str(json_job["RemoteHost"])
        job_status = json_job["JobStatus"]
        if "HoldReasonCode" in json_job:
            json_job["HoldReasonCode"]
        if job_status == AttemptStatus.HELD:
            missing_f = True
            for f in json_job["TransferInput"].split(","):
                if "_random.hddm" in f:
                    print(f)
                    missing_f = Path(f).is_file()
                    print(missing_f)
            if missing_f is False:
                job_status = AttemptStatus.INACTIVE
                deactivate_job = (
                    f"UPDATE Jobs SET IsActive = {JOB_INACTIVE} "
                    f"WHERE ID = {job['Job_ID']!s};"
                )
                cursor.execute(deactivate_job)
                connection.commit()
        run_ip = "NULL"
        if "LastPublicClaimId" in json_job:
            ipstr = str(json_job["LastPublicClaimId"])
            ipstr = ipstr.split("#")[0]
            ipstr = ipstr[1:-1].split(":")[0]
            run_ip = ipstr
        started_at = datetime.fromtimestamp(float(start_time))
        attempt_update = (
            "UPDATE Attempts "
            f'SET NumStarts = {num_starts!s}, Status = "{job_status!s}", '
            f"ExitCode = {exit_code}, "
            f"Start_Time = '{started_at!s}', "
            f"RunningLocation = '{remote_host!s}', "
            f"WallTime = '{_duration_text(wall_time)}', "
            f"CPUTime = '{_duration_text(cpu_time)}', RAMUsed = '{ram_used}', "
            f"Size_In = {trans_in_size!s}, RunIP = '{run_ip!s}' "
            f"WHERE BatchJobID = '{job['BatchJobID']!s}' "
            f'&& SubmitHost = "{self._host_name}"'
        )
        if completed_time != "NULL":
            completed_at = datetime.fromtimestamp(float(completed_time))
            attempt_update = (
                "UPDATE Attempts "
                f'SET NumStarts = {num_starts!s}, Status = "{job_status!s}", '
                f"ExitCode = {exit_code}, "
                f"Completed_Time = '{completed_at!s}', "
                f"Start_Time = '{started_at!s}', "
                f"RunningLocation = '{remote_host!s}', "
                f"WallTime = '{_duration_text(wall_time)}', "
                f"CPUTime = '{_duration_text(cpu_time)}', RAMUsed = '{ram_used}', "
                f"Size_In = {trans_in_size!s}, RunIP = '{run_ip!s}' "
                f"WHERE BatchJobID = '{job['BatchJobID']!s}' "
                f'&& SubmitHost = "{self._host_name}"'
            )
        try:
            cursor.execute(attempt_update)
            connection.commit()
        except Exception as e:
            print("Error:", attempt_update)
            print("Error:", e)
            return

    def _check_history(
        self,
        job: Mapping[str, Any],
        connection: "MySQLdb.connections.Connection",
        cursor: "MySQLdb.cursors.DictCursor",
    ) -> None:
        """Read Condor history, classify missing inputs, and record failure details."""
        historystatuscommand = f"condor_history -limit 1 {job['BatchJobID']!s} -json"
        print(historystatuscommand)
        try:
            json_outputstr = subprocess.check_output(historystatuscommand.split(" "))
        except Exception as e:
            print("Error:", historystatuscommand)
            print("Error:", e)
            return
        if str(json_outputstr, "utf-8") == "[\n]\n":
            attempt_update = (
                f'UPDATE Attempts SET Status = "{4!s}", ExitCode = {999!s}, '
                "ProgramFailed = 'condor' "
                f"WHERE BatchJobID = '{job['BatchJobID']!s}' "
                f'&& SubmitHost = "{self._host_name}"'
            )
            try:
                cursor.execute(attempt_update)
                connection.commit()
            except Exception as e:
                print(e)
                pass
        elif str(json_outputstr, "utf-8") != "":
            json_jobar = json.loads(str(json_outputstr, "utf-8"))
            if json_jobar == []:
                return
            json_job = json_jobar[0]
            num_starts = str(json_job["NumJobStarts"])
            exit_code = "NULL"
            if (
                json_job["JobStatus"] != AttemptStatus.REMOVED
                and "ExitCode" in json_job
            ):
                print("Out:", str(json_job["Out"]))
                print("Exit Code:", str(json_job["ExitCode"]))
                exit_code = str(json_job["ExitCode"])
            start_time = 0
            if "JobStartDate" in json_job:
                start_time = json_job["JobStartDate"]
            completed_time = "NULL"
            if (
                json_job["JobStatus"] >= AttemptStatus.REMOVED
                and "JobFinishedHookDone" in json_job
            ):
                completed_time = json_job["JobFinishedHookDone"]
            wall_time = timedelta(seconds=json_job["RemoteWallClockTime"])
            cpu_time = timedelta(seconds=json_job["RemoteUserCpu"])
            ram_used = str(float(json_job["ImageSize_RAW"]) / float(1024))
            trans_in_size = json_job["TransferInputSizeMB"]
            job_status = json_job["JobStatus"]
            if "HoldReasonCode" in json_job:
                json_job["HoldReasonCode"]
            if job_status == AttemptStatus.HELD:
                missing_f = False
                for f in json_job["TransferInput"].split(","):
                    if ".hddm" in f:
                        missing_f = Path(f).is_file()
                if missing_f is False:
                    job_status = AttemptStatus.INACTIVE
            if str(exit_code) == str(ExitCode.RANDOM_TRIGGER_NOT_FOUND) or str(
                exit_code
            ) == str(ExitCode.RANDOM_TRIGGER_INITIALIZATION_FAILED):
                print("EXIT CODE 232 DETECTED")
                run_query = (
                    "SELECT RunNumber, Project_ID FROM Jobs "
                    f"WHERE ID = {job['Job_ID']!s}"
                )
                cursor.execute(run_query)
                this_job = cursor.fetchall()
                if len(this_job) == 1:
                    job_run_number = this_job[0]["RunNumber"]
                    background_query = (
                        "SELECT BKG FROM Project "
                        f"WHERE ID = {this_job[0]['Project_ID']!s}"
                    )
                    cursor.execute(background_query)
                    this_job_bkg = cursor.fetchall()
                    if len(this_job_bkg) == 1:
                        print(this_job_bkg)
                        attempt_bkg = this_job_bkg[0]["BKG"]
                        attempt_bkg_parts = attempt_bkg.split(":")
                        print(len(attempt_bkg_parts))
                        if len(attempt_bkg_parts) != 1:
                            locally_found = False
                            try:
                                random_file_dir = attempt_bkg_parts[1].split("+")[0]
                                random_file_name = (
                                    f"run{str(job_run_number).zfill(6)}_random.hddm"
                                )
                                pelican_server = (
                                    "osdf://jlab-osdf/gluex/osgpool/random_triggers/"
                                )
                                pelican_check = (
                                    f"pelican object ls {pelican_server}"
                                    f"{random_file_dir}/{random_file_name}"
                                )
                                os.environ["BEARER_TOKEN_FILE"] = (
                                    "/var/run/user/10967/bt_u10967"
                                )
                                os.environ["XDG_RUNTIME_DIR"] = "/run/user/10967"
                                my_env = os.environ.copy()
                                p = Popen(
                                    pelican_check,
                                    env=my_env,
                                    stdin=PIPE,
                                    stdout=PIPE,
                                    stderr=PIPE,
                                    bufsize=-1,
                                    shell=True,
                                    close_fds=True,
                                )
                                output, errors = p.communicate()
                                if f"Failure getting {pelican_server}" not in str(
                                    errors, "utf-8"
                                ) and random_file_name in str(output, "utf-8"):
                                    print("FILE FOUND VIA PELICAN")
                                    locally_found = True
                            except Exception as e:
                                print(e)
                                locally_found = False
                            print("is found:", locally_found)
                            if locally_found:
                                random_path = _random_trigger_path(
                                    attempt_bkg_parts[1], job_run_number
                                )
                                print(f"found file locally: {random_path}")
                                print("7 job stat")
                                job_status = AttemptStatus.SUSPENDED
                                if locally_found:
                                    job_status = AttemptStatus.COMPLETED
                                    exit_code = ExitCode.RANDOM_TRIGGER_AVAILABLE
                            else:
                                print("6 job stat")
                                job_status = AttemptStatus.INACTIVE
                                deactivate_job = (
                                    f"UPDATE Jobs SET IsActive = {JOB_INACTIVE} "
                                    f"WHERE ID = {job['Job_ID']!s};"
                                )
                                print(deactivate_job)
                                cursor.execute(deactivate_job)
                                connection.commit()
            failed_program = "NULL"
            if str(exit_code) != str(ExitCode.SUCCESS) and str(exit_code) != "NULL":
                stdout_path = Path(str(json_job["Out"]))
                print(stdout_path)
                if not stdout_path.is_file():
                    remote_suffix = str(stdout_path).split("REQUESTEDMC_OUTPUT")[1]
                    remote_path = PurePosixPath(
                        "/cache/halld/gluex_simulations/REQUESTED_MC"
                    ) / remote_suffix.lstrip("/")
                    local_path = Path("/tmp") / stdout_path.name
                    command = (
                        f"scp {self._user_name}@dtn1902:{remote_path} {local_path}"
                    )
                    print(command)
                    subprocess.call(command, shell=True)
                    stdout_path = local_path
                try:
                    with stdout_path.open() as stdout_f:
                        for num, line in enumerate(stdout_f, 1):
                            if "Something went wrong with" in line:
                                splitl = line.strip().split(" ")
                                failed_program = splitl[len(splitl) - 1]
                except Exception as e:
                    print(e)
                    failed_program = "Unidentified"
                    pass
            failed_program = failed_program.replace("(", "\\(")
            failed_program = failed_program.replace(")", "\\)")
            run_ip = "NULL"
            if "LastPublicClaimId" in json_job:
                ipstr = str(json_job["LastPublicClaimId"])
                ipstr = ipstr.split("#")[0]
                ipstr = ipstr[1:-1].split(":")[0]
                run_ip = ipstr
            last_remote_host = "NULL"
            if "LastRemoteHost" in json_job:
                last_remote_host = json_job["LastRemoteHost"]
            started_at = datetime.fromtimestamp(float(start_time))
            attempt_update = (
                "UPDATE Attempts "
                f'SET NumStarts = {num_starts!s}, Status = "{job_status!s}", '
                f"ExitCode = {exit_code!s}, "
                f"Start_Time = '{started_at!s}', "
                f"RunningLocation = '{last_remote_host!s}', "
                f"WallTime = '{_duration_text(wall_time)}', "
                f"CPUTime = '{_duration_text(cpu_time)}', RAMUsed = '{ram_used}', "
                f"Size_In = {trans_in_size!s}, RunIP = '{run_ip!s}'"
            )
            if completed_time != "NULL":
                completed_at = datetime.fromtimestamp(float(completed_time))
                attempt_update = (
                    "UPDATE Attempts "
                    f'SET NumStarts = {num_starts!s}, Status = "{job_status!s}", '
                    f"ExitCode = {exit_code!s}, "
                    f"Start_Time = '{started_at!s}', "
                    f"Completed_Time = '{completed_at!s}', "
                    f"RunningLocation = '{last_remote_host!s}', "
                    f"WallTime = '{_duration_text(wall_time)}', "
                    f"CPUTime = '{_duration_text(cpu_time)}', "
                    f"RAMUsed = '{ram_used}', Size_In = {trans_in_size!s}, "
                    f"RunIP = '{run_ip!s}'"
                )
            if failed_program != "NULL":
                attempt_update = (
                    f"{attempt_update}, ProgramFailed = '{failed_program!s}'"
                )
            attempt_update = (
                f"{attempt_update} "
                f"WHERE BatchJobID = '{job['BatchJobID']!s}' "
                f'&& SubmitHost = "{self._host_name}"'
            )
            try:
                cursor.execute(attempt_update)
                connection.commit()
            except Exception as e:
                print(e)
                pass


def split_assignments(items: Sequence[Any], worker_count: int) -> List[List[Any]]:
    """Distribute items across worker lists in round-robin order."""
    to_return = []
    for i in range(0, worker_count):
        to_return.append([])
    for count, ele in enumerate(items):
        index = count % worker_count
        to_return[index].append(ele)
    return to_return


class OverlordRun:
    """Coordinate scheduler and completion workers and track monitoring iterations."""

    def __init__(
        self,
        user_name: str,
        host_name: str,
        size_updater: Optional[ProjectSizeUpdater] = None,
    ) -> None:
        self._user_name = user_name
        self._host_name = host_name
        self._size_updater = size_updater

    def run(self, argv: Sequence[str]) -> None:
        """Monitor repeatedly; any CLI argument overrides the process-count limit."""
        try:
            database_connection = MySQLdb.connect(
                host=DB_HOST, user=DB_USER, db=DB_NAME
            )
            database_cursor = database_connection.cursor(MySQLdb.cursors.DictCursor)
        except BaseException:
            print(
                "WARNING: CANNOT CONNECT TO DATABASE.  JOBS WILL NOT BE "
                "CONTROLLED OR MONITORED"
            )
            pass
        iteration = 0
        iteration_limit = -1
        max_workers = 20
        completion_workers = 4
        override_process_limit = False
        if len(argv) != 0:
            override_process_limit = True
        running_processes = subprocess.check_output(
            [
                (
                    f"echo `ps all -u {self._user_name} | grep MCOverlord.py | grep -v "
                    "grep | wc -l`"
                )
            ],
            shell=True,
        )
        print(int(running_processes))
        if int(running_processes) < 2 or override_process_limit:
            while iteration < iteration_limit or iteration_limit == -1:
                iteration = iteration + 1
                database_cursor.execute(
                    "INSERT INTO MCOverlord (Host, StartTime, Status) "
                    f"VALUES ('{socket.gethostname()!s}', NOW(), "
                    f"'{RunStatus.RUNNING}' )"
                )
                database_connection.commit()
                run_id_query = "SELECT MAX(ID) FROM MCOverlord;"
                database_cursor.execute(run_id_query)
                run_rows = database_cursor.fetchall()
                try:
                    pending_attempts_query = (
                        "SELECT * FROM Attempts "
                        "WHERE BatchSystem = 'OSG' "
                        f'&& SubmitHost = "{self._host_name}" '
                        f"&& Status != '{AttemptStatus.COMPLETED}' "
                        f"&& Status != '{AttemptStatus.REMOVED}' "
                        f"&& Status != '{AttemptStatus.INACTIVE}' "
                        f"&& Status != '{AttemptStatus.HELD}';"
                    )
                    print(pending_attempts_query)
                    database_cursor.execute(pending_attempts_query)
                    alljobs = list(database_cursor.fetchall())
                    random.shuffle(alljobs)
                    length_limit = 50000
                    if len(alljobs) > length_limit:
                        alljobs = alljobs[:length_limit]
                    if len(alljobs) != 0:
                        target_amount = 250
                        print(len(alljobs), target_amount, max_workers)
                        if len(alljobs) < target_amount:
                            target_amount = int(len(alljobs) / 5)
                        if target_amount == 0:
                            target_amount = 1
                        worker_count = min(
                            int(len(alljobs) / target_amount), max_workers
                        )
                        monitoring_assignments = split_assignments(
                            alljobs, worker_count
                        )
                        spawns = []
                        for i in range(0, worker_count):
                            time.sleep(random.randint(1, worker_count))
                            print(f"block {i!s}")
                            print(len(monitoring_assignments[i]))
                            if len(monitoring_assignments[i]) != 0:
                                p = Process(
                                    target=check_osg, args=(monitoring_assignments[i],)
                                )
                                p.daemon = True
                                spawns.append(p)
                        for i in range(0, len(spawns)):
                            time.sleep(random.randint(1, worker_count) / 1000.0)
                            spawns[i].start()
                        for i in range(0, len(spawns)):
                            if spawns[i].is_alive():
                                spawns[i].join()
                    print("CHECKING GLOBALS ON MAIN")
                    if self._size_updater is None:
                        update_output_sizes()
                    else:
                        self._size_updater.update()
                    outstanding_projects_query = (
                        "SELECT * FROM Project "
                        "WHERE (Is_Dispatched != '0' "
                        f"&& Tested != '{ProjectStatus.TEST_FAILED}' "
                        f"&& Tested != '{ProjectStatus.STOPPED}' ) "
                        "&& Notified IS NULL"
                    )
                    print(outstanding_projects_query)
                    try:
                        database_cursor.execute(outstanding_projects_query)
                        outstanding_projects = database_cursor.fetchall()
                    except BaseException:
                        print("DB connection died. Re-establish and try again.")
                        try:
                            database_connection = MySQLdb.connect(
                                host=DB_HOST, user=DB_USER, db=DB_NAME
                            )
                            database_cursor = database_connection.cursor(
                                MySQLdb.cursors.DictCursor
                            )
                            database_cursor.execute(outstanding_projects_query)
                            outstanding_projects = database_cursor.fetchall()
                        except BaseException:
                            print(
                                "WARNING: CANNOT CONNECT TO DATABASE.  JOBS WILL "
                                "NOT BE CONTROLLED OR MONITORED"
                            )
                            pass
                    for proj in outstanding_projects:
                        print("to check", proj["ID"])
                    if completion_workers > 0:
                        completion_assignments = split_assignments(
                            outstanding_projects, completion_workers
                        )
                    if len(outstanding_projects) < completion_workers:
                        completion_workers = len(outstanding_projects)
                    comp_spawns = []
                    for i in range(0, completion_workers):
                        compp = Process(
                            target=check_projects_for_completion,
                            args=(completion_assignments[i],),
                        )
                        compp.daemon = True
                        comp_spawns.append(compp)
                    for i in range(0, len(comp_spawns)):
                        comp_spawns[i].start()
                    for i in range(0, len(comp_spawns)):
                        if comp_spawns[i].is_alive():
                            comp_spawns[i].join()
                    if completion_workers == 0:
                        check_projects_for_completion(outstanding_projects)
                    database_cursor.execute(
                        "UPDATE MCOverlord "
                        f'SET EndTime = NOW(), Status = "{RunStatus.SUCCESS}" '
                        f"WHERE ID = {run_rows[0]['MAX(ID)']!s}"
                    )
                    database_connection.commit()
                except Exception as e:
                    print("exception")
                    print(e)
                    database_cursor.execute(
                        f'UPDATE MCOverlord SET Status = "{RunStatus.FAIL}" '
                        f"WHERE ID = {run_rows[0]['MAX(ID)']!s}"
                    )
                    database_connection.commit()
                    break
        database_connection.close()


def check_osg(jobs: Sequence[Mapping[str, Any]]) -> None:
    """Multiprocessing entry point for Condor attempt checks."""
    OsgMonitor(runner_name, HOST_NAME).check(jobs)


def check_projects_for_completion(projects: Sequence[Mapping[str, Any]]) -> None:
    """Multiprocessing entry point for project completion checks."""
    ProjectCompletionChecker(runner_name, HOST_NAME).check(projects)


def main(argv: Sequence[str]) -> None:
    """Run scheduler and completion monitoring with the configured database session."""
    OverlordRun(runner_name, HOST_NAME).run(argv)


def update_output_sizes() -> None:
    """Update project sizes using the configured database session."""
    ProjectSizeUpdater(database_connection, database_cursor, runner_name).update()


if __name__ == "__main__":
    main(sys.argv[1:])
