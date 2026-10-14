#!/usr/bin/env python3
"""Submit pending MC jobs in bundles and record the submitter run's outcome."""

import os
import pwd
import socket
import subprocess
import sys
from typing import Any, List, Mapping, Sequence, TextIO, Tuple

import MySQLdb
from mc_status import JOB_ACTIVE, ProjectStatus, RunStatus

DB_HOST = "hallddb.jlab.org"
DB_USER = "mcuser"
DB_NAME = "gluex_mc"
ALLOWED_USERS = ("tbritton", "mcwrap")
MCWRAPPER_BOT_HOME = "/scigroup/mcwrapper/gluex_MCwrapper/"
PAYLOAD_CONFIG_PATH = "MCSubDispatched.config"
BLOCK_SIZE = 1000
MAX_RUNNING_SUBMITTERS = 3
DEFAULT_EVENTS_PER_FILE = 20000

# Preserve the existing database setup and account-check order.
database_connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
database_cursor = database_connection.cursor(MySQLdb.cursors.DictCursor)
runner_name = pwd.getpwuid(os.getuid())[0]
if runner_name not in ALLOWED_USERS:
    print("ERROR: You must be tbritton or mcwrap to run this script")
    sys.exit(1)


class PayloadConfigWriter:
    """Append project settings to a copied OSG or SWIF payload template."""

    def __init__(self, user_name: str) -> None:
        self._user_name = user_name

    def write(self, project: Mapping[str, Any], batch_system: str) -> None:
        """Retain payload keys, value formatting, and associated SWIF copies."""
        config = open(PAYLOAD_CONFIG_PATH, "a")
        config.write(f"PROJECT={project['Exp']}\n")
        if str(project["Exp"]) == "CPP":
            config.write("FLUX_TO_GEN=cobrems\n")
        if 30000 <= int(project["RunNumLow"]) <= 39999 and str(
            project["VersionSet"]
        ) in ("recon-2017_01-ver05.xml", "version_7.2.0.xml"):
            config.write("VARIATION=mc_2017_01_ver05\n")
            config.write("RECON_VERSION=mc_2017_01_ver05\n")
            config.write("ANA_VERSION=mc_2017_01_ver05\n")
        location_parts = project["OutputLocation"].split("/")
        config.write(f"WORKFLOW_NAME=proj{project['ID']}_{location_parts[-2]}\n")
        config.write(f"{project['Config_Stub']:s}\n")
        # The existing format truncates the string, rather than rounding energy.
        config.write(f"GEN_MIN_ENERGY={str(project['GenMinE'])[:5]}\n")
        config.write(f"GEN_MAX_ENERGY={str(project['GenMaxE'])[:5]}\n")
        if str(project["GenFlux"]) == "cobrems":
            config.write("FLUX_TO_GEN=cobrems\n")
        if project["CoherentPeak"] is not None:
            config.write(f"COHERENT_PEAK={project['CoherentPeak']}\n")
        self._write_generator(config, project, batch_system)
        if (
            project["GenPostProcessing"] is not None
            and project["GenPostProcessing"] != ""
        ):
            config.write(f"GENERATOR_POSTPROCESS={project['GenPostProcessing']}\n")
        config.write(f"GEANT_VERSION={project['GeantVersion']}\n")
        config.write(f"NOSECONDARIES={abs(project['GeantSecondaries'] - 1)}\n")
        config.write(f"BKG={project['BKG']}\n")
        output_directory = "/".join(str(project["OutputLocation"]).split("/")[7:-1])
        if batch_system == "OSG":
            config.write(
                f"DATA_OUTPUT_BASE_DIR=/osgpool/halld/{self._user_name}/"
                f"REQUESTEDMC_OUTPUT/{output_directory}\n"
            )
        elif batch_system == "SWIF":
            config.write(
                "DATA_OUTPUT_BASE_DIR=/cache/halld/gluex_simulations/REQUESTED_MC/"
                f"{output_directory}\n"
            )
        if project["RCDBQuery"] != "":
            config.write(f"RCDB_QUERY={project['RCDBQuery']:s}\n")
        if project["eBeamEnergy"] is not None:
            config.write(f"eBEAM_ENERGY={project['eBeamEnergy']}\n")
        if project["eBeamCurrent"] is not None:
            config.write(f"eBEAM_CURRENT={project['eBeamCurrent']}\n")
        self._write_reactions(config, project, batch_system)
        config.write(
            "ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/"
            f"{project['VersionSet']}\n"
        )
        if project["ANAVersionSet"] is not None and project["ANAVersionSet"] != "None":
            config.write(
                "ANA_ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/"
                f"{project['ANAVersionSet']}\n"
            )
        if project["SimVersionSet"] is not None and project["SimVersionSet"] != "None":
            config.write(
                "SIM_ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/"
                f"{project['SimVersionSet']}\n"
            )
        for stage in ("GENERATOR", "POSTGEN", "SIMULATION", "MCSMEAR", "RECON", "ANA"):
            config.write(f"{stage}_OS=db\n")
        config.close()

    def _write_generator(
        self, config: TextIO, project: Mapping[str, Any], batch_system: str
    ) -> None:
        file_generator = str(project["Generator"]) == "file:"
        if not file_generator:
            config.write(f"GENERATOR={project['Generator']}\n")
        if batch_system == "OSG":
            location = str(project["Generator_Config"])
        elif batch_system == "SWIF":
            location = project["Generator_Config"].replace(
                f"/osgpool/halld/{self._user_name}/",
                f"/work/halld/home/{self._user_name}/",
            )
            command = f"scp {project['Generator_Config']} ifarm:{location}"
            print(
                "COPYING GENERATOR file"
                if file_generator
                else "COPYING GENERATOR CONFIG"
            )
            print(command)
            subprocess.call(command, shell=True)
        else:
            return
        if file_generator:
            config.write(f"GENERATOR={project['Generator']}/{location}\n")
        else:
            config.write(f"GENERATOR_CONFIG={location}\n")

    def _write_reactions(
        self, config: TextIO, project: Mapping[str, Any], batch_system: str
    ) -> None:
        if project["ReactionLines"] == "":
            return
        local_path = (
            f"/osgpool/halld/{self._user_name}/REQUESTEDMC_CONFIGS/"
            f"{project['ID']}_jana.config"
        )
        if project["ReactionLines"][:5] != "file:":
            jana_config = open(local_path, "w")
            plugins = "PLUGINS danarest,monitoring_hists,mcthrown_tree"
            if project["ReactionLines"]:
                plugins = f"{plugins},ReactionFilter\n{project['ReactionLines']:s}"
            else:
                plugins = f"{plugins}\n"
            jana_config.write(plugins)
            jana_config.close()
        if batch_system == "OSG":
            config.write(f"CUSTOM_PLUGINS=file:{local_path}\n")
        elif batch_system == "SWIF":
            remote_path = (
                f"/work/halld/home/{self._user_name}/REQUESTEDMC_CONFIGS/"
                f"{project['ID']}_jana.config"
            )
            command = f"scp {local_path} ifarm:{remote_path}"
            print(command)
            subprocess.call(command, shell=True)
            config.write(f"CUSTOM_PLUGINS=file:{remote_path}\n")


