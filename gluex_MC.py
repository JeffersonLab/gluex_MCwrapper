#!/usr/bin/env python3
"""Configure MC jobs, allocate events across runs, and submit simulation payloads.

Written by Thomas Britton, 2017.
"""

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from optparse import OptionParser
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    MutableMapping,
    NoReturn,
    Sequence,
    Tuple,
    Union,
    cast,
)

import ccdb
import hddm_s
import MySQLdb
import rcdb

from Utilities.mc_status import JOB_ACTIVE, AttemptStatus, ProjectStatus

MCWRAPPER_VERSION = "2.14.1"
MCWRAPPER_DATE = "8/25/26"


def get_os_name(version_set: str) -> str:
    """Look up the operating system associated with a version-set filename."""
    version_set = version_set[version_set.rfind("/") + 1 :]
    connection = MySQLdb.connect(
        user="vsuser", database="vsdb", host="hallddb.jlab.org"
    )
    cursor = connection.cursor()
    query = (
        "SELECT OSName "
        "FROM versionSet "
        "INNER JOIN OSVersions ON versionSet.OS_ID=OSVersions.ID "
        f"WHERE versionSet.filename='{version_set!s}'"
    )
    cursor.execute(query)
    os_names = cursor.fetchall()
    if len(os_names) != 1:
        return "AmbiguousOS"
    return os_names[0][0]


class JobRepository:
    """Record simulation jobs, attempts, and project outcomes."""

    def __init__(self, connection: Any, cursor: Any) -> None:
        self.connection = connection
        self.cursor = cursor

    @classmethod
    def connect(cls) -> "JobRepository":
        """Try to open workflow tracking; allow untracked runs when it is unavailable."""
        try:
            connection = MySQLdb.connect(
                user="mcuser", database="gluex_mc", host="hallddb.jlab.org"
            )
            return cls(connection, connection.cursor())
        except BaseException:
            return cls(None, None)

    def bundle_job(self, job_id: Union[int, str]) -> List[Tuple[int, int]]:
        """Find active jobs sharing the project, run, and event count of a job."""
        bundle_query = (
            "SELECT ID,FileNumber "
            "FROM Jobs "
            "WHERE Project_ID IN (SELECT Project_ID "
            "FROM Jobs "
            f"WHERE ID={job_id!s}) "
            "AND RunNumber IN (SELECT RunNumber "
            "FROM Jobs "
            f"WHERE ID={job_id!s}) "
            "AND NumEvts IN (SELECT NumEvts "
            "FROM Jobs "
            f"WHERE ID={job_id!s}) "
            f"AND IsActive={JOB_ACTIVE};"
        )
        self.cursor.execute(bundle_query)
        jobs = self.cursor.fetchall()
        print("count:", len(jobs))
        print(jobs)
        return jobs

    def mark_no_events(self, project_id: Union[int, str]) -> None:
        """Mark the project as having no events when its email row is unique."""
        email_query = f"SELECT Email FROM Projects WHERE ID={project_id!s};"
        self.cursor.execute(email_query)
        email_rows = self.cursor.fetchall()
        if len(email_rows) == 1:
            project_update_q = f"UPDATE Projects SET Tested={ProjectStatus.NO_EVENTS} WHERE ID={project_id!s};"
            self.cursor.execute(project_update_q)
            self.connection.commit()

    def record_job(
        self,
        project_id: Union[int, str],
        run_number: Union[int, str],
        file_number: Union[int, str],
        batch_job_id: str,
        num_events: Union[int, str],
    ) -> None:
        """Insert an active job with its run, file number, and event count."""
        self.cursor.execute(
            (
                "INSERT INTO Jobs (Project_ID, RunNumber, FileNumber, Creation_Time, IsActive, NumEvts) "
                f"VALUES ({project_id!s}, {run_number!s}, {file_number!s}, NOW(), {JOB_ACTIVE}, {num_events!s})"
            )
        )
        self.connection.commit()

    def record_first_attempt(
        self,
        project_id: Union[int, str],
        run_number: Union[int, str],
        file_number: Union[int, str],
        batch_system: str,
        batch_job_id: str,
        num_events: Union[int, str],
        num_cores: str,
        ram: str,
    ) -> None:
        """Find one matching active job and record its first attempt."""
        job_query = (
            "SELECT ID "
            "FROM Jobs "
            f"WHERE Project_ID={project_id!s} "
            f"&& RunNumber={run_number!s} "
            f"&& FileNumber={file_number!s} "
            f"&& NumEvts={num_events!s} "
            f"&& IsActive={JOB_ACTIVE};"
        )
        self.cursor.execute(job_query)
        matching_jobs = self.cursor.fetchall()
        if len(matching_jobs) != 1:
            print("I either can't find a job or too many jobs might be mine")
            sys.exit(1)
        job_id = matching_jobs[0][0]
        add_attempt = (
            "INSERT INTO Attempts (Job_ID,Creation_Time,BatchSystem,HostName,BatchJobID,Status,WallTime,CPUTime,ThreadsRequested,RAMRequested, RAMUsed) "
            f"VALUES ({job_id!s}, NOW(), '{batch_system!s}', {socket.gethostname()!s}, {batch_job_id!s}, '{AttemptStatus.CREATED}', 0, 0, {num_cores!s}, '{ram!s}', '0');"
        )
        print(add_attempt)
        self.cursor.execute(add_attempt)
        self.connection.commit()

    def execute_transaction(self, trans_string: str) -> None:
        """Execute and commit an attempt insertion transaction."""
        self.cursor.execute(trans_string)
        self.connection.commit()

    def record_attempt(
        self,
        job_id: Union[int, str],
        run_number: Union[int, str],
        file_number: Union[int, str],
        batch_system: str,
        batch_job_id: str,
        num_events: Union[int, str],
        num_cores: str,
        ram: str,
    ) -> None:
        """Check that a job exists and insert its retry attempt."""
        job_query = f"SELECT * FROM Jobs WHERE ID={job_id!s}"
        self.cursor.execute(job_query)
        matching_jobs = self.cursor.fetchall()
        if len(matching_jobs) != 1:
            print("I either can't find a job or too many jobs might be mine")
            sys.exit(1)
        add_attempt = (
            "INSERT INTO Attempts (Job_ID,Creation_Time,BatchSystem,SubmitHost,BatchJobID,Status,WallTime,CPUTime,ThreadsRequested,RAMRequested, RAMUsed) "
            f"VALUES ({job_id!s}, NOW(), '{batch_system!s}', {socket.gethostname()!s}, {batch_job_id!s}, '{AttemptStatus.CREATED}', 0, 0, {num_cores!s}, '{ram!s}', '0');"
        )
        print(add_attempt)
        self.cursor.execute(add_attempt)
        self.connection.commit()


def build_attempt_values(
    job_id: Union[int, str],
    run_number: Union[int, str],
    file_number: Union[int, str],
    batch_system: str,
    hostname: str,
    batch_job_id: str,
    num_events: Union[int, str],
    num_cores: str,
    ram: str,
) -> str:
    """Format one attempt row for a bulk insertion statement."""
    add_attempt = (
        f"({job_id!s}, NOW(), '{batch_system!s}', {hostname!s}, {batch_job_id!s}, "
        f"'{AttemptStatus.CREATED}', 0, 0, {num_cores!s}, '{ram!s}', '0')"
    )
    return add_attempt


# MakeMC shell scripts consume these fields positionally; their order is required.
COMMAND_FIELDS = (
    "batchrun",
    "environment_file",
    "ana_environment_file",
    "generator_os",
    "postgen_os",
    "simulation_os",
    "mcsmear_os",
    "recon_os",
    "ana_os",
    "generator_config",
    "output_directory",
    "run_number",
    "file_number",
    "num_events",
    "jana_calib_context",
    "jana_calibtime",
    "do_gen",
    "do_geant",
    "do_mcsmear",
    "do_recon",
    "clean_gen",
    "clean_geant",
    "clean_mcsmear",
    "clean_recon",
    "batch_system",
    "num_cores",
    "generator",
    "geant_version",
    "background_to_include",
    "custom_Gcontrol",
    "eBeam_energy",
    "coherent_peak",
    "min_generator_energy",
    "max_generator_energy",
    "custom_tag_string",
    "custom_plugins",
    "custom_ana_plugins",
    "events_per_file",
    "running_directory",
    "ccdb_sqlite_path",
    "rcdb_sqlite_path",
    "background_tagger_only",
    "radiator_thickness",
    "background_rate",
    "random_background_tag",
    "recon_version",
    "recon_calibtime",
    "ana_version",
    "ana_calibtime",
    "no_geant_secondaries",
    "mcwrapper_version",
    "no_bcal_sipm_saturation",
    "flux_to_generate",
    "flux_histogram",
    "polarization_to_generate",
    "polarization_histogram",
    "ccdb_flux_version",
    "eBeam_current",
    "experiment",
    "num_rand_trigs",
    "location",
    "generator_post",
    "generator_post_config",
    "generator_post_configevt",
    "generator_post_configdec",
    "geant_vertex_area",
    "geant_vertex_length",
    "mcsmear_notag",
    "project_directory_name",
    "random_background_rate",
    "sim_environment_file",
    "generator_file_skip",
)


def format_command(command: Mapping[str, str], user: str, bundle_size: int = 1) -> str:
    """Serialize the ordered MakeMC arguments, substituting bundled file numbers."""
    return " ".join(
        (
            "$(Process)"
            if key == "file_number" and user == "OSG" and (bundle_size != 1)
            else command[key]
            for key in COMMAND_FIELDS
        )
    )


def _log_file(directory: str, filename: str) -> Path:
    """Build a scheduler log path under its configured log directory."""
    return Path(directory) / "log" / filename