def decide_system(job: Mapping[str, Any]) -> str:
    """Retain the existing unconditional OSG choice for every job."""
    return "OSG"


class JobSubmitter:
    """Build payloads, launch bundles, and track submitted job IDs in a batch."""

    def __init__(self, cursor: "MySQLdb.cursors.DictCursor", user_name: str) -> None:
        self._cursor = cursor
        self._user_name = user_name
        self._config_writer = PayloadConfigWriter(user_name)

    def submit(
        self, jobs: Sequence[Mapping[str, Any]], submitted_job_ids: List[int]
    ) -> None:
        """Retain disk checks, bundle selection, and removal from the pending list."""
        print("Submitting SubList")
        pending_jobs = list(jobs)
        print(f"Submitting >= {len(pending_jobs)} jobs")
        row_index = 0
        while row_index < len(pending_jobs):
            print(f"on row {row_index}", "out of", str(len(pending_jobs)))
            job = pending_jobs[row_index]
            if job["ID"] in submitted_job_ids:
                print(f"Job {job['ID']} already submitted")
                row_index += 1
                continue
            process = subprocess.Popen(
                "df -H | grep /osgpool/halld",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            output, _errors = process.communicate()
            percent_full = float(output.split()[4].decode("utf-8").strip("%"))
            print(f"percent full is {percent_full}")
            if percent_full > 75.0:
                print("Node is too full to submit new jobs")
                return
            print("about to bundle")
            query = (
                "select ID, FileNumber from Jobs where Project_ID in "
                f"(SELECT Project_ID from Jobs where ID = {job['ID']}) "
                "and RunNumber in "
                f"(SELECT RunNumber from Jobs where ID = {job['ID']}) "
                "and NumEvts in "
                f"(SELECT NumEvts from Jobs where ID = {job['ID']}) "
                f"and IsActive = {JOB_ACTIVE};"
            )
            self._cursor.execute(query)
            bundle_jobs = self._cursor.fetchall()
            print("bundled:", len(bundle_jobs))
            self._cursor.execute(
                f"SELECT * FROM Project where ID = {job['Project_ID']}"
            )
            project = self._cursor.fetchall()[0]
            run_number = job["RunNumber"]
            # Read these settings before copying or writing payload files, as before.
            cleanup_flags = (
                0 if project["SaveGeneration"] == 1 else 1,
                0 if project["SaveGeant"] == 1 else 1,
                0 if project["SaveSmear"] == 1 else 1,
                0 if project["SaveReconstruction"] == 1 else 1,
            )
            batch_system = decide_system(job)
            if batch_system == "OSG":
                subprocess.call(
                    f"cp {MCWRAPPER_BOT_HOME}/examples/OSGShell.config "
                    f"./{PAYLOAD_CONFIG_PATH}",
                    shell=True,
                )
            elif batch_system == "SWIF":
                subprocess.call(
                    f"cp {MCWRAPPER_BOT_HOME}examples/SWIFShell.config "
                    f"./{PAYLOAD_CONFIG_PATH}",
                    shell=True,
                )
            self._config_writer.write(project, batch_system)
            events_per_file = self._events_per_file(project)
            print("Setting token env")
            os.environ["BEARER_TOKEN_FILE"] = "/var/run/user/10967/bt_u10967"
            os.environ["XDG_RUNTIME_DIR"] = "/run/user/10967"
            command = self._submission_command(
                job, project, events_per_file, run_number, cleanup_flags
            )
            print("COMMAND", command)
            output, errors = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ,
                executable="/bin/bash",
            ).communicate()
            print("OUT", output)
            print("ERR", errors)
            for bundle_job in bundle_jobs:
                submitted_job_ids.append(bundle_job["ID"])
            print("Submitted", submitted_job_ids)
            print("length of list to submit", len(pending_jobs))
            for pending_job in pending_jobs.copy():
                if pending_job["ID"] in submitted_job_ids:
                    pending_jobs.pop(pending_jobs.index(pending_job))
                    row_index = -1
            row_index += 1

    def _events_per_file(self, project: Mapping[str, Any]) -> int:
        query = (
            "SELECT PerFile from Generator_perfiles "
            f'where GenName = "{project["Generator"]}";'
        )
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        try:
            return rows[0]["PerFile"]
        except Exception as error:
            print("per file error")
            print(error)
            return DEFAULT_EVENTS_PER_FILE

    def _submission_command(
        self,
        job: Mapping[str, Any],
        project: Mapping[str, Any],
        events_per_file: int,
        run_number: int,
        cleanup_flags: Tuple[int, int, int, int],
    ) -> str:
        """Keep the PATH-selected python3 command and existing flags and paths."""
        clean_generation, clean_geant, clean_smear, clean_reconstruction = cleanup_flags
        log_directory = project["OutputLocation"].split("/")[7]
        return (
            f"python3 {MCWRAPPER_BOT_HOME}/gluex_MC.py {PAYLOAD_CONFIG_PATH} "
            f"{run_number} {job['NumEvts']} per_file={events_per_file} "
            f"base_file_number={job['FileNumber']} generate={project['RunGeneration']} "
            f"cleangenerate={clean_generation} geant={project['RunGeant']} "
            f"cleangeant={clean_geant} mcsmear={project['RunSmear']} "
            f"cleanmcsmear={clean_smear} recon={project['RunReconstruction']} "
            f"cleanrecon={clean_reconstruction} projid=-{job['ID']} "
            f"logdir=/osgpool/halld/{self._user_name}/REQUESTEDMC_LOGS/{log_directory} "
            "batch=2 submitter=1 tobundle=1"
        )


class SubmitterRun:
    """Select pending jobs repeatedly and record the run's existing success path."""

    def __init__(
        self,
        connection: "MySQLdb.connections.Connection",
        cursor: "MySQLdb.cursors.DictCursor",
        user_name: str,
    ) -> None:
        self._connection = connection
        self._cursor = cursor
        self._submitter = JobSubmitter(cursor, user_name)

    def run(self) -> None:
        """Retain startup-error handling, refresh commits, and outcome tracking."""
        try:
            self._cursor.execute(
                "INSERT INTO MCSubmitter (Host, StartTime, Status) "
                f"VALUES ('{socket.gethostname()}', NOW(), '{RunStatus.RUNNING}')"
            )
            self._connection.commit()
        except Exception as error:
            print(error)
        self._cursor.execute("SELECT MAX(ID) FROM MCSubmitter;")
        run_rows = self._cursor.fetchall()
        submitted_job_ids: List[int] = []
        try:
            while True:
                print("=============================================================")
                query = self._pending_jobs_query()
                print("Query:", query)
                self._cursor.execute(query)
                jobs = self._cursor.fetchall()
                print(f"length of rows: {len(jobs)}")
                if not jobs:
                    break
                self._submitter.submit(jobs, submitted_job_ids)
                # Refresh the selection even when gluex_MC.py commits its own session.
                self._connection.commit()
            try:
                self._cursor.execute(
                    "UPDATE MCSubmitter SET EndTime = NOW(), "
                    f'Status = "{RunStatus.SUCCESS}" '
                    f"where ID = {run_rows[0]['MAX(ID)']}"
                )
                self._connection.commit()
            except Exception as error:
                print(error)
        except Exception as error:
            print("exception")
            print(error)
            self._cursor.execute(
                f'UPDATE MCSubmitter SET Status = "{RunStatus.FAIL}" '
                f"where ID = {run_rows[0]['MAX(ID)']}"
            )
            self._connection.commit()

    def _pending_jobs_query(self) -> str:
        query = (
            "SELECT UName, RunNumber, FileNumber, Tested, NumEvts, BKG, Notified, "
            "Jobs.ID, Project_ID, Priority, IsActive FROM Jobs "
            "INNER JOIN Project ON Jobs.Project_ID = Project.ID "
            "INNER JOIN Users ON Project.user_id = Users.id "
            "LEFT JOIN Attempts ON Jobs.ID = Attempts.Job_ID "
            f"WHERE Tested = {ProjectStatus.READY} AND Notified IS NULL "
            f"AND IsActive = {JOB_ACTIVE} AND Attempts.Job_ID IS NULL "
            "ORDER BY Priority DESC"
        )
        if BLOCK_SIZE != 1:
            query = f"{query} LIMIT {BLOCK_SIZE}"
        return f"{query};"


def _count_running_submitters(user_name: str) -> bytes:
    """Return the original process-count output, including its printed byte form."""
    command = (
        f"echo `ps all -u {user_name} | grep MCSubmitter.py | grep -v grep | wc -l`"
    )
    return subprocess.check_output([command], shell=True)


def main(argv: Sequence[str]) -> None:
    """Submit when allowed by the existing stop-file and process-count checks."""
    if os.path.isfile(f"/osgpool/halld/{runner_name}/.ALLSTOP"):
        print("ALL STOP DETECTED")
        sys.exit(1)
    process_count = _count_running_submitters(runner_name)
    print(process_count)
    if int(process_count) < MAX_RUNNING_SUBMITTERS:
        SubmitterRun(database_connection, database_cursor, runner_name).run()
    database_connection.close()


if __name__ == "__main__":
    main(sys.argv[1:])