def _make_directory(path: Path) -> None:
    """Create local directories and report filesystem errors without aborting."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(error, file=sys.stderr)


def _remove_file(path: Path, missing_ok: bool = False) -> None:
    """Remove a local submission or staging file and report filesystem errors."""
    try:
        path.unlink(missing_ok=missing_ok)
    except OSError as error:
        print(error, file=sys.stderr)


class BatchSubmitter:
    """Build scheduler payloads and record submitted job attempts."""

    def __init__(self, repository: JobRepository) -> None:
        self._repository = repository

    def swif_add_job(
        self,
        config: "SimulationConfig",
        run_number: Union[int, str],
        file_number: Union[int, str],
        script_to_run: str,
        command: MutableMapping[str, str],
    ) -> None:
        """Write or submit swif jobs and record tracked jobs or attempts."""
        self._submit_swif(
            config,
            run_number,
            file_number,
            script_to_run,
            command,
            scheduler="swif",
            container=False,
        )

    def swif2_add_job(
        self,
        config: "SimulationConfig",
        run_number: Union[int, str],
        file_number: Union[int, str],
        script_to_run: str,
        command: MutableMapping[str, str],
    ) -> None:
        """Write or submit swif2 jobs and record tracked jobs or attempts."""
        self._submit_swif(
            config,
            run_number,
            file_number,
            script_to_run,
            command,
            scheduler="swif2",
            container=False,
        )

    def swif2cont_add_job(
        self,
        config: "SimulationConfig",
        run_number: Union[int, str],
        file_number: Union[int, str],
        script_to_run: str,
        command: MutableMapping[str, str],
    ) -> None:
        """Write or submit swif2 container jobs and record tracked jobs or attempts."""
        self._submit_swif(
            config,
            run_number,
            file_number,
            script_to_run,
            command,
            scheduler="swif2",
            container=True,
        )

    def qsub_add_job(
        self,
        config: "SimulationConfig",
        run_number: Union[int, str],
        file_number: Union[int, str],
        script_to_run: str,
        command: MutableMapping[str, str],
    ) -> None:
        """Write or submit qsub jobs and record tracked jobs or attempts."""
        job_stub = ""
        if command["custom_tag_string"] != "I_dont_have_one":
            job_stub = f"{command['custom_tag_string']!s}_"
        job_stub = f"{job_stub!s}{run_number!s}_{file_number!s}"
        job_name = f"{config.workflow!s}_{job_stub!s}"
        sub_command = "qsub MCqsub.submit"
        resource_directive = ""
        bits = config.num_cores.split(":")
        if len(bits) == 3:
            resource_directive = f"nodes={bits[0]!s}:{bits[1]!s}:ppn={bits[2]!s}"
        elif len(bits) == 2:
            resource_directive = f"nodes={bits[0]!s}:ppn={bits[1]!s}"
        shell_to_use = "/bin/bash"
        if script_to_run[len(script_to_run) - 3] == "c":
            shell_to_use = "/bin/csh"
        if ".iu.edu" in socket.gethostname() and config.queue_name.upper() == "STANLEY":
            submission_file = Path("MCqsub.submit").open("w")
            submission_file.write(
                f"#$ -o {_log_file(config.log_directory, f'{job_name!s}.out')!s}\n"
            )
            submission_file.write(f"#$ -N {job_name!s}\n")
            submission_file.write("#$ -j y\n")
            submission_file.write(
                f"{shell_to_use!s}{_unavailable_backend_value('indir')!s} {command!s}\n"
            )
            submission_file.write("exit 0\n")
            submission_file.close()
        else:
            submission_file = Path("MCqsub.submit").open("w")
            submission_file.write("#!/bin/sh -f\n")
            submission_file.write(f"#PBS -N {job_name!s}\n")
            submission_file.write(f"#PBS -l {resource_directive!s}\n")
            submission_file.write(
                f"#PBS -o {_log_file(config.log_directory, f'{job_name!s}.out')!s}\n"
            )
            submission_file.write(
                f"#PBS -e {_log_file(config.log_directory, f'{job_name!s}.err')!s}\n"
            )
            submission_file.write(f"#PBS -l walltime={config.time_limit!s}\n")
            if config.queue_name != "DEF":
                submission_file.write(f"#PBS -q {config.queue_name!s}\n")
            submission_file.write(f"#PBS -l mem={config.ram!s}\n")
            submission_file.write("#PBS -m a\n")
            submission_file.write("#PBS -p 0\n")
            submission_file.write("#PBS -c c=2 \n")
            submission_file.write("NCPU=\\ \n")
            submission_file.write("NNODES=\\ \n")
            submission_file.write(
                f"{shell_to_use!s} {script_to_run!s} {format_command(command, 'PBS')!s}\n"
            )
            submission_file.write("exit 0\n")
            submission_file.close()
        time.sleep(0.25)
        if config.output_directory != config.log_directory:
            _make_directory(Path(config.log_directory) / "log/")
        _make_directory(Path(config.output_directory) / "log/")
        if int(config.project_id) <= 0:
            subprocess.call(sub_command, shell=True)
            if not config.verbose:
                _remove_file(Path("MCqsub.submit"), missing_ok=False)
            if int(config.project_id) > 0:
                self._repository.record_job(
                    config.project_id,
                    run_number,
                    file_number,
                    _unavailable_backend_value("SWIF_ID_NUM"),
                    command["num_events"],
                )
            elif int(config.project_id) < 0:
                self._repository.record_attempt(
                    abs(int(config.project_id)),
                    run_number,
                    file_number,
                    "QSUB",
                    _unavailable_backend_value("SWIF_ID_NUM"),
                    command["num_events"],
                    config.num_cores,
                    config.ram,
                )

    def condor_add_job(
        self,
        config: "SimulationConfig",
        run_number: Union[int, str],
        file_number: Union[int, str],
        script_to_run: str,
        command: MutableMapping[str, str],
    ) -> None:
        """Write or submit condor jobs and record tracked jobs or attempts."""
        job_stub = ""
        if command["custom_tag_string"] != "I_dont_have_one":
            job_stub = f"{command['custom_tag_string']!s}_"
        job_stub = f"{job_stub!s}{run_number!s}_{file_number!s}"
        job_name = f"{config.workflow!s}_{job_stub!s}"
        mkdircom = f"mkdir -p {config.output_directory!s}/log/"
        submission_file = Path("MCcondor.submit").open("w")
        submission_file.write(f"Executable = {script_to_run!s}\n")
        submission_file.write(f"Arguments  = {format_command(command, 'CONDOR')!s}\n")
        submission_file.write(
            f"Error      = {_log_file(config.output_directory, f'error_{job_name!s}.log')!s}\n"
        )
        submission_file.write(
            f"Output      = {_log_file(config.output_directory, f'out_{job_name!s}.log')!s}\n"
        )
        submission_file.write(
            f"Log = {_log_file(config.output_directory, f'CONDOR_{job_name!s}.log')!s}\n"
        )
        submission_file.write(f"RequestCpus = {config.num_cores!s}\n")
        if config.condor_options != []:
            for magic in config.condor_options:
                submission_file.write(f"{magic!s}\n")
        submission_file.write("Queue 1\n")
        submission_file.close()
        job_name = job_name.replace(".", "p")
        if int(config.project_id) <= 0:
            add_command = (
                f"condor_submit -batch-name {config.workflow!s} MCcondor.submit"
            )
            if (
                add_command.find(";") != -1
                or add_command.find("&") != -1
                or mkdircom.find(";") != -1
                or (mkdircom.find("&") != -1)
            ):
                print("Nice try.....you cannot use ; or &")
                sys.exit(1)
            _make_directory(Path(config.output_directory) / "log/")
            subprocess.call(add_command, shell=True)
            _remove_file(Path("MCcondor.submit"), missing_ok=False)
        if int(config.project_id) > 0:
            self._repository.record_job(
                config.project_id,
                run_number,
                file_number,
                _unavailable_backend_value("SWIF_ID_NUM"),
                command["num_events"],
            )
        elif int(config.project_id) < 0:
            self._repository.record_attempt(
                abs(int(config.project_id)),
                run_number,
                file_number,
                "Condor",
                _unavailable_backend_value("SWIF_ID_NUM"),
                command["num_events"],
                config.num_cores,
                "UnSet",
            )

    def osg_add_job(
        self,
        config: "SimulationConfig",
        run_number: Union[int, str],
        file_number: Union[int, str],
        script_to_run: str,
        command: MutableMapping[str, str],
    ) -> None:
        """Write or submit OSG jobs and record tracked jobs or attempts."""
        ship_random_triggers = False
        job_stub = ""
        if command["custom_tag_string"] != "I_dont_have_one":
            job_stub = f"{command['custom_tag_string']!s}_"
        job_stub = job_stub + str(run_number)
        bundle_size = 1
        bundled_jobs = []
        if int(config.project_id) < 0 and config.to_bundle:
            bundled_jobs = self._repository.bundle_job(-1 * int(config.project_id))
            bundle_size = len(bundled_jobs)
        elif int(config.project_id) < 0 and (not config.to_bundle):
            bundled_jobs = [[-1 * int(config.project_id), file_number]]
            bundle_size = len(bundled_jobs)
        if bundle_size == 1:
            job_stub = f"{job_stub!s}_{file_number!s}"
        else:
            job_stub = f"{job_stub!s}_$(Process)"
        job_name = f"{config.workflow!s}_{job_stub!s}"
        script_parts = script_to_run.split("/")
        script_to_use = script_parts[len(script_parts) - 1]
        print(script_to_use)
        envfile_parts = config.environment_file.split("/")
        envfile_to_source = f"./{envfile_parts[len(envfile_parts) - 1]!s}"
        simenvfile_parts = config.sim_environment_file.split("/")
        if len(simenvfile_parts) != 1:
            simenvfile_to_source = f"./{simenvfile_parts[len(simenvfile_parts) - 1]!s}"
            envfile_to_source = f".{envfile_to_source!s}"
        anaenvfile_parts = config.ana_environment_file.split("/")
        if len(anaenvfile_parts) != 1:
            anaenvfile_to_source = f"../{anaenvfile_parts[len(anaenvfile_parts) - 1]!s}"
        command_settings = command
        command_settings["environment_file"] = envfile_to_source
        command_settings["output_directory"] = "./"
        command_settings["running_directory"] = "./"
        additional_passins = ""
        if command_settings["sim_environment_file"] != "no_Sim_env":
            additional_passins += f"{command_settings['sim_environment_file']!s}, "
            command_settings["sim_environment_file"] = simenvfile_to_source
        if command_settings["ana_environment_file"] != "no_Analysis_env":
            additional_passins += f"{command_settings['ana_environment_file']!s}, "
            command_settings["ana_environment_file"] = anaenvfile_to_source
        if command_settings["generator_config"][:5] == "file:":
            gen_config_parts = command_settings["generator_config"].split("/")
            gen_config_to_use = gen_config_parts[len(gen_config_parts) - 1]
            additional_passins += f"{command_settings['generator_config'][5:]!s}, "
            command_settings["generator_config"] = f"file:../{gen_config_to_use!s}"
        elif command_settings["generator_config"] != "NA":
            gen_config_parts = command_settings["generator_config"].split("/")
            gen_config_to_use = gen_config_parts[len(gen_config_parts) - 1]
            additional_passins += f"{command_settings['generator_config']!s}, "
            command_settings["generator_config"] = f"../{gen_config_to_use!s}"
        if command_settings["generator"][:5] == "file:":
            filegen_parts = command_settings["generator"][5:].split("/")
            additional_passins += f"{command_settings['generator'][5:]!s}, "
            command_settings["generator"] = (
                f"file:../{filegen_parts[len(filegen_parts) - 1]!s}"
            )
        if command_settings["generator_post_config"] != "Default":
            gen_post_config_parts = command_settings["generator_post_config"].split("/")
            gen_post_config_to_use = gen_post_config_parts[
                len(gen_post_config_parts) - 1
            ]
            additional_passins += f"{command_settings['generator_post_config']!s}, "
            command_settings["generator_post_config"] = f"../{gen_post_config_to_use!s}"
        if command_settings["generator_post_configevt"] != "Default":
            gen_post_configevt_parts = command_settings[
                "generator_post_configevt"
            ].split("/")
            gen_post_configevt_to_use = gen_post_configevt_parts[
                len(gen_post_configevt_parts) - 1
            ]
            additional_passins += f"{command_settings['generator_post_configevt']!s}, "
            command_settings["generator_post_configevt"] = (
                f"../{gen_post_configevt_to_use!s}"
            )
        if command_settings["generator_post_configdec"] != "Default":
            gen_post_configdec_parts = command_settings[
                "generator_post_configdec"
            ].split("/")
            gen_post_configdec_to_use = gen_post_configdec_parts[
                len(gen_post_configdec_parts) - 1
            ]
            additional_passins += f"{command_settings['generator_post_configdec']!s}, "
            command_settings["generator_post_configdec"] = (
                f"../{gen_post_configdec_to_use!s}"
            )
        if (
            command_settings["background_to_include"] == "Random"
            and command_settings["num_rand_trigs"] == -1
            or command_settings["background_to_include"][:4] == "loc:"
            or ship_random_triggers
        ):
            formatted_run_number = ""
            for i in range(len(str(run_number)), 6):
                formatted_run_number += "0"
            formatted_run_number = formatted_run_number + str(run_number)
            if command_settings["background_to_include"] == "Random":
                additional_passins += f"/osgpool/halld/random_triggers/{config.random_background_tag!s}/run{formatted_run_number!s}_random.hddm, "
            elif command_settings["background_to_include"][:4] == "loc:":
                additional_passins += f"{command_settings['background_to_include'][4:]!s}/run{formatted_run_number!s}_random.hddm, "
        if (
            command_settings["custom_plugins"] != "None"
            and command_settings["custom_plugins"][:5] == "file:"
        ):
            janaconfig_parts = command_settings["custom_plugins"].split("/")
            janaconfig_to_use = janaconfig_parts[len(janaconfig_parts) - 1]
            additional_passins += f"{command_settings['custom_plugins'][5:]!s}, "
            command_settings["custom_plugins"] = f"file:../{janaconfig_to_use!s}"
        if (
            command_settings["custom_ana_plugins"] != "None"
            and command_settings["custom_ana_plugins"][:5] == "file:"
        ):
            anajanaconfig_parts = command_settings["custom_ana_plugins"].split("/")
            anajanaconfig_to_use = anajanaconfig_parts[len(anajanaconfig_parts) - 1]
            additional_passins += f"{command_settings['custom_ana_plugins'][5:]!s}, "
            command_settings["custom_ana_plugins"] = f"file:../{anajanaconfig_to_use!s}"
        if (
            command_settings["ccdb_sqlite_path"] != "no_sqlite"
            and command_settings["ccdb_sqlite_path"] != "batch_default"
        ):
            ccdbsqlite_parts = command_settings["ccdb_sqlite_path"].split("/")
            ccdbsqlite_to_use = ccdbsqlite_parts[len(ccdbsqlite_parts) - 1]
            additional_passins += f"{command_settings['ccdb_sqlite_path']!s}, "
            command_settings["ccdb_sqlite_path"] = f"../{ccdbsqlite_to_use!s}"
        if (
            command_settings["rcdb_sqlite_path"] != "no_sqlite"
            and command_settings["rcdb_sqlite_path"] != "batch_default"
        ):
            rcdbsqlite_parts = command_settings["rcdb_sqlite_path"].split("/")
            rcdbsqlite_to_use = rcdbsqlite_parts[len(rcdbsqlite_parts) - 1]
            additional_passins += f"{command_settings['rcdb_sqlite_path']!s}, "
            command_settings["rcdb_sqlite_path"] = f"../{rcdbsqlite_to_use!s}"
        if (
            command_settings["flux_to_generate"] != "unset"
            and command_settings["flux_to_generate"] != "ccdb"
            and (command_settings["flux_to_generate"] != "cobrems")
        ):
            flux_to_use = command_settings["flux_to_generate"]
            additional_passins += f"{command_settings['flux_to_generate']!s}, "
            command_settings["flux_to_generate"] = f"../{flux_to_use!s}"
        if (
            command_settings["polarization_to_generate"] != "ccdb"
            and command_settings["polarization_histogram"] != "unset"
        ):
            tpol_to_use = command_settings["polarization_to_generate"]
            additional_passins += f"{command_settings['polarization_to_generate']!s}, "
            command_settings["polarization_to_generate"] = f"../{tpol_to_use!s}"
        if additional_passins != "":
            additional_passins = f", {additional_passins!s}"
            additional_passins = additional_passins[:-2]
        submission_file = Path(f"MCOSG_{config.project_id!s}.submit").open("w")
        submission_file.write("universe = vanilla\n")
        submission_file.write(
            f"Executable = {os.environ.get('MCWRAPPER_CENTRAL')!s}/osg-container.sh\n"
        )
        submission_file.write('+ProjectName = "gluex"\n')
        submission_file.write(
            f"Arguments  = ./{script_to_use!s} {format_command(command_settings, 'OSG', bundle_size)!s}\n"
        )
        submission_file.write(
            (
                "Requirements = (HAS_SINGULARITY == TRUE) && (HAS_CVMFS_oasis_opensciencegrid_org "
                '== True) && (TARGET.GLIDEIN_Entry_Name =!= "OSG_US_ODU-Ubuntu") && '
                "(TARGET.HasUserNamespaces == True)\n"
            )
        )
        if "data_mirror_test" in config.output_directory:
            submission_file.write(
                '+SingularityImage = "/cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_devel:latest"\n'
            )
            submission_file.write("use_oauth_services = jlab_gluex\n")
        else:
            submission_file.write(
                '+SingularityImage = "/cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_almalinux_9:latest"\n'
            )
            submission_file.write("use_oauth_services = jlab_gluex\n")
        submission_file.write("+SingularityBindCVMFS = True\n")
        submission_file.write("+SingularityAutoLoad = True\n")
        submission_file.write("should_transfer_files = YES\n")
        submission_file.write("concurrency_limits = GluexProduction\n")
        submission_file.write("on_exit_remove = true\n")
        submission_file.write("on_exit_hold = false\n")
        submission_file.write(
            f"Error      = {_log_file(config.output_directory, f'error_{job_name!s}.log')!s}\n"
        )
        submission_file.write(
            f"output      = {_log_file(config.output_directory, f'out_{job_name!s}.log')!s}\n"
        )
        submission_file.write(
            f"log = {_log_file(config.log_directory, f'OSG_{job_name!s}.log')!s}\n"
        )
        submission_file.write(f"initialdir = {config.running_directory!s}\n")
        submission_file.write(f"request_cpus = {config.num_cores!s}\n")
        submission_file.write(f"request_memory = {config.ram!s}\n")
        if int(run_number) == 40881:
            submission_file.write("request_disk = 7.0GB\n")
        elif int(run_number) == 30401:
            submission_file.write("request_disk = 7.0GB\n")
        elif 40000 < int(run_number) and int(run_number) < 49999:
            submission_file.write("request_disk = 8.0GB\n")
        else:
            submission_file.write("request_disk = 5.0GB\n")
        submission_file.write(
            f"transfer_input_files = {script_to_run!s}, {config.environment_file!s}{additional_passins!s}\n"
        )
        submission_file.write(f"queue {bundle_size!s}\n")
        submission_file.close()
        job_name = job_name.replace(".", "p")
        add_command = f"condor_submit MCOSG_{config.project_id!s}.submit"
        if add_command.find(";") != -1 or add_command.find("&") != -1:
            print("Nice try.....you cannot use ; or &")
            sys.exit(1)
        _make_directory(Path(config.log_directory) / "log/")
        _make_directory(Path(config.output_directory) / "log/")
        batch_job_id = "-1"
        if int(config.project_id) <= 0:
            os.environ["BEARER_TOKEN_FILE"] = "/var/run/user/10967/bt_u10967"
            os.environ["XDG_RUNTIME_DIR"] = "/run/user/10967"
            token_str = ""
            agent_kill_str = ""
            print("Submitting: ", token_str + add_command + agent_kill_str)
            submission_output, submission_error = subprocess.Popen(
                token_str + add_command + agent_kill_str,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ,
                executable="/bin/bash",
                close_fds=True,
                text=True,
            ).communicate()
            print("JOBSUB OUTPUT", submission_output)
            print("JOBSUB ERROR", submission_error)
            submission_id_parts = ""
            for line in submission_output.splitlines():
                if "job(s) submitted" in line:
                    submission_id_parts = line
                    break
            submission_id_parts = submission_id_parts.split(".")[0].split(" ")
            _remove_file(Path(f"MCOSG_{config.project_id!s}.submit"), missing_ok=True)
            _remove_file(
                Path(f"/tmp/MCOSG_{config.project_id!s}.submit"), missing_ok=True
            )
        if int(config.project_id) > 0:
            self._repository.record_job(
                config.project_id,
                run_number,
                file_number,
                batch_job_id,
                command["num_events"],
            )
        elif int(config.project_id) < 0:
            print("IDNUMLINE:", submission_id_parts)
            if int(submission_id_parts[0]) == bundle_size:
                transactions = []
                trans_block_count = 0
                transaction_stub = (
                    "INSERT INTO Attempts (Job_ID,Creation_Time,BatchSystem,SubmitHost,BatchJobID,Status,WallTime,CPUTime,ThreadsRequested,RAMRequested, RAMUsed) "
                    "VALUES "
                )
                transaction_str = ""
                for job in bundled_jobs:
                    if trans_block_count % 500 == 0 and trans_block_count != 0:
                        transactions.append(transaction_stub + transaction_str[:-2])
                        transaction_str = ""
                    batch_job_id = f"{submission_id_parts[5]!s}.0"
                    if bundle_size > 1:
                        batch_job_id = f"{submission_id_parts[5]!s}.{job[1]!s}"
                    transaction_str += f"""{build_attempt_values(int(job[0]), run_number, job[1], "OSG", f"'{socket.gethostname()!s}'", batch_job_id, command["num_events"], config.num_cores, "Unset")!s}, """
                    trans_block_count += 1
                if transaction_str != "":
                    transactions.append(transaction_stub + transaction_str[:-2])
                for transaction in transactions:
                    print(transaction)
                    print("===================================================")
                    self._repository.execute_transaction(transaction)

    def jsub_add_job(
        self,
        config: "SimulationConfig",
        run_number: Union[int, str],
        file_number: Union[int, str],
        script_to_run: str,
        command: MutableMapping[str, str],
    ) -> None:
        """Write the JSUB request stub and exit without submitting it."""
        job_stub = ""
        if command["custom_tag_string"] != "I_dont_have_one":
            job_stub = f"{command['custom_tag_string']!s}_"
        job_stub = f"{job_stub!s}{run_number!s}_{file_number!s}"
        job_name = f"{config.workflow!s}_{job_stub!s}"
        submission_file = Path("MCJSUB.submit").open("w")
        submission_file.write("<Request>\n")
        submission_file.write(f'<Project name="{config.project!s}"/>\n')
        submission_file.write(f'<Track name="{config.track!s}"/>\n')
        submission_file.write(f'<Name name="{job_name!s}"/>\n')
        submission_file.write(
            (
                f"<Command><![CDATA[ {script_to_run!s} {format_command(command, 'JSUB')!s} "
                "]></Command>\n"
            )
        )
        submission_file.write("<Job> </Job>\n")
        submission_file.write("</Request>\n")
        submission_file.close()
        sys.exit(1)

    def slurm_container_add_job(
        self,
        config: "SimulationConfig",
        run_number: Union[int, str],
        file_number: Union[int, str],
        script_to_run: str,
        command: MutableMapping[str, str],
    ) -> None:
        """Write or submit SLURM container jobs and record tracked jobs or attempts."""
        job_stub = ""
        if command["custom_tag_string"] != "I_dont_have_one":
            job_stub = f"{command['custom_tag_string']!s}_"
        job_stub = f"{job_stub!s}{run_number!s}_{file_number!s}"
        job_name = f"{config.workflow!s}_{job_stub!s}"
        _make_directory(Path(config.output_directory) / "log/")
        submission_file = Path("MCSLURM.submit").open("w")
        submission_file.write("#!/bin/bash -l\n")
        submission_file.write(f"#SBATCH -J {job_name!s}\n")
        submission_file.write("#SBATCH --nodes=1\n")
        submission_file.write(f"#SBATCH --time={config.time_limit!s}\n")
        submission_file.write("#SBATCH --tasks-per-node=1\n")
        submission_file.write(f"#SBATCH --cpus-per-task={config.num_cores!s}\n")
        submission_file.write(f"#SBATCH --mem={config.ram!s}\n")
        submission_file.write("#SBATCH -p production\n")
        submission_file.write(
            f"#SBATCH -o {_log_file(config.output_directory, f'{job_name!s}.out')!s}\n"
        )
        submission_file.write(
            f"#SBATCH -e {_log_file(config.output_directory, f'{job_name!s}.err')!s}\n"
        )
        submission_file.write(
            (
                "singularity exec --bind /scigroup/mcwrapper/ --bind /u --bind /group/halld/ "
                "--bind /scratch/slurm/ --bind /cvmfs --bind /work/osgpool/ --bind "
                "/work/halld --bind /cache/halld --bind /volatile/halld --bind /work/halld2 "
                "/cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_almalinux_9:latest "
                f"$MCWRAPPER_CENTRAL/MakeMC.sh {format_command(command, 'SBATCH_SLURM')!s}\n"
            )
        )
        submission_file.close()
        if int(config.project_id) <= 0:
            add_command = "sbatch MCSLURM.submit"
            if add_command.find(";") != -1 or add_command.find("&") != -1:
                print("Nice try.....you cannot use ; or &")
                sys.exit(1)
        if int(config.project_id) > 0:
            self._repository.record_job(
                config.project_id,
                run_number,
                file_number,
                _unavailable_backend_value("SWIF_ID_NUM"),
                command["num_events"],
            )
        elif int(config.project_id) < 0:
            self._repository.record_attempt(
                abs(int(config.project_id)),
                run_number,
                file_number,
                "SLURM",
                _unavailable_backend_value("SWIF_ID_NUM"),
                command["num_events"],
                config.num_cores,
                "UnSet",
            )
        subprocess.call(add_command, shell=True)
        _remove_file(Path("MCSLURM.submit"), missing_ok=False)

    def slurm_add_job(
        self,
        config: "SimulationConfig",
        run_number: Union[int, str],
        file_number: Union[int, str],
        script_to_run: str,
        command: MutableMapping[str, str],
    ) -> None:
        """Write or submit SLURM jobs and record tracked jobs or attempts."""
        job_stub = ""
        if command["custom_tag_string"] != "I_dont_have_one":
            job_stub = f"{command['custom_tag_string']!s}_"
        job_stub = f"{job_stub!s}{run_number!s}_{file_number!s}"
        job_name = f"{config.workflow!s}_{job_stub!s}"
        _make_directory(Path(config.output_directory) / "log/")
        submission_file = Path("MCSLURM.submit").open("w")
        submission_file.write("#!/bin/bash -l\n")
        submission_file.write(f"#SBATCH -J {job_name!s}\n")
        submission_file.write("#SBATCH --nodes=1\n")
        submission_file.write(f"#SBATCH --time={config.time_limit!s}\n")
        submission_file.write("#SBATCH --tasks-per-node=1\n")
        submission_file.write(f"#SBATCH --cpus-per-task={config.num_cores!s}\n")
        submission_file.write("#SBATCH -p production\n")
        submission_file.write(
            f"#SBATCH -o {_log_file(config.output_directory, f'{job_name!s}.out')!s}\n"
        )
        submission_file.write(
            f"#SBATCH -e {_log_file(config.output_directory, f'{job_name!s}.err')!s}\n"
        )
        submission_file.write(
            f"{script_to_run!s} {format_command(command, 'SLURM')!s}\n"
        )
        submission_file.close()
        if int(config.project_id) <= 0:
            add_command = "sbatch MCSLURM.submit"
            if add_command.find(";") != -1 or add_command.find("&") != -1:
                print("Nice try.....you cannot use ; or &")
                sys.exit(1)
        if int(config.project_id) > 0:
            self._repository.record_job(
                config.project_id,
                run_number,
                file_number,
                _unavailable_backend_value("SWIF_ID_NUM"),
                command["num_events"],
            )
        elif int(config.project_id) < 0:
            self._repository.record_attempt(
                abs(int(config.project_id)),
                run_number,
                file_number,
                "SLURM",
                _unavailable_backend_value("SWIF_ID_NUM"),
                command["num_events"],
                config.num_cores,
                "UnSet",
            )
        subprocess.call(add_command, shell=True)
        _remove_file(Path("MCSLURM.submit"), missing_ok=False)

    def submit(
        self,
        config: "SimulationConfig",
        script_to_run: str,
        command: MutableMapping[str, str],
        run_number: Union[int, str],
        file_number: Union[int, str],
        start_workflow: bool = False,
        container_slurm: bool = True,
    ) -> None:
        """Select a scheduler backend and submit one configured simulation job."""
        if config.batch_system.upper() == "SWIF":
            self.swif_add_job(
                config, run_number, file_number, str(script_to_run), command
            )
            if start_workflow:
                swifrun = f"swif run {config.workflow!s}"
                subprocess.call(swifrun.split(" "))
        elif config.batch_system.upper() == "SWIF2":
            self.swif2_add_job(
                config, run_number, file_number, str(script_to_run), command
            )
            if start_workflow:
                swifrun = f"swif2 run {config.workflow!s}"
                subprocess.call(swifrun.split(" "))
        elif config.batch_system.upper() == "SWIF2CONT":
            self.swif2cont_add_job(
                config, run_number, file_number, str(script_to_run), command
            )
            if start_workflow:
                swifrun = f"swif2 run {config.workflow!s}"
                subprocess.call(swifrun.split(" "))
        elif config.batch_system.upper() == "QSUB":
            self.qsub_add_job(config, run_number, file_number, script_to_run, command)
        elif config.batch_system.upper() == "CONDOR":
            self.condor_add_job(config, run_number, file_number, script_to_run, command)
        elif config.batch_system.upper() == "OSG":
            self.osg_add_job(config, run_number, file_number, script_to_run, command)
        elif config.batch_system.upper() == "SLURMCONT":
            if container_slurm:
                self.slurm_container_add_job(
                    config, run_number, file_number, script_to_run, command
                )
            else:
                self.slurm_add_job(
                    config, run_number, file_number, script_to_run, command
                )
        elif config.batch_system.upper() == "SLURM":
            self.slurm_add_job(config, run_number, file_number, script_to_run, command)

    def _submit_swif(
        self,
        config: "SimulationConfig",
        run_number: Union[int, str],
        file_number: Union[int, str],
        script_to_run: str,
        command: MutableMapping[str, str],
        *,
        scheduler: str,
        container: bool,
    ) -> None:
        """Build and submit a SWIF job with the selected CLI and execution environment."""
        job_stub = ""
        if command["custom_tag_string"] != "I_dont_have_one":
            job_stub = f"{command['custom_tag_string']!s}_"
        job_stub = f"{job_stub!s}{run_number!s}_{file_number!s}"
        if scheduler == "swif":
            log_directory = config.output_directory
            allocation_options = f"-project {config.project!s} -track {config.track!s}"
            fail_save_option = f" -fail-save-dir {config.output_directory!s}"
        else:
            log_directory = config.log_directory
            allocation_options = (
                f"-account {config.account!s} -partition {config.partition!s}"
            )
            fail_save_option = ""
        _make_directory(Path(log_directory) / "log/")
        execution_prefix = ""
        if container:
            execution_prefix = """ singularity exec --bind /scigroup/mcwrapper/ --bind /u --bind /group/halld/ \
--bind /scratch/slurm/ --bind /lustre/enp/swif2 --bind /cvmfs --bind /work/osgpool/ \
--bind /work/halld --bind /cache/halld --bind /volatile/halld --bind /work/halld2 \
/cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_almalinux_9:latest"""
        stdout_path = _log_file(
            log_directory, f"{run_number!s}_stdout.{job_stub!s}.out"
        )
        stderr_path = _log_file(
            log_directory, f"{run_number!s}_stderr.{job_stub!s}.err"
        )
        add_command = f"""{scheduler} add-job -workflow {config.workflow!s} {allocation_options} \
-create -cores {config.num_cores!s} -disk {config.disk!s} -ram {config.ram!s} \
-time {config.time_limit!s} -os {config.os_name!s} \
-stdout {stdout_path!s} -stderr {stderr_path!s} \
-tag run_number {run_number!s} -tag file_number {file_number!s}\
{fail_save_option}{execution_prefix} {script_to_run!s} {format_command(command, "SWIF")!s}"""
        if config.verbose:
            print(f"job add command is \n{add_command!s}")
        if (
            int(config.num_cores) == 1
            and int(config.ram[:-2]) >= 10
            and (config.ram[-2:] == "GB")
        ):
            print(
                (
                    "SciComp has a limit on RAM requested per thread, as RAM is the limiting "
                    "factor."
                )
            )
            print("This will likely cause an AUGER-SUBMIT error.")
            print(
                "Please either increase NCORES or decrease RAM requested and try again."
            )
            sys.exit(1)
        if add_command.find(";") != -1 or add_command.find("&") != -1:
            print("Nice try.....you cannot use ; or &")
            sys.exit(1)
        batch_job_id = "-1"
        if int(config.project_id) <= 0:
            print(add_command)
            submission_output = subprocess.check_output(add_command.split(" "))
            print(submission_output.decode())
            submission_id_parts = (
                submission_output.decode().split("\n")[0].strip().split("=")
            )
            if len(submission_id_parts) == 2:
                batch_job_id = str(submission_id_parts[1])
        if int(config.project_id) > 0:
            self._repository.record_job(
                config.project_id,
                run_number,
                file_number,
                batch_job_id,
                command["num_events"],
            )
        elif int(config.project_id) < 0:
            self._repository.record_attempt(
                abs(int(config.project_id)),
                run_number,
                file_number,
                "SWIF",
                batch_job_id,
                command["num_events"],
                config.num_cores,
                config.ram,
            )


def _unavailable_backend_value(name: str) -> NoReturn:
    """Fail when a scheduler stub needs a value its implementation does not capture."""
    raise NameError(f"name '{name}' is not defined")


def split_file_on_run_number(input_name: str) -> Dict[int, int]:
    """Split reconstructed HDDM records into files by run number."""
    import hddm_r

    fout = {}
    outevts = {}
    for rec in hddm_r.istream(input_name):
        evt = rec.getReconstructedPhysicsEvent()
        if evt.runNo not in fout:
            outfname = "{0}_run{1}.hddm".format(input_name[:-5], evt.runNo)
            print("Creating output file {0} ...".format(outfname))
            fout[evt.runNo] = hddm_r.ostream(outfname)
            outevts[evt.runNo] = 0
        else:
            outevts[evt.runNo] += 1
        fout[evt.runNo].write(rec)
    print(fout)
    print(outevts)
    return outevts


def count_hddm_events(file: str) -> int:
    """Count simulated HDDM records in an input file."""
    return sum((1 for r in hddm_s.istream(file)))


def load_ccdb() -> Any:
    """Open the calibration provider used for photon flux calculations."""
    sqlite_connect_str = "mysql://ccdb_user@hallddb.jlab.org/ccdb"
    provider = ccdb.AlchemyProvider()
    provider.connect(sqlite_connect_str)
    provider.authentication.current_user_name = "psflux_user"
    return provider


def ps_acceptance(
    energy: float, normalization: float, minimum: float, maximum: float
) -> float:
    """Calculate pair-spectrometer acceptance for a photon energy."""
    if energy > 2.0 * minimum and energy < minimum + maximum:
        return normalization * (1 - 2.0 * minimum / energy)
    elif energy >= minimum + maximum:
        return normalization * (2.0 * maximum / energy - 1)
    return 0.0


class FluxCalculator:
    """Read calibration tables and integrate tagged or untagged flux."""

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    def untagged_flux(self, run: Sequence[Any], emin: float, emax: float) -> float:
        """Integrate untagged photon flux across the requested energy range."""
        # The 2025 run range requires recon-2025_01-ver03 random-trigger inputs.
        if 130000 < run[0] and run[0] < 139999:
            pelican_ls_string = f"pelican object ls osdf://jlab-osdf/gluex/osgpool/random_triggers/recon-2025_01-ver03/run{run[0]!s}_random.hddm"
            token_str = "eval `ssh-agent`; /usr/bin/ssh-add; "
            agent_kill_str = "; ssh-agent -k"
            my_env = os.environ.copy()
            p = subprocess.Popen(
                token_str + pelican_ls_string + agent_kill_str,
                env=my_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=-1,
                shell=True,
                close_fds=True,
            )
            output, errors = p.communicate()
            if "object not found" in str(errors):
                print(
                    "Missing random hddm files for run number = %d, skipping generation"
                    % run[0]
                )
                return -1.0
        flux = 0.0
        variation = "default"
        calibtime = datetime.now()
        energy_calibtime = calibtime
        livetime_ratio = 0.0
        try:
            livetime_assignment = self._provider.get_assignment(
                "/PHOTON_BEAM/pair_spectrometer/lumi/trig_live",
                run[0],
                variation,
                calibtime,
            )
            livetime = livetime_assignment.constant_set.data_table
            if float(livetime[3][1]) > 0.0:
                livetime_ratio = float(livetime[0][1]) / float(livetime[3][1])
            else:
                livetime_ratio = 1.0
        except BaseException:
            livetime_ratio = 1.0
        converter_thickness = run[2]
        converter_length = 7.5e-05
        if converter_thickness == "Be 750um":
            converter_length = 0.00075
        elif converter_thickness != "Be 75um":
            print(
                "Unknown converter thickness for run %s: %s, assuming Be 75um"
                % (run[0], run[2])
            )
        beryllium_radiation_length = 0.3528
        radiation_length = converter_length / beryllium_radiation_length
        scale = livetime_ratio * 1.0 / (7 / 9.0 * radiation_length)
        try:
            photon_endpoint_assignment = self._provider.get_assignment(
                "/PHOTON_BEAM/endpoint_energy", run[0], variation, energy_calibtime
            )
            photon_endpoint = photon_endpoint_assignment.constant_set.data_table
            tagh_untagged_flux_assignment = self._provider.get_assignment(
                "/PHOTON_BEAM/pair_spectrometer/lumi/tagh/untagged",
                run[0],
                variation,
                calibtime,
            )
            tagh_untagged_flux = tagh_untagged_flux_assignment.constant_set.data_table
            tagh_scaled_energy_assignment = self._provider.get_assignment(
                "/PHOTON_BEAM/hodoscope/scaled_energy_range",
                run[0],
                variation,
                energy_calibtime,
            )
            tagh_scaled_energy_table = (
                tagh_scaled_energy_assignment.constant_set.data_table
            )
            ps_accept_assignment = self._provider.get_assignment(
                "/PHOTON_BEAM/pair_spectrometer/lumi/PS_accept",
                run[0],
                variation,
                calibtime,
            )
            ps_acceptance_table = ps_accept_assignment.constant_set.data_table
        except Exception as e:
            print(e)
            print("Missing flux for run number = %d, skipping generation" % run[0])
            return -1.0
        for tagh_flux, tagh_scaled_energy in zip(
            tagh_untagged_flux, tagh_scaled_energy_table
        ):
            tagh_energy = (
                float(photon_endpoint[0][0])
                * (float(tagh_scaled_energy[1]) + float(tagh_scaled_energy[2]))
                / 2.0
            )
            if tagh_energy < emin or tagh_energy > emax:
                continue
            acceptance = ps_acceptance(
                tagh_energy,
                float(ps_acceptance_table[0][0]),
                float(ps_acceptance_table[0][1]),
                float(ps_acceptance_table[0][2]),
            )
            if acceptance <= 0.0:
                continue
            flux = flux + float(tagh_flux[1]) * scale / acceptance
        return flux

    def tagged_flux(self, run: Sequence[Any], emin: float, emax: float) -> float:
        """Integrate tagged hodoscope and microscope photon flux."""
        flux = 0.0
        variation = "default"
        calibtime = datetime.now()
        energy_calibtime = calibtime
        livetime_ratio = 0.0
        try:
            livetime_assignment = self._provider.get_assignment(
                "/PHOTON_BEAM/pair_spectrometer/lumi/trig_live",
                run[0],
                variation,
                calibtime,
            )
            livetime = livetime_assignment.constant_set.data_table
            if float(livetime[3][1]) > 0.0:
                livetime_ratio = float(livetime[0][1]) / float(livetime[3][1])
            else:
                livetime_ratio = 1.0
        except BaseException:
            livetime_ratio = 1.0
        converter_thickness = run[2]
        # Tagged flux uses a 750 micrometer default, including Be 75um labels.
        converter_length = 0.00075
        if converter_thickness == "Be 750um":
            converter_length = 0.00075
        elif converter_thickness != "Be 75um":
            print(
                "Unknown converter thickness for run %s: %s, assuming Be 750um"
                % (run[0], run[2])
            )
        beryllium_radiation_length = 0.3528
        radiation_length = converter_length / beryllium_radiation_length
        scale = livetime_ratio * 1.0 / (7 / 9.0 * radiation_length)
        try:
            photon_endpoint_assignment = self._provider.get_assignment(
                "/PHOTON_BEAM/endpoint_energy", run[0], variation, energy_calibtime
            )
            photon_endpoint = photon_endpoint_assignment.constant_set.data_table
            photon_endpoint_calib_assignment = self._provider.get_assignment(
                "/PHOTON_BEAM/hodoscope/endpoint_calib",
                run[0],
                variation,
                energy_calibtime,
            )
            photon_endpoint_calib = (
                photon_endpoint_calib_assignment.constant_set.data_table
            )
            tagh_tagged_flux_assignment = self._provider.get_assignment(
                "/PHOTON_BEAM/pair_spectrometer/lumi/tagh/tagged",
                run[0],
                variation,
                calibtime,
            )
            tagh_tagged_flux = tagh_tagged_flux_assignment.constant_set.data_table
            tagh_scaled_energy_assignment = self._provider.get_assignment(
                "/PHOTON_BEAM/hodoscope/scaled_energy_range",
                run[0],
                variation,
                energy_calibtime,
            )
            tagh_scaled_energy_table = (
                tagh_scaled_energy_assignment.constant_set.data_table
            )
            tagm_tagged_flux_assignment = self._provider.get_assignment(
                "/PHOTON_BEAM/pair_spectrometer/lumi/tagm/tagged",
                run[0],
                variation,
                calibtime,
            )
            tagm_tagged_flux = tagm_tagged_flux_assignment.constant_set.data_table
            tagm_scaled_energy_assignment = self._provider.get_assignment(
                "/PHOTON_BEAM/microscope/scaled_energy_range",
                run[0],
                variation,
                energy_calibtime,
            )
            tagm_scaled_energy_table = (
                tagm_scaled_energy_assignment.constant_set.data_table
            )
            ps_accept_assignment = self._provider.get_assignment(
                "/PHOTON_BEAM/pair_spectrometer/lumi/PS_accept",
                run[0],
                variation,
                calibtime,
            )
            ps_acceptance_table = ps_accept_assignment.constant_set.data_table
        except Exception as e:
            print(e)
            print("Missing flux for run number = %d, skipping generation" % run[0])
            return -1.0
        for tagh_flux, tagh_scaled_energy in zip(
            tagh_tagged_flux, tagh_scaled_energy_table
        ):
            tagh_energy = (
                float(photon_endpoint_calib[0][0])
                * (float(tagh_scaled_energy[1]) + float(tagh_scaled_energy[2]))
                / 2.0
                + float(photon_endpoint[0][0])
                - float(photon_endpoint_calib[0][0])
            )
            if tagh_energy < emin or tagh_energy > emax:
                continue
            acceptance = ps_acceptance(
                tagh_energy,
                float(ps_acceptance_table[0][0]),
                float(ps_acceptance_table[0][1]),
                float(ps_acceptance_table[0][2]),
            )
            if acceptance <= 0.0:
                continue
            flux = flux + float(tagh_flux[1]) * scale / acceptance
        for tagm_flux, tagm_scaled_energy in zip(
            tagm_tagged_flux, tagm_scaled_energy_table
        ):
            tagm_energy = (
                float(photon_endpoint_calib[0][0])
                * (float(tagm_scaled_energy[1]) + float(tagm_scaled_energy[2]))
                / 2.0
                + float(photon_endpoint[0][0])
                - float(photon_endpoint_calib[0][0])
            )
            if tagm_energy < emin or tagm_energy > emax:
                continue
            acceptance = ps_acceptance(
                tagm_energy,
                float(ps_acceptance_table[0][0]),
                float(ps_acceptance_table[0][1]),
                float(ps_acceptance_table[0][2]),
            )
            if acceptance <= 0.0:
                continue
            flux = flux + float(tagm_flux[1]) * scale / acceptance
        return flux


class RandomTriggerCatalog:
    """Look up and scan random-trigger files for simulation jobs."""

    def __init__(self, repository: JobRepository) -> None:
        self._repository = repository

    def get_count(
        self,
        background: str,
        random_background_tag: str,
        batch_system: str,
        run_number: Union[int, str],
    ) -> int:
        """Find or scan a random-trigger file and cache its event count."""
        try:
            print("GETTING RANDOM COUNT")
            if background[0:3] != "Ran" and background[0:3] != "loc":
                return -1
            style = background
            if background[0:3] == "loc":
                style = "loc"
            path_base = "/work/osgpool/halld/random_triggers/"
            if style == "Random":
                path_base = f"{path_base!s}{random_background_tag!s}/"
            else:
                path_base = background[4:]
            formatted_run_number = ""
            for i in range(len(str(run_number)), 6):
                formatted_run_number += "0"
            formatted_run_number = formatted_run_number + str(run_number)
            path_base = f"{path_base!s}run{formatted_run_number!s}_random.hddm"
            running_hostname = socket.gethostname()
            if (
                running_hostname == "scosg16.jlab.org"
                or running_hostname == "scosg20.jlab.org"
                or "scosg2201" in running_hostname
            ):
                path_base = f"/tmp/{random_background_tag!s}/run{formatted_run_number!s}_random.hddm"
            print("final path base:", path_base)
            realpath = str(Path(path_base).resolve())
            print("real path:", realpath)
            queryrand = (
                "SELECT Num_Events "
                "FROM Randoms "
                f'WHERE Style="{style!s}" '
                f'&& Tag="{random_background_tag!s}" '
                f"&& Run_Number={run_number!s}"
            )
            print(queryrand)
            self._repository.cursor.execute(queryrand)
            matches = self._repository.cursor.fetchall()
            if len(matches) == 0:
                print("Attempting to scan and tag this random trigger file")
                running_hostname = socket.gethostname()
                if (
                    running_hostname == "scosg16.jlab.org"
                    or running_hostname == "scosg20.jlab.org"
                    or "scosg2201" in running_hostname
                ):
                    _make_directory(Path("/tmp") / f"{random_background_tag!s}")
                    pelican_get_string = (
                        f"pelican object get osdf://jlab-osdf/gluex/osgpool/random_triggers/{random_background_tag!s}/run{formatted_run_number!s}_random.hddm "
                        f"/tmp/{random_background_tag!s}"
                    )
                    token_str = "eval `ssh-agent`; /usr/bin/ssh-add; "
                    agent_kill_str = "; ssh-agent -k"
                    print(token_str + pelican_get_string + agent_kill_str)
                    os.environ["BEARER_TOKEN_FILE"] = "/var/run/user/10967/bt_u10967"
                    os.environ["XDG_RUNTIME_DIR"] = "/run/user/10967"
                    my_env = os.environ.copy()
                    p = subprocess.Popen(
                        token_str + pelican_get_string + agent_kill_str,
                        env=my_env,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        bufsize=-1,
                        shell=True,
                        close_fds=True,
                    )
                    output, errors = p.communicate()
                if not Path(realpath).is_file():
                    print("can't find file to scan.")
                    return -1
                file_size = Path(realpath).stat().st_size
                event_count = count_hddm_events(realpath)
                addquery = (
                    "INSERT INTO Randoms (Style,Tag,Path,Size,Num_Events,Run_Number) "
                    f'VALUES ("{style!s}","{random_background_tag!s}","{realpath!s}","{file_size!s}",{event_count!s},{run_number!s})'
                )
                self._repository.cursor.execute(addquery)
                self._repository.connection.commit()
                print(f"COUNT: {event_count!s}")
                _remove_file(
                    Path("/tmp")
                    / f"{random_background_tag!s}/run{formatted_run_number!s}_random.hddm",
                    missing_ok=True,
                )
                return event_count
            elif len(matches) == 1:
                print("Matched a file!")
                print(matches[0][0])
                return matches[0][0]
            else:
                value = matches[0][0]
                for match in matches:
                    if match[0] != value:
                        print("AMBIGUOUS!")
                        return -1
                return value
        except Exception as e:
            print(e)
            pass
        return -1


def show_help() -> str:
    """Return help text for configuration overrides accepted by the CLI."""
    return """variation=%s where %s is a valid jana_calib_context variation string (default is "mc")
 per_file=%i where %i is the number of events you want per file/job (default is 10000)
 base_file_number=%i where %i is the starting number of the files/jobs (default is 0)
 numthreads=%i sets the number of threads to use to %i.  Note that this will overwrite the NCORES set in MC.config
 generate=[0/1] where 0 means that the generation step and any subsequent step will not run (default is 1)
 geant=[0/1] where 0 means that the geant step and any subsequent step will not run (default is 1)
 mcsmear=[0/1] where 0 means that the mcsmear step and any subsequent step will not run (default is 1)
 recon=[0/1] where 0 means that the reconstruction step will not run (default is 1)
 cleangenerate=[0/1] where 0 means that the generation step will not be cleaned up after use (default is 1)
 cleangeant=[0/1] where 0 means that the geant step will not be cleaned up after use (default is 1)
 cleanmcsmear=[0/1] where 0 means that the mcsmear step will not be cleaned up after use (default is 1)
 cleanrecon=[0/1]where 0 means that the reconstruction step will not be cleaned up after running (default is 0)
 batch=[0/1/2] where 1 means that jobs will be submitted, 2 will do the same as 1 but also run the workflow in the case of swif(2) (default is 0 [interactive])
 logdir=[path] will direct the .out and .err files to the specified path for qsub
"""


class SimulationConfig:
    """Load simulation settings while preserving config-file and CLI precedence."""

    _CONFIG_FIELDS = {
        "PROJECT": "project",
        "ACCOUNT": "account",
        "TRACK": "track",
        "PARTITION": "partition",
        "EXPERIMENT": "experiment",
        "NCORES": "num_cores",
        "DISK": "disk",
        "RAM": "ram",
        "TIMELIMIT": "time_limit",
        "OS": "os_name",
        "DATA_OUTPUT_BASE_DIR": "output_directory",
        "ENVIRONMENT_FILE": "environment_file",
        "SIM_ENVIRONMENT_FILE": "sim_environment_file",
        "ANA_ENVIRONMENT_FILE": "ana_environment_file",
        "GENERATOR": "generator",
        "GEANT_VERSION": "geant_version",
        "CUSTOM_MAKEMC": "custom_makemc",
        "CUSTOM_GCONTROL": "custom_gcontrol",
        "EBEAM_ENERGY": "ebeam_energy",
        "EBEAM_CURRENT": "ebeam_current",
        "COHERENT_PEAK": "coherent_peak",
        "RADIATOR_THICKNESS": "radiator_thickness",
        "GEN_MIN_ENERGY": "min_generator_energy",
        "GEN_MAX_ENERGY": "max_generator_energy",
        "TAG": "tag_string",
        "CUSTOM_PLUGINS": "custom_plugins",
        "CUSTOM_ANA_PLUGINS": "custom_ana_plugins",
        "RUNNING_DIRECTORY": "running_directory",
        "RECON_VERSION": "recon_version",
        "RECON_CALIBTIME": "recon_calibtime",
        "ANA_VERSION": "ana_version",
        "ANA_CALIBTIME": "ana_calibtime",
        "CCDBSQLITEPATH": "ccdb_sqlite_path",
        "RCDBSQLITEPATH": "rcdb_sqlite_path",
        "NOSECONDARIES": "no_geant_secondaries",
        "NOSIPMSATURATION": "no_bcal_sipm_saturation",
        "CCDB_FLUX_MCWRAPPER": "wrapper_flux_version",
        "CCDB_FLUX_GENERATOR": "generator_flux_version",
    }
    _OS_CONFIG_FIELDS = {
        "GENERATOR_OS": "generator_os",
        "POSTGEN_OS": "postgen_os",
        "SIMULATION_OS": "simulation_os",
        "MCSMEAR_OS": "mcsmear_os",
        "RECON_OS": "recon_os",
        "ANA_OS": "ana_os",
    }
    account: str
    ana_environment_file: str
    ana_calibtime: str
    ana_os: str
    ana_version: str
    base_file_number: int
    batchrun: int
    batch_system: str
    background: str
    background_rate: str
    background_tagger_only: Union[int, str]
    calibtime: str
    generator_flux_version: str
    wrapper_flux_version: str
    clean_geant: int
    clean_gen: int
    clean_recon: int
    clean_mcsmear: int
    coherent_peak: str
    condor_options: List[str]
    config_file: str
    custom_ana_plugins: str
    custom_gcontrol: str
    custom_makemc: str
    custom_plugins: str
    output_directory: str
    disk: str
    environment_file: str
    num_events: int
    experiment: str
    flux_histogram: str
    flux_to_generate: str
    do_geant: int
    geant_version: Union[int, str]
    generator_config: str
    generator: str
    generator_os: str
    generator_post: str
    generator_post_config: str
    generator_post_configdec: str
    generator_post_configevt: str
    do_gen: int
    is_submitter: Union[int, str]
    location: str
    log_directory: str
    max_generator_energy: str
    mcsmear_os: str
    min_generator_energy: str
    num_cores: str
    no_geant_secondaries: Union[int, str]
    no_bcal_sipm_saturation: Union[int, str]
    os_name: str
    partition: str
    events_per_file: int
    polarization_histogram: str
    polarization_to_generate: str
    postgen_os: str
    project: str
    project_id: Any
    queue_name: str
    radiator_thickness: str
    ram: str
    random_background_rate: Union[float, str]
    random_background_tag: str
    num_rand_trigs: int
    rcdb_query: str
    do_recon: int
    recon_calibtime: str
    recon_os: str
    recon_version: str
    running_directory: str
    run_number: str
    shell_to_use: str
    sim_environment_file: str
    simulation_os: str
    do_mcsmear: int
    mcsmear_notag: str
    tag_string: str
    time_limit: str
    to_bundle: bool
    track: str
    verbose: bool
    variation: str
    vertex_area: str
    vertex_length: str
    workflow: str
    ccdb_sqlite_path: str
    ebeam_current: str
    ebeam_energy: str
    rcdb_sqlite_path: str

    def __init__(self, config_file: str, run_number: str, num_events: int) -> None:
        self.config_file = config_file
        self.run_number = run_number
        self.num_events = num_events
        self.verbose = False
        self.tag_string = "I_dont_have_one"
        self.output_directory = "UNKNOWN_LOCATION"
        self.rcdb_query = ""
        self.environment_file = "my-environment-file"
        self.sim_environment_file = "no_Sim_env"
        self.ana_environment_file = "no_Analysis_env"
        self.generator = "genr8"
        self.generator_config = "NA"
        self.generator_post = "No"
        self.generator_post_config = "Default"
        self.generator_post_configevt = "Default"
        self.generator_post_configdec = "Default"
        self.ebeam_energy = "rcdb"
        self.ebeam_current = "rcdb"
        self.coherent_peak = "rcdb"
        self.flux_to_generate = "ccdb"
        self.flux_histogram = "unset"
        self.polarization_to_generate = "0.4"
        self.polarization_histogram = "unset"
        self.min_generator_energy = "3"
        self.max_generator_energy = "12"
        self.wrapper_flux_version = "untagged"
        self.generator_flux_version = "untagged"
        try:
            starting_run_number = int(str(self.run_number).split("-")[0])
            if (
                60000 <= starting_run_number
                and starting_run_number <= 69999
                or (80000 <= starting_run_number and starting_run_number <= 89999)
                or (110000 <= starting_run_number and starting_run_number <= 119999)
            ):
                print("PrimEx run detected. Will use tagged flux by default.")
                self.wrapper_flux_version = "tagged"
                self.generator_flux_version = "tagged"
        except Exception:
            print("Something went wrong getting starting run number")
        self.radiator_thickness = "rcdb"
        self.background_rate = "rcdb"
        self.background_tagger_only = "0"
        self.running_directory = "./"
        self.ccdb_sqlite_path = "no_sqlite"
        self.rcdb_sqlite_path = "no_sqlite"
        self.geant_version = 4
        self.vertex_area = "ccdb"
        self.vertex_length = "29.5"
        self.background = "DEFAULT"
        self.num_rand_trigs = -1
        self.random_background_tag = "none"
        self.random_background_rate = 1.0
        self.mcsmear_notag = "0"
        self.custom_makemc = "DEFAULT"
        self.custom_gcontrol = "0"
        self.custom_plugins = "None"
        self.custom_ana_plugins = "None"
        self.generator_os = "LOCAL"
        self.postgen_os = "LOCAL"
        self.simulation_os = "LOCAL"
        self.mcsmear_os = "LOCAL"
        self.recon_os = "LOCAL"
        self.ana_os = "LOCAL"
        self.batch_system = "NULL"
        self.queue_name = "DEF"
        self.project = "gluex"
        self.track = "simulation"
        self.account = "halld"
        self.partition = "production"
        self.experiment = "GlueX"
        self.condor_options = []
        self.num_cores = "8"
        self.disk = "10GB"
        self.ram = "20GB"
        self.time_limit = "300minutes"
        self.os_name = "el9"
        self.project_id = 0
        self.is_submitter = 0
        self.to_bundle = False
        self.variation = "mc"
        self.calibtime = "notime"
        self.recon_version = "mc"
        self.recon_calibtime = "notime"
        self.ana_version = "mc"
        self.ana_calibtime = "notime"
        self.base_file_number = 0
        self.events_per_file = 10000
        self.do_gen = 1
        self.do_geant = 1
        self.do_mcsmear = 1
        self.do_recon = 1
        self.clean_gen = 1
        self.clean_geant = 1
        self.clean_mcsmear = 1
        self.clean_recon = 0
        self.batchrun = 0
        self.no_geant_secondaries = 0
        self.no_bcal_sipm_saturation = 0
        self.shell_to_use = "csh"
        self.location = "auto"

    def read(self) -> bool:
        """Read config settings and apply experiment defaults before CLI overrides."""
        with Path(self.config_file).open("r") as config_file:
            for line in config_file:
                if len(line) == 0:
                    continue
                if line[0] == "#":
                    continue
                parts = line.split("#")[0].split("=", 1)
                if len(parts) == 1:
                    continue
                if (
                    len(parts) > 2
                    and str(parts[0]).upper() != "VARIATION"
                    and (str(parts[0]).upper() != "RCDB_QUERY")
                ):
                    print("warning! I am going to have a really difficult time with:")
                    print(line)
                    print("I'm going to just ignore it and hope it isn't a problem....")
                    continue
                rm_comments = []
                if len(parts) > 1:
                    rm_comments = parts[len(parts) - 1].split("#")
                j = -1
                for i in parts:
                    j = j + 1
                    i = i.strip()
                    parts[j] = i
                print(parts[0], "found")
                print("will set to", rm_comments[0].strip())
                key = str(parts[0]).upper()
                if key in self._CONFIG_FIELDS:
                    setattr(self, self._CONFIG_FIELDS[key], rm_comments[0].strip())
                elif key in self._OS_CONFIG_FIELDS:
                    setattr(
                        self,
                        self._OS_CONFIG_FIELDS[key],
                        rm_comments[0].strip().upper(),
                    )
                elif str(parts[0]).upper() == "VERBOSE":
                    if (
                        rm_comments[0].strip().upper() == "TRUE"
                        or rm_comments[0].strip() == "1"
                    ):
                        self.verbose = True
                elif str(parts[0]).upper() == "CONDOR_MAGIC":
                    self.condor_options.append(rm_comments[0].strip())
                elif str(parts[0]).upper() == "VERTEX_VOLUME":
                    vertex_volume = rm_comments[0].strip()
                    vertex_parts = vertex_volume.split(":")
                    if len(vertex_parts) == 1:
                        self.vertex_length = vertex_parts[0]
                    elif len(vertex_parts) == 2:
                        self.vertex_area = vertex_parts[0]
                        self.vertex_length = vertex_parts[1]
                elif str(parts[0]).upper() == "WORKFLOW_NAME":
                    self.workflow = rm_comments[0].strip()
                    if self.workflow.find(";") != -1 or self.workflow.find("&") != -1:
                        print("Nice try.....you cannot use ; or & in the name")
                        sys.exit(1)
                elif str(parts[0]).upper() == "GENERATOR_CONFIG":
                    self.generator_config = rm_comments[0].strip()
                    if len(self.generator_config.split(" ")) != 1:
                        print(
                            self.generator_config,
                            "is an invalid GENERATOR_CONFIG parameter. Please fix in",
                            self.config_file,
                            "exiting...",
                        )
                        sys.exit(1)
                elif str(parts[0]).upper() == "GENERATOR_POSTPROCESS":
                    postprocessing = rm_comments[0].strip()
                    postprocessing_parts = postprocessing.split(":")
                    self.generator_post = postprocessing_parts[0]
                    if len(postprocessing_parts) == 2:
                        self.generator_post_config = (
                            "Default"
                            if postprocessing_parts[1].lower() == "default"
                            else postprocessing_parts[1]
                        )
                    elif len(postprocessing_parts) == 3:
                        self.generator_post_config = (
                            "Default"
                            if postprocessing_parts[1].lower() == "default"
                            else postprocessing_parts[1]
                        )
                        self.generator_post_configevt = (
                            "Default"
                            if postprocessing_parts[2].lower() == "default"
                            else postprocessing_parts[2]
                        )
                    elif len(postprocessing_parts) == 4:
                        self.generator_post_config = (
                            "Default"
                            if postprocessing_parts[1].lower() == "default"
                            else postprocessing_parts[1]
                        )
                        self.generator_post_configevt = (
                            "Default"
                            if postprocessing_parts[2].lower() == "default"
                            else postprocessing_parts[2]
                        )
                        self.generator_post_configdec = (
                            "Default"
                            if postprocessing_parts[3].lower() == "default"
                            else postprocessing_parts[3]
                        )
                    elif len(postprocessing_parts) == 1:
                        self.generator_post = postprocessing
                elif str(parts[0]).upper() == "RANDBGRATE":
                    print("RANDBGRATE")
                    self.random_background_rate = rm_comments[0].strip()
                elif str(parts[0]).upper() == "BKG":
                    bkg_parts = rm_comments[0].strip().split("+")
                    for part in bkg_parts:
                        subparts = part.split(":")
                        if len(subparts) > 2:
                            print(f"Error in BKG Parsing: {part!s}")
                            return False
                        if subparts[0].upper() == "TAGONLY":
                            self.background_tagger_only = 1
                            if self.background == "DEFAULT":
                                self.background = "TagOnly"
                            if len(subparts) == 2:
                                self.background_rate = subparts[1]
                        elif subparts[0].upper() == "BEAMPHOTONS":
                            self.background = subparts[0]
                            if len(subparts) == 2:
                                self.background_rate = subparts[1]
                        elif (
                            subparts[0].upper() == "RANDOM"
                            or subparts[0].upper() == "DEFAULT"
                        ):
                            self.background = subparts[0]
                            if len(subparts) == 2:
                                self.random_background_tag = subparts[1]
                        elif subparts[0].upper() == "NOTAG":
                            self.mcsmear_notag = "1"
                        else:
                            self.background = part
                elif str(parts[0]).upper() == "BATCH_SYSTEM":
                    batch_sys_parts = rm_comments[0].strip().split(":")
                    self.batch_system = batch_sys_parts[0]
                    if len(batch_sys_parts) > 1:
                        self.queue_name = batch_sys_parts[1]
                elif str(parts[0]).upper() == "VARIATION":
                    recomb = "=".join(parts)
                    print(recomb)
                    space_parts = recomb.split(" ")
                    if len(space_parts) == 2:
                        self.variation = space_parts[0].split("=")[1]
                        self.calibtime = space_parts[1].split("=")[1]
                    elif len(space_parts) == 1:
                        self.variation = space_parts[0].split("=")[1]
                    else:
                        print(
                            (
                                "VARIATION improperly set and is not parseable.  Please configure "
                                "the VARIATION properly in"
                            ),
                            self.config_file,
                        )
                        sys.exit(1)
                    if (
                        self.variation == ""
                        or len(self.variation.split(" ")) != 1
                        or self.calibtime == "timegoeshere"
                    ):
                        print(
                            "VARIATION improperly set.  Please configure the VARIATION properly in",
                            self.config_file,
                        )
                        sys.exit(1)
                elif str(parts[0]).upper() == "RCDB_QUERY":
                    query = line.split("#")[0][line.split("#")[0].find("=") + 1 :]
                    self.rcdb_query = query
                elif str(parts[0]).upper() == "FLUX_TO_GEN":
                    fluxbits = rm_comments[0].strip().split(":")
                    if len(fluxbits) == 2:
                        self.flux_to_generate = fluxbits[0]
                        self.flux_histogram = fluxbits[1]
                    elif len(fluxbits) == 1:
                        if str(fluxbits[0]).upper() == "COBREMS":
                            self.flux_to_generate = "cobrems"
                elif str(parts[0]).upper() == "POL_TO_GEN":
                    polbits = rm_comments[0].strip().split(":")
                    if len(polbits) == 2:
                        self.polarization_to_generate = polbits[0]
                        self.polarization_histogram = polbits[1]
                    elif len(polbits) == 1:
                        self.polarization_to_generate = polbits[0]
                        if self.flux_to_generate == "cobrems":
                            self.polarization_histogram = "cobrems"
                else:
                    print(f"unknown config parameter!! {parts[0]!s}")
        if self.experiment == "GlueX" and self.project != "gluex":
            self.experiment = self.project
        if self.variation == "mc_cpp":
            print(
                (
                    "ERROR: variation=mc_cpp is deprecated and not supported. Please use "
                    "a variation=mc and set EXPERIMENT=CPP."
                )
            )
            sys.exit(1)
        if str(self.experiment).upper() == "CPP" and self.vertex_length == "29.5":
            self.vertex_length = "0.02806"
            print("CPP experiment detected. Setting target length to 0.02806 cm.")
        self.log_directory = self.output_directory
        if self.generator_config == "":
            self.generator_config = "NA"
        return True

    def apply_options(self, args: Sequence[str]) -> None:
        """Apply the supported key=value arguments in their supplied order."""
        for argu in args:
            argfound = 0
            flag = argu.split("=")
            if len(flag) < 2:
                continue
            else:
                if flag[0] == "variation":
                    argfound = 1
                    self.variation = flag[1]
                    self.calibtime = "notime"
                if flag[0] == "calibtime":
                    argfound = 1
                    self.calibtime = flag[1]
                if flag[0] == "per_file":
                    argfound = 1
                    self.events_per_file = int(flag[1])
                if flag[0] == "base_file_number":
                    argfound = 1
                    self.base_file_number = int(flag[1])
                if flag[0] == "generate":
                    argfound = 1
                    self.do_gen = int(flag[1])
                if flag[0] == "geant":
                    argfound = 1
                    self.do_geant = int(flag[1])
                if flag[0] == "mcsmear":
                    argfound = 1
                    self.do_mcsmear = int(flag[1])
                if flag[0] == "recon":
                    argfound = 1
                    self.do_recon = int(flag[1])
                if flag[0] == "cleangenerate":
                    argfound = 1
                    self.clean_gen = int(flag[1])
                if flag[0] == "cleangeant":
                    argfound = 1
                    self.clean_geant = int(flag[1])
                if flag[0] == "cleanmcsmear":
                    argfound = 1
                    self.clean_mcsmear = int(flag[1])
                if flag[0] == "cleanrecon":
                    argfound = 1
                    self.clean_recon = int(flag[1])
                if flag[0] == "batch":
                    argfound = 1
                    self.batchrun = int(flag[1])
                if flag[0] == "numthreads":
                    argfound = 1
                    self.num_cores = str(flag[1])
                if flag[0] == "logdir":
                    argfound = 1
                    self.log_directory = str(flag[1])
                if flag[0] == "projid":
                    argfound = 1
                    self.project_id = str(flag[1])
                if flag[0] == "shell":
                    argfound = 1
                    self.shell_to_use = str(flag[1])
                if flag[0] == "submitter":
                    argfound = 1
                    self.is_submitter = str(flag[1])
                if flag[0] == "tobundle":
                    argfound = 1
                    if str(flag[1]) == "1":
                        self.to_bundle = True
                if argfound == 0:
                    print(f"WARNING OPTION: {argu!s} NOT FOUND!")
        if self.variation == "mc_cpp":
            print(
                (
                    "ERROR: variation=mc_cpp is deprecated and not supported. Please use "
                    "variation=mc, and in your MC.config set EXPERIMENT=CPP."
                )
            )
            sys.exit(1)


class SimulationRunner:
    """Resolve execution settings, distribute events, and run simulation jobs."""

    def __init__(
        self,
        config: SimulationConfig,
        repository: JobRepository,
        arguments: Sequence[str],
    ) -> None:
        self._config = config
        self._repository = repository
        self._arguments = arguments
        self._submitter = BatchSubmitter(repository)
        self._random_triggers = RandomTriggerCatalog(repository)

    def run(self) -> None:
        """Prepare wrapper arguments and execute a single run or a run range."""
        if self._config.output_directory == "UNKNOWN_LOCATION":
            print(
                (
                    f"I doubt that the system will find the output directory: {self._config.output_directory!s} "
                    "so I am saving you the embarrassment of trying and stopping this "
                    "now"
                )
            )
            return
        print("WILL BE BUNDLED", self._config.to_bundle)
        name_breakdown = self._config.generator_config.split("/")
        channel = name_breakdown[len(name_breakdown) - 1].split(".")[0]
        if self._config.batchrun == 0 or self._config.batch_system == "NULL":
            print(f"Locally simulating {self._arguments[2]!s} {channel!s} Events")
        else:
            print(
                (
                    f"Creating {self._config.workflow!s} to simulate {self._arguments[2]!s} "
                    f"{channel!s} Events"
                )
            )
        self._resolve_stage_os()
        files_to_generate = int(self._config.num_events / self._config.events_per_file)
        remaining_events = self._config.num_events % self._config.events_per_file
        script_to_run = cast(str, os.environ.get("MCWRAPPER_CENTRAL"))
        script_to_use = "/MakeMC.csh"
        login_shell = "bash"
        try:
            login_shell = os.environ["SHELL"].split("/")
        except BaseException:
            pass
        if (
            login_shell[len(login_shell) - 1] == "bash"
            or (
                self._config.batch_system.upper() == "OSG"
                and int(self._config.batchrun) != 0
            )
            or self._config.shell_to_use == "bash"
        ):
            script_to_use = "/MakeMC.sh"
        elif (
            login_shell[len(login_shell) - 1] == "zsh"
            or self._config.shell_to_use == "zcsh"
        ):
            script_to_use = "/MakeMC.sh"
        script_to_run += script_to_use
        if ".jlab.org" in socket.gethostname():
            self._config.location = "JLAB"
        if (
            len(self._config.custom_makemc) != 0
            and self._config.custom_makemc != "DEFAULT"
        ):
            script_to_run = self._config.custom_makemc
        if (
            self._config.batch_system.upper() == "OSG"
            and int(self._config.batchrun) != 0
            and (self._config.ccdb_sqlite_path == "no_sqlite")
        ):
            self._config.ccdb_sqlite_path = "batch_default"
        if (
            self._config.batch_system.upper() == "SWIF"
            and int(self._config.batchrun) != 0
            and (self._config.ccdb_sqlite_path == "no_sqlite")
        ):
            self._config.ccdb_sqlite_path = "jlab_batch_default"
            self._config.location = "JLAB"
        if (
            self._config.batch_system.upper() == "SWIF2"
            and int(self._config.batchrun) != 0
            and (self._config.ccdb_sqlite_path == "no_sqlite")
        ):
            self._config.ccdb_sqlite_path = "jlab_batch_default"
            self._config.location = "JLAB"
        if (
            self._config.batch_system.upper() == "OSG"
            and int(self._config.batchrun) != 0
            and (self._config.rcdb_sqlite_path == "no_sqlite")
        ):
            self._config.rcdb_sqlite_path = "batch_default"
            self._config.location = "OSG"
        if str(script_to_run) == "None":
            print("MCWRAPPER_CENTRAL not set")
            return
        outdir = self._config.output_directory
        if outdir[len(outdir) - 1] != "/":
            outdir += "/"
        run_type = str(self._config.run_number).split("-")
        command_settings = self._build_command(outdir)
        if command_settings["generator"][:4] == "file:" and len(run_type) != 1:
            print(
                (
                    "ERROR: MCwrapper currently does not support taking a monolithic file "
                    "and converting it into a range of runs."
                )
            )
            sys.exit(1)
        if str(self._config.is_submitter) == "1":
            self._run_submitter(command_settings, script_to_run)
        else:
            if len(run_type) != 1:
                self._run_range(command_settings, script_to_run, run_type)
            else:
                self._run_single(
                    command_settings, script_to_run, files_to_generate, remaining_events
                )
            self._finish_workflow()
        try:
            self._repository.connection.close()
        except Exception as e:
            print(e)
            pass
        print("ending gluex_MC.py")

    def _resolve_stage_os(self) -> None:
        """Resolve version-set operating systems and validate each stage selection."""
        rec_os_name = get_os_name(self._config.environment_file)
        print("recon_os_name:", rec_os_name, self._config.environment_file)
        sim_os_name = get_os_name(self._config.sim_environment_file)
        print("sim_os_name:", sim_os_name, self._config.sim_environment_file)
        ana_os_name = get_os_name(self._config.ana_environment_file)
        print("ana_os_name:", ana_os_name, self._config.ana_environment_file)
        rec_os = (
            "CENTOS7"
            if "CentOS7" in rec_os_name
            else "ALMA9"
            if "Alma9" in rec_os_name
            else "UNKNOWN"
        )
        ana_os = (
            "CENTOS7"
            if "CentOS7" in ana_os_name
            else "ALMA9"
            if "Alma9" in ana_os_name
            else "UNKNOWN"
        )
        sim_os = (
            "CENTOS7"
            if "CentOS7" in sim_os_name
            else "ALMA9"
            if "Alma9" in sim_os_name
            else "UNKNOWN"
        )
        running_os = ""
        if self._config.sim_environment_file != "no_Sim_env":
            running_os = sim_os
        else:
            running_os = rec_os
        if self._config.generator_os == "DB":
            self._config.generator_os = running_os
        if self._config.postgen_os == "DB":
            self._config.postgen_os = running_os
        if self._config.simulation_os == "DB":
            self._config.simulation_os = running_os
        if self._config.mcsmear_os == "DB":
            self._config.mcsmear_os = running_os
        if self._config.recon_os == "DB":
            self._config.recon_os = rec_os
        if self._config.ana_os == "DB":
            self._config.ana_os = ana_os
        print("GENERATOR_OS:", self._config.generator_os)
        print("POSTGEN_OS:", self._config.postgen_os)
        print("SIMULATION_OS:", self._config.simulation_os)
        print("MCSMEAR_OS:", self._config.mcsmear_os)
        print("RECON_OS:", self._config.recon_os)
        print("ANA_OS:", self._config.ana_os)
        if self._config.generator_os not in ["CENTOS7", "ALMA9", "LOCAL"]:
            print(
                "Generator OS not set to a valid OS.  Please set to CENTOS7, ALMA9 or LOCAL."
            )
            sys.exit(1)
        if self._config.postgen_os not in ["CENTOS7", "ALMA9", "LOCAL"]:
            print(
                (
                    "Post-Generator OS not set to a valid OS.  Please set to CENTOS7, "
                    "ALMA9 or LOCAL."
                )
            )
            sys.exit(1)
        if self._config.simulation_os not in ["CENTOS7", "ALMA9", "LOCAL"]:
            print(
                "Simulation OS not set to a valid OS.  Please set to CENTOS7, ALMA9 or LOCAL."
            )
            sys.exit(1)
        if self._config.mcsmear_os not in ["CENTOS7", "ALMA9", "LOCAL"]:
            print(
                "MC Smear OS not set to a valid OS.  Please set to CENTOS7, ALMA9 or LOCAL."
            )
            sys.exit(1)
        if self._config.recon_os not in ["CENTOS7", "ALMA9", "LOCAL"]:
            print(
                (
                    "Reconstruction OS not set to a valid OS.  Please set to CENTOS7, "
                    "ALMA9 or LOCAL."
                )
            )
            sys.exit(1)
        if self._config.ana_os not in ["CENTOS7", "ALMA9", "LOCAL"]:
            print(
                "Analysis OS not set to a valid OS.  Please set to CENTOS7, ALMA9 or LOCAL."
            )
            if self._config.ana_environment_file == "no_Analysis_env":
                print("Keep going as it is not needed.")
            else:
                sys.exit(1)

    def _build_command(self, outdir: str) -> Dict[str, str]:
        """Build the named settings consumed by the ordered MakeMC argument protocol."""
        command_settings = {"batchrun": str(self._config.batchrun)}
        command_settings["environment_file"] = self._config.environment_file
        command_settings["sim_environment_file"] = self._config.sim_environment_file
        command_settings["ana_environment_file"] = self._config.ana_environment_file
        command_settings["generator_os"] = self._config.generator_os
        command_settings["postgen_os"] = self._config.postgen_os
        command_settings["simulation_os"] = self._config.simulation_os
        command_settings["mcsmear_os"] = self._config.mcsmear_os
        command_settings["recon_os"] = self._config.recon_os
        command_settings["ana_os"] = self._config.ana_os
        command_settings["generator_config"] = self._config.generator_config
        command_settings["output_directory"] = str(outdir)
        command_settings["run_number"] = str(self._config.run_number)
        command_settings["file_number"] = str(self._config.base_file_number)
        command_settings["num_events"] = str(self._config.num_events)
        command_settings["jana_calib_context"] = str(self._config.variation)
        command_settings["jana_calibtime"] = str(self._config.calibtime)
        command_settings["do_gen"] = str(self._config.do_gen)
        command_settings["do_geant"] = str(self._config.do_geant)
        command_settings["do_mcsmear"] = str(self._config.do_mcsmear)
        command_settings["do_recon"] = str(self._config.do_recon)
        command_settings["clean_gen"] = str(self._config.clean_gen)
        command_settings["clean_geant"] = str(self._config.clean_geant)
        command_settings["clean_mcsmear"] = str(self._config.clean_mcsmear)
        command_settings["clean_recon"] = str(self._config.clean_recon)
        command_settings["batch_system"] = str(self._config.batch_system)
        command_settings["num_cores"] = str(self._config.num_cores).split(":")[-1]
        command_settings["generator"] = str(self._config.generator)
        command_settings["geant_version"] = str(self._config.geant_version)
        command_settings["background_to_include"] = str(self._config.background)
        command_settings["custom_Gcontrol"] = str(self._config.custom_gcontrol)
        command_settings["eBeam_energy"] = str(self._config.ebeam_energy)
        command_settings["coherent_peak"] = str(self._config.coherent_peak)
        command_settings["min_generator_energy"] = str(
            self._config.min_generator_energy
        )
        command_settings["max_generator_energy"] = str(
            self._config.max_generator_energy
        )
        command_settings["custom_tag_string"] = str(self._config.tag_string)
        command_settings["custom_plugins"] = str(self._config.custom_plugins)
        command_settings["custom_ana_plugins"] = str(self._config.custom_ana_plugins)
        command_settings["events_per_file"] = str(self._config.events_per_file)
        command_settings["running_directory"] = str(self._config.running_directory)
        command_settings["ccdb_sqlite_path"] = str(self._config.ccdb_sqlite_path)
        command_settings["rcdb_sqlite_path"] = str(self._config.rcdb_sqlite_path)
        command_settings["background_tagger_only"] = str(
            self._config.background_tagger_only
        )
        command_settings["radiator_thickness"] = str(self._config.radiator_thickness)
        command_settings["background_rate"] = str(self._config.background_rate)
        command_settings["random_background_tag"] = str(
            self._config.random_background_tag
        )
        command_settings["recon_version"] = str(self._config.recon_version)
        command_settings["recon_calibtime"] = str(self._config.recon_calibtime)
        command_settings["ana_version"] = str(self._config.ana_version)
        command_settings["ana_calibtime"] = str(self._config.ana_calibtime)
        command_settings["no_geant_secondaries"] = str(
            self._config.no_geant_secondaries
        )
        command_settings["mcwrapper_version"] = str(MCWRAPPER_VERSION)
        command_settings["no_bcal_sipm_saturation"] = str(
            self._config.no_bcal_sipm_saturation
        )
        command_settings["flux_to_generate"] = str(self._config.flux_to_generate)
        command_settings["flux_histogram"] = str(self._config.flux_histogram)
        command_settings["polarization_to_generate"] = str(
            self._config.polarization_to_generate
        )
        command_settings["polarization_histogram"] = str(
            self._config.polarization_histogram
        )
        command_settings["eBeam_current"] = str(self._config.ebeam_current)
        command_settings["experiment"] = str(self._config.experiment)
        command_settings["ccdb_flux_version"] = str(self._config.generator_flux_version)
        command_settings["num_rand_trigs"] = str(self._config.num_rand_trigs)
        command_settings["location"] = str(self._config.location)
        command_settings["generator_post"] = str(self._config.generator_post)
        command_settings["generator_post_config"] = str(
            self._config.generator_post_config
        )
        command_settings["generator_post_configevt"] = str(
            self._config.generator_post_configevt
        )
        command_settings["generator_post_configdec"] = str(
            self._config.generator_post_configdec
        )
        command_settings["geant_vertex_area"] = str(self._config.vertex_area)
        command_settings["geant_vertex_length"] = str(self._config.vertex_length)
        command_settings["mcsmear_notag"] = str(self._config.mcsmear_notag)
        command_settings["project_directory_name"] = str(self._config.output_directory)
        command_settings["random_background_rate"] = str(
            self._config.random_background_rate
        )
        command_settings["generator_file_skip"] = "-1"
        return command_settings

    def _run_submitter(
        self, command_settings: MutableMapping[str, str], script_to_run: str
    ) -> None:
        """Execute the single job handed off by the submitter."""
        matching_jobs: Sequence[Any] = []
        if (
            self._config.background == "Random"
            or self._config.background == "DEFAULT"
            or self._config.background[0:3] == "loc"
        ):
            self._config.num_rand_trigs = self._random_triggers.get_count(
                self._config.background,
                self._config.random_background_tag,
                self._config.batch_system,
                self._config.run_number,
            )
            command_settings["num_rand_trigs"] = str(self._config.num_rand_trigs)
        if self._config.batchrun == 0 or self._config.batch_system.upper() == "NULL":
            os.system(
                f"{script_to_run!s} {format_command(command_settings, 'INTERACTIVE')!s}"
            )
        else:
            if self._config.project_id != 0:
                print(
                    (
                        "SELECT ID "
                        "FROM Jobs "
                        f"WHERE Project_ID={self._config.project_id!s} "
                        f"&& RunNumber={self._config.run_number!s} "
                        f"&& FileNumber={self._config.base_file_number!s} "
                        f"&& NumEvts={self._config.num_events!s}"
                    )
                )
                job_query = (
                    "SELECT ID "
                    "FROM Jobs "
                    f"WHERE Project_ID={self._config.project_id!s} "
                    f"&& RunNumber={self._config.run_number!s} "
                    f"&& FileNumber={self._config.base_file_number!s} "
                    f"&& NumEvts={self._config.num_events!s}"
                )
                self._repository.cursor.execute(job_query)
                matching_jobs = self._repository.cursor.fetchall()
                print(len(matching_jobs))
            if len(matching_jobs) == 0:
                self._submitter.submit(
                    self._config,
                    script_to_run,
                    command_settings,
                    self._config.run_number,
                    self._config.base_file_number,
                    start_workflow=True,
                    container_slurm=True,
                )

    def _run_range(
        self,
        command_settings: MutableMapping[str, str],
        script_to_run: str,
        run_type: Sequence[str],
    ) -> None:
        """Select runs, weight their requested events by flux, and execute their files."""
        matching_jobs: Sequence[Any] = []
        event_sum = 0.0
        db = rcdb.RCDBProvider(os.environ.get("RCDB_CONNECTION"))
        ccdb_conn = load_ccdb()
        flux_calculator = FluxCalculator(ccdb_conn)
        run_low = 0
        run_high = 0
        if run_type[0] != "RunPeriod":
            run_low = run_type[0].lstrip("0")
            run_high = run_type[1].lstrip("0")
        else:
            cnx = MySQLdb.connect(
                user="ccdb_user", database="ccdb", host="hallddb.jlab.org"
            )
            cursor = cnx.cursor()
            run_range_name = ""
            for npart in run_type:
                if npart == "RunPeriod":
                    continue
                else:
                    run_range_name = run_range_name + npart
            cursor.execute(
                f"SELECT runMin,runMax FROM runRanges WHERE name = '{run_range_name!s}'"
            )
            run_range = cursor.fetchall()
            run_low = run_range[0][0]
            run_high = run_range[0][1]
            print(run_range)
            print(f"{run_low!s}-->{run_high!s}")
        query_to_do = "@is_production and @status_approved"
        if str(self._config.experiment).upper() == "CPP":
            query_to_do = "@is_cpp_production and @status_approved"
        print(f"RCDB_QUERY IS: {self._config.rcdb_query!s}")
        if (
            self._config.rcdb_query != ""
            and str(self._config.rcdb_query).strip().lower() != "none"
        ):
            query_to_do = self._config.rcdb_query
        print(f"{run_low!s}------->{run_high!s}")
        running_hostname = socket.gethostname()
        if "scosg2201" in running_hostname:
            conn_command = (
                "singularity exec --cleanenv --bind /scigroup/mcwrapper/ --bind /group/halld/:/group/halld/ "
                "--bind /cvmfs /cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_almalinux_9:latest"
            )
            conn_command = (
                f"{conn_command!s} /scigroup/mcwrapper/gluex_MCwrapper/Utilities/rcdb_wrapper.sh "
                f'"{query_to_do.split(chr(10))[0]!s}" {run_low!s} {run_high!s}'
            )
            print("RCDB Container command:")
            print(conn_command)
            my_env = os.environ.copy()
            p = subprocess.Popen(
                conn_command,
                env=my_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=-1,
                shell=True,
            )
            output, errors = p.communicate()
            print(output)
            table = json.loads(output)
        else:
            table = db.select_runs(str(query_to_do), run_low, run_high).get_values(
                ["event_count", "polarimeter_converter"], True
            )
        print(table)
        print(
            (
                "\nComputing flux from CCDB for all runs in the requested range, this "
                "may take a minute...\n"
            )
        )
        fluxes = []
        flux_sum = 0
        for runs in table:
            print(runs)
            if len(table) <= 1:
                fluxes.append(0)
                break
            event_sum = event_sum + runs[1]
            flux = 0
            if self._config.wrapper_flux_version == "tagged":
                flux = (
                    flux_calculator.tagged_flux(
                        runs,
                        float(self._config.min_generator_energy),
                        float(self._config.max_generator_energy),
                    )
                    / 1000000000.0
                )
            else:
                flux = (
                    flux_calculator.untagged_flux(
                        runs,
                        float(self._config.min_generator_energy),
                        float(self._config.max_generator_energy),
                    )
                    / 1000000000.0
                )
            print(flux)
            fluxes.append(flux)
            flux_sum = flux_sum + flux
        print(f"Events from rcdb: {event_sum!s}")
        if event_sum == 0 and self._config.project_id > 0:
            print(
                "No events found in the requested range matching the RCDB query, exiting"
            )
            self._repository.mark_no_events(self._config.project_id)
        print(f"Flux from ccdb: {flux_sum!s}")
        allocated_events = 0.0
        generator_file_skip_counter = (
            self._config.base_file_number * self._config.events_per_file
        )
        for runs, flux in zip(table, fluxes):
            if len(table) <= 1:
                break
            num_events_this_run = int(flux / flux_sum * self._config.num_events + 0.5)
            allocated_events = allocated_events + int(
                flux / flux_sum * self._config.num_events + 0.5
            )
            if num_events_this_run == 0:
                continue
            files_this_run = int(num_events_this_run / self._config.events_per_file)
            remaining_events_this_run = (
                num_events_this_run % self._config.events_per_file
            )
            for file_index in range(1, int(files_this_run) + 2):
                num_this_file = self._config.events_per_file
                if file_index == files_this_run + 1:
                    num_this_file = remaining_events_this_run
                if num_this_file == 0:
                    continue
                command_settings["run_number"] = str(runs[0])
                command_settings["file_number"] = str(
                    self._config.base_file_number + file_index + -1
                )
                command_settings["num_events"] = str(num_this_file)
                if str(self._config.generator)[:5] == "file:":
                    command_settings["generator_file_skip"] = str(
                        generator_file_skip_counter
                    )
                    generator_file_skip_counter = (
                        generator_file_skip_counter + num_this_file
                    )
                else:
                    command_settings["generator_file_skip"] = "-1"
                if (
                    self._config.background == "Random"
                    or self._config.background == "DEFAULT"
                    or self._config.background[0:3] == "loc"
                ):
                    self._config.num_rand_trigs = self._random_triggers.get_count(
                        self._config.background,
                        self._config.random_background_tag,
                        self._config.batch_system,
                        runs[0],
                    )
                    command_settings["num_rand_trigs"] = str(
                        self._config.num_rand_trigs
                    )
                format_command(command_settings, "NONSUB")
                if (
                    self._config.batchrun == 0
                    or self._config.batch_system.upper() == "NULL"
                ):
                    os.system(
                        f"{script_to_run!s} {format_command(command_settings, 'INTERACTIVE')!s}"
                    )
                else:
                    if self._config.project_id != 0:
                        print(
                            (
                                "SELECT ID "
                                "FROM Jobs "
                                f"WHERE Project_ID={self._config.project_id!s} "
                                f"&& RunNumber={runs[0]!s} "
                                f"&& FileNumber={self._config.base_file_number + file_index + -1!s} "
                                f"&& NumEvts={num_this_file!s}"
                            )
                        )
                        job_query = (
                            "SELECT ID "
                            "FROM Jobs "
                            f"WHERE Project_ID={self._config.project_id!s} "
                            f"&& RunNumber={runs[0]!s} "
                            f"&& FileNumber={self._config.base_file_number + file_index + -1!s} "
                            f"&& NumEvts={num_this_file!s}"
                        )
                        self._repository.cursor.execute(job_query)
                        matching_jobs = self._repository.cursor.fetchall()
                        print(len(matching_jobs))
                    if len(matching_jobs) == 0:
                        self._submitter.submit(
                            self._config,
                            script_to_run,
                            command_settings,
                            runs[0],
                            self._config.base_file_number + file_index + -1,
                            start_workflow=False,
                            container_slurm=False,
                        )

    def _run_single(
        self,
        command_settings: MutableMapping[str, str],
        script_to_run: str,
        files_to_generate: int,
        remaining_events: int,
    ) -> None:
        """Execute full files and the final remainder for a single run."""
        matching_jobs: Sequence[Any] = []
        generator_file_skip_counter = (
            self._config.base_file_number * self._config.events_per_file
        )
        for file_number in range(1, int(files_to_generate) + 2):
            num_events_this_file = self._config.events_per_file
            if file_number == files_to_generate + 1:
                num_events_this_file = remaining_events
            if num_events_this_file == 0:
                continue
            command_settings["run_number"] = str(self._config.run_number)
            command_settings["file_number"] = str(
                self._config.base_file_number + file_number + -1
            )
            command_settings["num_events"] = str(num_events_this_file)
            if str(self._config.generator)[:5] == "file:":
                command_settings["generator_file_skip"] = str(
                    generator_file_skip_counter
                )
                generator_file_skip_counter = (
                    generator_file_skip_counter + num_events_this_file
                )
            else:
                command_settings["generator_file_skip"] = "-1"
            if (
                self._config.background == "Random"
                or self._config.background == "DEFAULT"
                or self._config.background[0:3] == "loc"
            ):
                self._config.num_rand_trigs = self._random_triggers.get_count(
                    self._config.background,
                    self._config.random_background_tag,
                    self._config.batch_system,
                    self._config.run_number,
                )
                command_settings["num_rand_trigs"] = str(self._config.num_rand_trigs)
                print("RANDOM_NUM_EVT =", self._config.num_rand_trigs)
            command = format_command(command_settings, "INTERACTIVE")
            print("COMMAND PRINTOUT:", f"{script_to_run!s} {command!s}")
            if (
                self._config.batchrun == 0
                or self._config.batch_system.upper() == "NULL"
            ):
                os.system(f"{script_to_run!s} {command!s}")
            else:
                if self._config.project_id != 0:
                    print(
                        (
                            "SELECT ID "
                            "FROM Jobs "
                            f"WHERE Project_ID={self._config.project_id!s} "
                            f"&& RunNumber={self._config.run_number!s} "
                            f"&& FileNumber={self._config.base_file_number + file_number + -1!s} "
                            f"&& NumEvts={num_events_this_file!s}"
                        )
                    )
                    job_query = (
                        "SELECT ID "
                        "FROM Jobs "
                        f"WHERE Project_ID={self._config.project_id!s} "
                        f"&& RunNumber={self._config.run_number!s} "
                        f"&& FileNumber={self._config.base_file_number + file_number + -1!s} "
                        f"&& NumEvts={num_events_this_file!s}"
                    )
                    self._repository.cursor.execute(job_query)
                    matching_jobs = self._repository.cursor.fetchall()
                    print(len(matching_jobs))
                if len(matching_jobs) == 0:
                    self._submitter.submit(
                        self._config,
                        script_to_run,
                        command_settings,
                        self._config.run_number,
                        self._config.base_file_number + file_number + -1,
                        start_workflow=False,
                        container_slurm=True,
                    )

    def _finish_workflow(self) -> None:
        """Start SWIF workflows when requested or print their start commands."""
        if self._config.batchrun == 1 and self._config.batch_system.upper() == "SWIF":
            print(
                f'All Jobs created.  Please call "swif run {self._config.workflow!s}" to run'
            )
        elif self._config.batchrun == 2 and self._config.batch_system.upper() == "SWIF":
            swifrun = f"swif run {self._config.workflow!s}"
            subprocess.call(swifrun.split(" "))
        if self._config.batchrun == 1 and (
            self._config.batch_system.upper() == "SWIF2"
            or self._config.batch_system.upper() == "SWIF2CONT"
        ):
            print(
                f'All Jobs created.  Please call "swif2 run {self._config.workflow!s}" to run'
            )
        elif self._config.batchrun == 2 and (
            self._config.batch_system.upper() == "SWIF2"
            or self._config.batch_system.upper() == "SWIF2CONT"
        ):
            swifrun = f"swif2 run {self._config.workflow!s}"
            subprocess.call(swifrun.split(" "))


def main(argv: Sequence[str]) -> None:
    """Parse required CLI arguments, load settings, and execute the simulation."""
    parser_usage = (
        "gluex_MC.py config_file Run_Number/Range num_events [all other options]\n\n "
        "where [all other options] are:\n\n "
    )
    parser_usage += show_help()
    parser = OptionParser(usage=parser_usage)
    options, args = parser.parse_args(list(argv))
    if len(argv) < 3:
        parser.print_help()
        return
    if len(args[1].split("=")) > 1 or len(args[2].split("=")) > 1:
        parser.print_help()
        return
    config_file = args[0]
    run_number = str(args[1]).lstrip("0")
    num_events = int(args[2])
    print("*********************************")
    print(f"Welcome to v{MCWRAPPER_VERSION!s} of MCwrapper")
    print(f"Thomas Britton {MCWRAPPER_DATE!s}")
    print("*********************************")
    config = SimulationConfig(config_file, run_number, num_events)
    if not config.read():
        return
    config.apply_options(args)
    repository = JobRepository.connect()
    SimulationRunner(config, repository, args).run()


if __name__ == "__main__":
    main(sys.argv[1:])
