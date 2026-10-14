#!/usr/bin/env python3
"""Dispatch, retry, and test requested MC projects and build their payloads."""

import datetime
import json
import os
import pwd
import shutil
import smtplib
import socket
import subprocess
import sys
import time
from email.message import EmailMessage
from multiprocessing import Process, Queue
from pathlib import Path
from subprocess import PIPE, Popen
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    TextIO,
    Tuple,
    Union,
)

import MySQLdb
from mc_status import (
    JOB_ACTIVE,
    JOB_INACTIVE,
    PROJECT_NOTIFIED,
    AttemptStatus,
    ExitCode,
    ProjectStatus,
    ProjectTestResult,
)

try:
    import rcdb
except Exception as error:
    print("IMPORT ERROR:", error)

MCWRAPPER_BOT_HOME = "/scigroup/mcwrapper/gluex_MCwrapper/"
HOST_NAME = socket.gethostname()
DB_HOST = "hallddb.jlab.org"
DB_USER = "mcuser"
DB_NAME = "gluex_mc"
RUNNER_NAME = pwd.getpwuid(os.getuid())[0]
ALLOWED_USERS = ("tbritton", "mcwrap")
DEFAULT_RCDB_CONNECTION = "mysql://rcdb@hallddb.jlab.org/rcdb2"


class TerminalColors:
    """ANSI color codes for project test results."""

    HEADER = "\x1b[95m"
    OKBLUE = "\x1b[94m"
    OKGREEN = "\x1b[92m"
    WARNING = "\x1b[93m"
    FAIL = "\x1b[91m"
    ENDC = "\x1b[0m"
    BOLD = "\x1b[1m"
    UNDERLINE = "\x1b[4m"


def extract_job_failure(output: Any) -> str:
    """Return the final failure marker with up to twenty preceding lines."""
    lines = str(output).splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if "something went wrong with" in lines[index].lower():
            return "\n".join(lines[max(0, index - 20) : index + 1])
    return ""


def source(script: str, update: bool = True) -> Dict[str, str]:
    """Read a shell script environment and optionally update this process."""
    proc = subprocess.Popen(
        ["bash", "-c", f"set -a && source {script} && env -0"],
        stdout=subprocess.PIPE,
        shell=False,
    )
    output, err = proc.communicate()
    output = output.decode("utf8")
    env = dict((line.split("=", 1) for line in output.split("\x00") if line))
    if update:
        os.environ.update(env)
    return env


def _stage_options(order: Mapping[str, Any]) -> str:
    """Format enabled simulation stages and their cleanup flags."""
    clean_generation = 0 if order["SaveGeneration"] == 1 else 1
    clean_geant = 0 if order["SaveGeant"] == 1 else 1
    clean_smear = 0 if order["SaveSmear"] == 1 else 1
    clean_reconstruction = 0 if order["SaveReconstruction"] == 1 else 1
    return (
        f"generate={order['RunGeneration']} cleangenerate={clean_generation} "
        f"geant={order['RunGeant']} cleangeant={clean_geant} mcsmear={order['RunSmear']} "
        f"cleanmcsmear={clean_smear} recon={order['RunReconstruction']} cleanrecon={clean_reconstruction}"
    )


def _run_range(order: Mapping[str, Any]) -> str:
    """Format a single run or inclusive run range for the wrapper."""
    run_number = str(order["RunNumLow"])
    if order["RunNumLow"] != order["RunNumHigh"]:
        run_number += f"-{order['RunNumHigh']}"
    return run_number


def _copy_payload_template(template_name: str, config_id: Union[int, str]) -> None:
    """Copy a batch template and report copy failures before payload generation."""
    try:
        shutil.copyfile(
            Path(MCWRAPPER_BOT_HOME) / "examples" / template_name,
            Path(f"MCDispatched_{config_id}.config"),
        )
    except OSError as error:
        print(error, file=sys.stderr)


def _rcdb_query(order: Mapping[str, Any], single_run_query: str = "") -> str:
    """Select the version-specific production query or the submitted override."""
    if order["RunNumLow"] == order["RunNumHigh"]:
        return single_run_query
    query = "@is_production and @status_approved"
    if "recon-2018" in order["VersionSet"]:
        query = "@is_2018production and @status_approved"
    if "recon-2019" in order["VersionSet"]:
        query = "@is_dirc_production and @status_approved"
    if order["RCDBQuery"] != "":
        query = order["RCDBQuery"]
    return query


def _write_test_script(
    project_id: Union[int, str], version_set: str, command: str
) -> None:
    """Write the environment and wrapper command used by the container test."""
    script = Path(f"TestProject_runscript_{project_id}.sh")
    with script.open("w") as run_script:
        run_script.write("#!/bin/bash -l\n")
        run_script.write("export SHELL=/bin/bash\n")
        run_script.write("export BEARER_TOKEN_FILE=/var/run/user/10967/bt_u10967\n")
        run_script.write("export XDG_RUNTIME_DIR=/run/user/10967\n")
        run_script.write(
            f"#source /group/halld/Software/build_scripts/gluex_env_jlab.sh /group/halld/www/halldweb/html/halld_versions/{version_set}\n"
        )
        run_script.write(
            "source /group/halld/Software/build_scripts/gluex_env_jlab.sh /group/halld/www/halldweb/html/halld_versions/version.xml\n"
        )
        run_script.write(f"export MCWRAPPER_CENTRAL={MCWRAPPER_BOT_HOME}\n")
        run_script.write(command)


class PayloadConfigWriter:
    """Build payload settings and stage project configuration files."""

    def __init__(self, connection: Any, cursor: Any) -> None:
        self._connection = connection
        self._cursor = cursor

    def write(
        self, order: Mapping[str, Any], found_config: str, job_id: Union[int, str] = -1
    ) -> Optional[int]:
        """Append a payload, stage auxiliary files, and report postprocessing failures."""
        config_id = order["ID"] if job_id == -1 else job_id
        with Path(f"MCDispatched_{config_id}.config").open("a") as config_file:
            config_file.write(f"PROJECT={order['Exp']!s}\n")
            if str(order["Exp"]) == "CPP":
                config_file.write("VARIATION=mc_cpp\n")
                config_file.write("FLUX_TO_GEN=cobrems\n")
            elif str(order["Exp"]) == "JEF":
                config_file.write("VARIATION=mc_JEF\n")
                config_file.write("FLUX_TO_GEN=cobrems\n")
                config_file.write("eBEAM_ENERGY=11.6\n")
                config_file.write("eBEAM_CURRENT=0.35\n")
                config_file.write("RADIATOR_THICKNESS=50.e-06\n")
                config_file.write("COHERENT_PEAK=8.6\n")
            if 30000 <= int(order["RunNumLow"]) and int(order["RunNumLow"]) <= 39999:
                if (
                    str(order["VersionSet"]) == "recon-2017_01-ver05.xml"
                    or str(order["VersionSet"]) == "version_7.2.0.xml"
                ):
                    config_file.write("VARIATION=mc_2017_01_ver05\n")
                    config_file.write("RECON_VERSION=mc_2017_01_ver05\n")
                    config_file.write("ANA_VERSION=mc_2017_01_ver05\n")
            location_parts = order["OutputLocation"].split("/")
            config_file.write(
                f"WORKFLOW_NAME={location_parts[len(location_parts) - 2]!s}\n"
            )
            config_file.write(f"{order['Config_Stub']!s}\n")
            minimum_energy = str(order["GenMinE"])
            if len(minimum_energy) > 5:
                cutnum = len(minimum_energy) - 5
                minimum_energy = minimum_energy[:-cutnum]
            maximum_energy = str(order["GenMaxE"])
            if len(maximum_energy) > 5:
                cutnum = len(maximum_energy) - 5
                maximum_energy = maximum_energy[:-cutnum]
            config_file.write(f"GEN_MIN_ENERGY={minimum_energy!s}\n")
            config_file.write(f"GEN_MAX_ENERGY={maximum_energy!s}\n")
            if str(order["GenFlux"]) == "cobrems":
                config_file.write("FLUX_TO_GEN=cobrems\n")
            if order["CoherentPeak"] is not None:
                config_file.write(f"COHERENT_PEAK={order['CoherentPeak']!s}\n")
            else:
                config_file.write("COHERENT_PEAK=rcdb\n")
            if str(order["Generator"]) == "file:":
                if found_config == "True":
                    config_file.write(
                        f"GENERATOR={order['Generator']!s}/{order['Generator_Config']!s}\n"
                    )
                else:
                    config_file.write(
                        f"GENERATOR={order['Generator']!s}/{found_config!s}\n"
                    )
            else:
                config_file.write(f"GENERATOR={order['Generator']!s}\n")
                print(order["Generator_Config"])
                if found_config == "True":
                    config_file.write(
                        f"GENERATOR_CONFIG={order['Generator_Config']!s}\n"
                    )
                else:
                    config_file.write(f"GENERATOR_CONFIG={found_config!s}\n")
            print("post genconfig!", order["GenPostProcessing"])
            postprocessing_status = self._write_postprocessing(config_file, order)
            if postprocessing_status == ProjectTestResult.POSTPROCESSING_FAILED:
                return ProjectTestResult.POSTPROCESSING_FAILED
            config_file.write(f"GEANT_VERSION={order['GeantVersion']!s}\n")
            config_file.write(f"NOSECONDARIES={abs(order['GeantSecondaries'] - 1)!s}\n")
            config_file.write(f"BKG={order['BKG']!s}\n")
            print(order["OutputLocation"])
            location_parts = str(order["OutputLocation"]).split("/")
            print(location_parts)
            # Output metadata stores the relative hierarchy at component seven.
            output_subdirectory = "/".join(location_parts[7:-1])
            output_path = _user_path("REQUESTEDMC_OUTPUT", output_subdirectory)
            trailing_separator = "/" if not output_subdirectory else ""
            config_file.write(
                f"DATA_OUTPUT_BASE_DIR={output_path}{trailing_separator}\n"
            )
            print("PREIF", order["VersionSet"])
            query_to_do = _rcdb_query(order, "")
            if query_to_do != "":
                config_file.write(f"RCDB_QUERY={query_to_do!s}\n")
            if order["eBeamEnergy"] is not None:
                config_file.write(f"eBEAM_ENERGY={order['eBeamEnergy']!s}\n")
            if order["eBeamCurrent"] is not None:
                config_file.write(f"eBEAM_CURRENT={order['eBeamCurrent']!s}\n")
            self._write_reactions(config_file, order)
            config_file.write(
                f"ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/{order['VersionSet']!s}\n"
            )
            print("ADD ANAVER TO PAYLOAD?")
            print(str(order["ANAVersionSet"]))
            print("adding anaver if needed...")
            if order["ANAVersionSet"] is not None and order["ANAVersionSet"] != "None":
                print("ADDING ANNAVER")
                config_file.write(
                    f"ANA_ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/{order['ANAVersionSet']!s}\n"
                )
                print("ADDED ANNAVER")
            print("adding simver if needed...")
            if order["SimVersionSet"] is not None and order["SimVersionSet"] != "None":
                print("ADDING SIMVER")
                config_file.write(
                    f"SIM_ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/{order['SimVersionSet']!s}\n"
                )
                print("ADDED SIMVER")
            config_file.write("GENERATOR_OS=db\n")
            config_file.write("POSTGEN_OS=db\n")
            config_file.write("SIMULATION_OS=db\n")
            config_file.write("MCSMEAR_OS=db\n")
            config_file.write("RECON_OS=db\n")
            config_file.write("ANA_OS=db\n")

    def render(self, order: Mapping[str, Any], found_config: str) -> str:
        """Print and return the display payload without staging auxiliary files."""
        config_str = ""
        config_str += f"PROJECT={order['Exp']!s}\n"
        if str(order["Exp"]) == "CPP":
            config_str += "VARIATION=mc_cpp\n"
            config_str += "FLUX_TO_GEN=cobrems\n"
        elif str(order["Exp"]) == "JEF":
            config_str += "VARIATION=mc_JEF\n"
            config_str += "FLUX_TO_GEN=cobrems\n"
            config_str += "eBEAM_ENERGY=11.6\n"
            config_str += "eBEAM_CURRENT=0.35\n"
            config_str += "RADIATOR_THICKNESS=50.e-06\n"
            config_str += "COHERENT_PEAK=8.6\n"
        if 30000 <= int(order["RunNumLow"]) and int(order["RunNumLow"]) <= 39999:
            if (
                str(order["VersionSet"]) == "recon-2017_01-ver05.xml"
                or str(order["VersionSet"]) == "version_7.2.0.xml"
            ):
                config_str += "VARIATION=mc_2017_01_ver05\n"
                config_str += "RECON_VERSION=mc_2017_01_ver05\n"
                config_str += "ANA_VERSION=mc_2017_01_ver05\n"
        location_parts = order["OutputLocation"].split("/")
        config_str += f"WORKFLOW_NAME={location_parts[len(location_parts) - 2]!s}\n"
        config_str += f"{order['Config_Stub']!s}\n"
        minimum_energy = str(order["GenMinE"])
        if len(minimum_energy) > 5:
            cutnum = len(minimum_energy) - 5
            minimum_energy = minimum_energy[:-cutnum]
        maximum_energy = str(order["GenMaxE"])
        if len(maximum_energy) > 5:
            cutnum = len(maximum_energy) - 5
            maximum_energy = maximum_energy[:-cutnum]
        config_str += f"GEN_MIN_ENERGY={minimum_energy!s}\n"
        config_str += f"GEN_MAX_ENERGY={maximum_energy!s}\n"
        if str(order["GenFlux"]) == "cobrems":
            config_str += "FLUX_TO_GEN=cobrems\n"
        # Display payloads include both peak entries when a peak is supplied.
        if order["CoherentPeak"] is not None:
            config_str += f"COHERENT_PEAK={order['CoherentPeak']!s}\n"
        if str(order["Generator"]) == "file:":
            if found_config == "True":
                config_str += (
                    f"GENERATOR={order['Generator']!s}/{order['Generator_Config']!s}\n"
                )
            else:
                config_str += f"GENERATOR={order['Generator']!s}/{found_config!s}\n"
        else:
            config_str += f"GENERATOR={order['Generator']!s}\n"
            if found_config == "True":
                config_str += f"GENERATOR_CONFIG={order['Generator_Config']!s}\n"
            else:
                config_str += f"GENERATOR_CONFIG={found_config!s}\n"
        if order["CoherentPeak"] is not None:
            config_str += f"COHERENT_PEAK={order['CoherentPeak']!s}\n"
        else:
            config_str += "COHERENT_PEAK=rcdb\n"
        if order["GenPostProcessing"] is not None and order["GenPostProcessing"] != "":
            config_str += f"GEN_POST_PROCESSING={order['GenPostProcessing']!s}\n"
        config_str += f"GEANT_VERSION={order['GeantVersion']!s}\n"
        config_str += f"NOSECONDARIES={abs(order['GeantSecondaries'] - 1)!s}\n"
        config_str += f"BKG={order['BKG']!s}\n"
        location_parts = str(order["OutputLocation"]).split("/")
        # Output metadata stores the relative hierarchy at component seven.
        output_subdirectory = "/".join(location_parts[7:-1])
        output_path = _user_path("REQUESTEDMC_OUTPUT", output_subdirectory)
        trailing_separator = "/" if not output_subdirectory else ""
        config_str += f"DATA_OUTPUT_BASE_DIR={output_path}{trailing_separator}\n"
        query_to_do = _rcdb_query(order, "")
        config_str += f"RCDB_QUERY={query_to_do!s}\n"
        if order["eBeamEnergy"] is not None:
            config_str += f"eBEAM_ENERGY={order['eBeamEnergy']!s}\n"
        if order["eBeamCurrent"] is not None:
            config_str += f"eBEAM_CURRENT={order['eBeamCurrent']!s}\n"
        if order["ReactionLines"] != "":
            if order["ReactionLines"][0:5] != "file:":
                jana_plugins = "PLUGINS danarest,monitoring_hists,mcthrown_tree"
                if order["ReactionLines"]:
                    jana_plugins += f",ReactionFilter\n{order['ReactionLines']!s}"
                else:
                    jana_plugins += "\n"
            config_str += f"CUSTOM_PLUGINS=file:/osgpool/halld/{RUNNER_NAME!s}/REQUESTEDMC_CONFIGS/{order['ID']!s}_jana.config\n"
        config_str += f"ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/{order['VersionSet']!s}\n"
        if order["ANAVersionSet"] is not None and order["ANAVersionSet"] != "None":
            config_str += f"ANA_ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/{order['ANAVersionSet']!s}\n"
        if order["SimVersionSet"] is not None and order["SimVersionSet"] != "None":
            config_str += f"SIM_ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/{order['SimVersionSet']!s}\n"
        config_str += "GENERATOR_OS=db\n"
        config_str += "POSTGEN_OS=db\n"
        config_str += "SIMULATION_OS=db\n"
        config_str += "MCSMEAR_OS=db\n"
        config_str += "RECON_OS=db\n"
        config_str += "ANA_OS=db\n"
        print(config_str)
        return config_str

    def _write_postprocessing(
        self, config_file: TextIO, order: Mapping[str, Any]
    ) -> Optional[int]:
        """Stage postprocessing configuration files and append their payload settings."""
        if order["GenPostProcessing"] is not None and order["GenPostProcessing"] != "":
            file_error = False
            postprocessing_parts = order["GenPostProcessing"].split(":")
            staged_postprocessing = postprocessing_parts[0]
            print("newGenPost_str", staged_postprocessing)
            for i in range(1, len(postprocessing_parts)):
                print("parseGenPostProcessing[i]", postprocessing_parts[i])
                if postprocessing_parts[i].strip() != "Default":
                    copy_loc = "ifarm2401-ib"
                    if "scosg2201" in socket.gethostname():
                        copy_loc = "ifarm2401"
                    staged_config = _user_path(
                        "REQUESTEDMC_CONFIGS", f"{order['ID']}_genpost_{i}.config"
                    )
                    print(
                        f"scp {RUNNER_NAME}@{copy_loc}:{postprocessing_parts[i]} {staged_config}"
                    )
                    try:
                        subprocess.call(
                            f"scp {RUNNER_NAME}@{copy_loc}:{postprocessing_parts[i]} {staged_config}",
                            shell=True,
                        )
                    except Exception as e:
                        print("Error in copying gen post processing file:", e)
                        pass
                    print("checking for config file:", str(staged_config))
                    if staged_config.exists():
                        staged_postprocessing += f":{staged_config}"
                    else:
                        print(
                            "Error finding a gen post processing file:",
                            postprocessing_parts[i],
                            "not found",
                        )
                        file_error = True
                else:
                    staged_postprocessing += ":Default"
            print("file Error:", file_error)
            if not file_error:
                update_str = (
                    f"UPDATE Project SET GenPostProcessing='{staged_postprocessing!s}' "
                    f"WHERE ID={order['ID']!s}"
                )
                print(update_str)
                self._cursor.execute(update_str)
                self._connection.commit()
            else:
                print("Could not find one or more generator post processing files!")
                msg = EmailMessage()
                msg.set_content(
                    (
                        "Could not test the project because MCwrapper-bot could not copy the "
                        f"following file: {postprocessing_parts[i]!s}\n This may be due to "
                        f"a lack of permissions for {RUNNER_NAME!s} to read from the containing "
                        "directory or the file itself may not exist.\n Shortly you will receive "
                        "a second email that the actual test has failed, please use the link "
                        "contained in the second email to correct this problem."
                    )
                )
                msg["Subject"] = (
                    f"GlueX MC Request #{order['ID']!s} Could not be tested properly"
                )
                msg["From"] = "MCwrapper-bot"
                msg["To"] = str(order["Email"])
                s = smtplib.SMTP("localhost")
                s.send_message(msg)
                s.quit()
                try:
                    copy = _user_path(
                        f"REQUESTED_FAIL_MAILS/email_{order['ID']!s}.log"
                    ).open("w+")
                    copy.write(
                        (
                            "Could not test the project because MCwrapper-bot could not copy the "
                            f"following file: {postprocessing_parts[i]!s}\n This may be due to "
                            f"a lack of permissions for {RUNNER_NAME!s} to read from the containing "
                            "directory or the file itself may not exist.\n Please correct this "
                            f"issue by following the link: https://halldweb.jlab.org/gluex_sim/SubmitSim.html?prefill={order['ID']!s}&mod=1.  "
                            "Do NOT resubmit this request."
                        )
                    )
                    copy.close()
                except Exception as e:
                    print(e)
                    pass
                update_status_query = (
                    f"UPDATE Project SET Tested={ProjectStatus.TEST_FAILED} "
                    f"WHERE ID={order['ID']!s}"
                )
                self._cursor.execute(update_status_query)
                self._connection.commit()
                return ProjectTestResult.POSTPROCESSING_FAILED
            config_file.write(f"GENERATOR_POSTPROCESS={staged_postprocessing!s}\n")

    def _write_reactions(self, config_file: TextIO, order: Mapping[str, Any]) -> None:
        """Stage reactions configuration files and append their payload settings."""
        if order["ReactionLines"] != "":
            if order["ReactionLines"][0:5] == "file:":
                jana_config_file = order["ReactionLines"][5:]
                copy_loc = "ifarm2401-ib"
                if "scosg2201" in socket.gethostname():
                    copy_loc = "ifarm2401"
                print(
                    f"scp {RUNNER_NAME!s}@{copy_loc!s}:{jana_config_file!s} /osgpool/halld/{RUNNER_NAME!s}/REQUESTEDMC_CONFIGS/{order['ID']!s}_jana.config"
                )
                subprocess.call(
                    f"scp {RUNNER_NAME!s}@{copy_loc!s}:{jana_config_file!s} /osgpool/halld/{RUNNER_NAME!s}/REQUESTEDMC_CONFIGS/{order['ID']!s}_jana.config",
                    shell=True,
                )
                if _user_path(
                    f"REQUESTEDMC_CONFIGS/{order['ID']!s}_jana.config"
                ).exists():
                    update_str = (
                        f"UPDATE Project SET ReactionLines='file:/osgpool/halld/{RUNNER_NAME!s}/REQUESTEDMC_CONFIGS/{order['ID']!s}_jana.config' "
                        f"WHERE ID={order['ID']!s}"
                    )
                    print(update_str)
                    self._cursor.execute(update_str)
                    self._connection.commit()
                else:
                    print("could not copy file", jana_config_file)
                    msg = EmailMessage()
                    msg.set_content(
                        (
                            "Could not test the project because MCwrapper-bot could not copy the "
                            f"following file: {jana_config_file!s}\n This may be due to a lack "
                            f"of permissions for {RUNNER_NAME!s} to read from the containing directory "
                            "or the file itself may not exist.\n Shortly you will receive a second "
                            "email that the actual test has failed, please use the link contained "
                            "in the second email to correct this problem."
                        )
                    )
                    msg["Subject"] = (
                        f"GlueX MC Request #{order['ID']!s} Could not be tested properly"
                    )
                    msg["From"] = "MCwrapper-bot"
                    msg["To"] = str(order["Email"])
                    s = smtplib.SMTP("localhost")
                    s.send_message(msg)
                    s.quit()
                    pass
            else:
                jana_config_file = _user_path(
                    f"REQUESTEDMC_CONFIGS/{order['ID']!s}_jana.config"
                ).open("w")
                jana_plugins = "PLUGINS danarest,monitoring_hists,mcthrown_tree"
                if order["ReactionLines"]:
                    jana_plugins += f",ReactionFilter\n{order['ReactionLines']!s}"
                else:
                    jana_plugins += "\n"
                jana_config_file.write(jana_plugins)
                jana_config_file.close()
            config_file.write(
                f"CUSTOM_PLUGINS=file:/osgpool/halld/{RUNNER_NAME!s}/REQUESTEDMC_CONFIGS/{order['ID']!s}_jana.config\n"
            )


class ProjectTester:
    """Stage generator inputs and validate projects with short MC runs."""

    def __init__(self, connection: Any, cursor: Any) -> None:
        self._connection = connection
        self._cursor = cursor
        self._payload_writer = PayloadConfigWriter(connection, cursor)

    def stage_generator_config(self, order: MutableMapping[str, Any]) -> str:
        """Stage the generator file on submit nodes and return its location."""
        project_id = order["ID"]
        print("checking/getting the generator config for project:", str(project_id))
        config_path = order["Generator_Config"].strip()
        name = "" if config_path.endswith("/") else Path(config_path).name
        config_directory = Path("/osgpool/halld") / RUNNER_NAME / "REQUESTEDMC_CONFIGS"
        staged_config = config_directory / f"{project_id}_{name}"
        running_hostname = socket.gethostname()
        is_submit_node = (
            running_hostname == "scosg16.jlab.org"
            or running_hostname == "scosg20.jlab.org"
            or "scosg2201" in running_hostname
        )
        if not Path(config_path).is_file() and is_submit_node:
            print(
                f"File not found and on submit node, attempting to copy to {config_directory}/"
            )
            copy_loc = "ifarm2401-ib"
            if "scosg2201" in running_hostname:
                copy_loc = "ifarm2401"
            print(
                f"scp {RUNNER_NAME}@{copy_loc}:{config_path.lstrip()} {staged_config}"
            )
            subprocess.call(
                f"scp {RUNNER_NAME}@{copy_loc}:{config_path.lstrip()} {staged_config}",
                shell=True,
            )
            print(
                "Updating order gen config:", config_path, "------>", str(staged_config)
            )
            order["Generator_Config"] = str(staged_config)
            print("new order config:", order["Generator_Config"])
            print("returning", str(staged_config))
            return str(staged_config)
        elif Path(config_path).is_file() and is_submit_node:
            print("File found and on submit node")
            print(f"scp {config_path} {staged_config}")
            subprocess.call(f"scp {config_path} {staged_config}", shell=True)
            order["Generator_Config"] = str(staged_config)
            return str(staged_config)
        elif not Path(config_path).is_file():
            print("File not found and not on submit node ")
            return str(staged_config)
        return "True"

    def test_in_worker(
        self,
        results_q: Any,
        index: int,
        row: Mapping[str, Any],
        project_id: Union[int, str],
        version_set: str,
        commands_to_call: str = "",
    ) -> Union[str, List[Any]]:
        """Test a project in a worker, record its result, and dispatch or notify."""
        skip_test = False
        test_directory = Path(f"TestProj_{project_id}")
        test_directory.mkdir(parents=True, exist_ok=True)
        os.chdir(test_directory)
        Path(f"MCDispatched_{project_id}.config").unlink(missing_ok=True)
        print(f"TESTING PROJECT {project_id!s}")
        query = f"SELECT * FROM Project WHERE ID={project_id!s}"
        print(f"{index!s}:  {query!s}")
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        order = rows[0]
        original_output_location = order["OutputLocation"]
        original_directory_name = original_output_location.split("/")[-2]
        new_dirname = (
            f"{'_'.join(original_directory_name.split('_')[:-1])!s}_{project_id!s}"
        )
        output_location = original_output_location.replace(
            original_directory_name, new_dirname
        )
        if output_location[-1] == "/":
            output_directory_name = output_location[:-1].split("/")[-1]
        else:
            output_directory_name = output_location.split("/")[-1]
        print("order", order)
        print("========================")
        print(order["Generator_Config"])
        staged_config = self.stage_generator_config(order)
        print(order["Generator_Config"])
        print("========================")
        print(staged_config)
        update_q = (
            f'UPDATE Project SET Generator_Config="{staged_config!s}" '
            f"WHERE ID={project_id!s};"
        )
        print(update_q)
        self._cursor.execute(update_q)
        self._connection.commit()
        if staged_config != "True":
            self._cursor.execute(query)
            rows = self._cursor.fetchall()
            order = rows[0]
            order["Generator_Config"] = staged_config
        already_passed_q = f"SELECT COUNT(*) FROM Jobs WHERE Project_ID={project_id!s}"
        self._cursor.execute(already_passed_q)
        already_passed = self._cursor.fetchall()
        if already_passed[0]["COUNT(*)"] > 0:
            update_query = (
                f"UPDATE Project SET Tested={ProjectStatus.READY}, "
                f'OutputLocation="{output_location!s}" '
                f"WHERE ID={project_id!s};"
            )
            self._cursor.execute(update_query)
            self._connection.commit()
            test_status = ProjectTestResult.ALREADY_PASSED
            return test_status
        output = "Dispatch_Failure"
        errors = "Dispatch_Failure"
        test_status = ProjectTestResult.FAILURE
        if order["RunNumHigh"] != order["RunNumLow"] and order["Generator"] == "file:":
            update_query = (
                f"UPDATE Project SET Tested={ProjectStatus.TEST_FAILED} "
                f"WHERE ID={project_id!s};"
            )
            self._cursor.execute(update_query)
            self._connection.commit()
            print(f"{TerminalColors.FAIL!s}TEST FAILED{TerminalColors.ENDC!s}")
            print(f"rm -rf {order['OutputLocation']!s}")
            return [
                "oh no!!!",
                ProjectTestResult.FAILURE,
                "MCwrapper cannot currently handle an input file with many run numbers properly",
            ]
        if not order["VersionSet"]:
            skip_test = True
            output = "oh no!!!"
            errors = (
                "Somehow a versionSet was not selected.  Please edit the submission "
                "via the link to select a version set."
            )
        if not skip_test:
            payload_status = self._payload_writer.write(order, staged_config)
            run_number = str(order["RunNumLow"])
            if payload_status == ProjectTestResult.POSTPROCESSING_FAILED:
                print("Error in writing payload")
                print("could not find postprocessing file(s)")
                status = [
                    "oh no!!!",
                    ProjectTestResult.POSTPROCESSING_FAILED,
                    "could not find postprocessing file(s)",
                ]
                return status
            print(f"{index!s}:  Wrote Payload")
            print("original RCDB QUERY:", order["RCDBQuery"])
            query_to_do = _rcdb_query(order, order["RCDBQuery"])
            if order["RunNumLow"] != order["RunNumHigh"]:
                print(f"RCDB_QUERY IS: {query_to_do!s}")
                connection_string = os.environ.get("RCDB_CONNECTION")
                if not connection_string:
                    connection_string = DEFAULT_RCDB_CONNECTION
                rcdb_db = rcdb.RCDBProvider(connection_string)
                try:
                    running_hostname = socket.gethostname()
                    run_list = []
                    if "scosg2201" in running_hostname:
                        conn_command = (
                            "singularity exec --cleanenv --bind /scigroup/mcwrapper/ --bind /group/halld/:/group/halld/ "
                            "--bind /cvmfs /cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_almalinux_9:latest"
                        )
                        query_line = query_to_do.split("\n")[0]
                        conn_command = (
                            f"{conn_command!s} /scigroup/mcwrapper/gluex_MCwrapper/Utilities/rcdb_wrapper.sh "
                            f'''"{query_line}" {order["RunNumLow"]} {order["RunNumHigh"]}'''
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
                        run_list = json.loads(output)
                    else:
                        rcdb_db = rcdb.RCDBProvider(os.environ.get("RCDB_CONNECTION"))
                        run_list = rcdb_db.select_runs(
                            str(query_to_do), order["RunNumLow"], order["RunNumHigh"]
                        ).get_values(["event_count"], True)
                    print("RunList:", run_list)
                    if run_list == [[]]:
                        print("No runs found for this query")
                        output = "oh no!!!"
                        errors = "No runs found for this query"
                        run_number = -1
                    else:
                        run_number = str(run_list[0][0])
                except Exception as e:
                    print(e)
                    output = e
                    errors = e
                    run_number = -1
                    pass
            working_directory = str(Path.cwd())
            if run_number != -1:
                test_number = 500
                if order["ID"] == 2531:
                    test_number = 50
                command = (
                    f"{MCWRAPPER_BOT_HOME!s}/gluex_MC.py {working_directory!s}/MCDispatched_{project_id!s}.config "
                    f"{run_number!s} {test_number!s} per_file=250000 base_file_number=0 "
                    f"{_stage_options(order)} projid={project_id!s} batch=0 tobundle=0"
                )
                print(command)
            my_env = None
            print(version_set)
            try:
                _write_test_script(project_id, version_set, command)
            except Exception as e:
                print(e)
                pass
            output = "Error in rcdb query"
            errors = f"Error in rcdb query:{query_to_do!s}"
            container_image = "/cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_almalinux_9:latest"
            print(
                (
                    "singularity exec --cleanenv --bind /cvmfs/singularity.opensciencegrid.org/ "
                    f"--bind /var/run/user/  --bind {working_directory!s}:{working_directory!s} "
                    f"--bind /osgpool/halld/{RUNNER_NAME!s}:/osgpool/halld/{RUNNER_NAME!s} "
                    "--bind /group/halld/:/group/halld/ --bind /scigroup/mcwrapper/gluex_MCwrapper:/scigroup/mcwrapper/gluex_MCwrapper "
                    f"{container_image!s} /bin/sh {working_directory!s}/TestProject_runscript_{project_id!s}.sh"
                )
            )
            if run_number != -1:
                p = Popen(
                    (
                        "singularity exec --cleanenv --bind /cvmfs/singularity.opensciencegrid.org/ "
                        f"--bind /var/run/user/  --bind {working_directory!s}:{working_directory!s} "
                        f"--bind /osgpool/halld/{RUNNER_NAME!s}:/osgpool/halld/{RUNNER_NAME!s} "
                        "--bind /group/halld/:/group/halld/ --bind /scigroup/mcwrapper/gluex_MCwrapper:/scigroup/mcwrapper/gluex_MCwrapper "
                        f"{container_image!s} /bin/sh {working_directory!s}/TestProject_runscript_{project_id!s}.sh"
                    ),
                    env=my_env,
                    stdin=PIPE,
                    stdout=PIPE,
                    stderr=PIPE,
                    bufsize=-1,
                    shell=True,
                )
                output, errors = p.communicate()
            output = str(output).replace("\\n", "\n")
            errors = str(errors).replace("\\n", "\n")
            test_status = output.find("Successfully completed")
        if test_status != ProjectTestResult.FAILURE:
            update_query = (
                f"UPDATE Project SET Tested={ProjectStatus.READY}, "
                f'OutputLocation="{output_location!s}" '
                f"WHERE ID={project_id!s};"
            )
            try:
                self._cursor.execute(update_query)
                self._connection.commit()
            except BaseException:
                print("DB connection died. Re-establish and try again.")
                try:
                    self._connection = MySQLdb.connect(
                        host=DB_HOST, user=DB_USER, db=DB_NAME
                    )
                    self._cursor = self._connection.cursor(MySQLdb.cursors.DictCursor)
                    self._cursor.execute(update_query)
                    self._connection.commit()
                except BaseException:
                    print(
                        "WARNING: CANNOT CONNECT TO DATABASE AFTER ParallelTestProject. Terminating."
                    )
                    sys.exit(1)
            try:
                if staged_config != "True":
                    update_config_query = (
                        f'UPDATE Project SET Generator_Config="{staged_config!s}" '
                        f"WHERE ID={project_id!s};"
                    )
                    print(update_config_query)
                    self._cursor.execute(update_config_query)
                    self._connection.commit()
            except Exception as e:
                print(e)
                pass
            print(f"{TerminalColors.OKGREEN!s}TEST SUCCEEDED{TerminalColors.ENDC!s}")
            print(f"rm -rf {order['OutputLocation']!s}")
            directory_result = self._create_output_directory(output_directory_name)
            if directory_result is not None:
                output, errors = directory_result
        else:
            try:
                update_query = (
                    f"UPDATE Project SET Tested={ProjectStatus.TEST_FAILED} "
                    f"WHERE ID={project_id!s};"
                )
                self._cursor.execute(update_query)
                self._connection.commit()
            except Exception as e:
                print(e)
                pass
            print(f"{TerminalColors.FAIL!s}TEST FAILED{TerminalColors.ENDC!s}")
            print(f"rm -rf {order['OutputLocation']!s}")
        status = [output, test_status, errors]
        print("status:", status)
        test_status_query = f"SELECT Tested FROM Project WHERE ID={row['ID']!s}"
        self._cursor.execute(test_status_query)
        test_status_rows = self._cursor.fetchall()
        stored_test_status = test_status_rows[0]["Tested"]
        if stored_test_status == ProjectStatus.READY:
            print("YAY TESTED")
            print(
                (
                    f"{MCWRAPPER_BOT_HOME!s}/Utilities/MCDispatcher.py dispatch -rlim "
                    f"-sys OSG {row['ID']!s}"
                )
            )
            subprocess.call(
                (
                    f"{MCWRAPPER_BOT_HOME!s}/Utilities/MCDispatcher.py dispatch -rlim "
                    f"-sys OSG {row['ID']!s}"
                ),
                shell=True,
            )
        elif stored_test_status == ProjectStatus.UNTESTED:
            print("DB FAILED TO UPDATE WITH Status")
            print("DB", stored_test_status)
            print("Test Status", status[1])
        else:
            self._notify_test_failure(row, status)
        return status

    def test(
        self, project_id: Union[int, str], version_set: str, commands_to_call: str = ""
    ) -> List[Any]:
        """Run a single project test and record its result."""
        test_directory = Path(f"TestProj_{project_id}")
        test_directory.mkdir(parents=True, exist_ok=True)
        os.chdir(test_directory)
        Path(f"MCDispatched_{project_id}.config").unlink(missing_ok=True)
        print(f"TESTING PROJECT {project_id!s}")
        query = f"SELECT * FROM Project WHERE ID={project_id!s}"
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        order = rows[0]
        original_output_location = order["OutputLocation"]
        original_directory_name = original_output_location.split("/")[-2]
        new_dirname = (
            f"{'_'.join(original_directory_name.split('_')[:-1])!s}_{project_id!s}"
        )
        output_location = original_output_location.replace(
            original_directory_name, new_dirname
        )
        print("========================")
        print(order["Generator_Config"])
        staged_config = self.stage_generator_config(order)
        print(order["Generator_Config"])
        print("========================")
        print(staged_config)
        if staged_config != "True":
            self._cursor.execute(query)
            rows = self._cursor.fetchall()
            order = rows[0]
        if order["RunNumHigh"] != order["RunNumLow"] and order["Generator"] == "file:":
            update_query = (
                f"UPDATE Project SET Tested={ProjectStatus.TEST_FAILED} "
                f"WHERE ID={project_id!s};"
            )
            self._cursor.execute(update_query)
            self._connection.commit()
            print(f"{TerminalColors.FAIL!s}TEST FAILED{TerminalColors.ENDC!s}")
            print(f"rm -rf {order['OutputLocation']!s}")
            return [
                "oh no!!!",
                ProjectTestResult.FAILURE,
                "MCwrapper cannot currently handle an input file with many run numbers properly",
            ]
        self._payload_writer.write(order, staged_config)
        run_number = str(order["RunNumLow"])
        if order["RunNumLow"] != order["RunNumHigh"]:
            query_to_do = "@is_production and @status_approved"
            if "recon-2018" in order["VersionSet"]:
                query_to_do = "@is_2018production and @status_approved"
            if "recon-2019" in order["VersionSet"]:
                query_to_do = "@is_dirc_production and @status_approved"
            if order["RCDBQuery"] != "":
                query_to_do = order["RCDBQuery"]
            print(f"RCDB_QUERY IS: {query_to_do!s}")
            connection_string = os.environ.get("RCDB_CONNECTION")
            if not connection_string:
                connection_string = DEFAULT_RCDB_CONNECTION
            rcdb_db = rcdb.RCDBProvider(connection_string)
            try:
                print(
                    f"{query_to_do!s} | {int(order['RunNumLow'])!s} | {int(order['RunNumHigh'])!s}"
                )
                run_list = rcdb_db.select_runs(
                    str(query_to_do), order["RunNumLow"], order["RunNumHigh"]
                ).get_values(["event_count"], True)
                print("RunList:", run_list)
                run_number = str(run_list[0][0])
            except Exception:
                update_query = (
                    f"UPDATE Project SET Tested={ProjectStatus.TEST_FAILED} "
                    f"WHERE ID={project_id!s};"
                )
                print(update_query)
                self._cursor.execute(update_query)
                self._connection.commit()
                print(f"{TerminalColors.FAIL!s}TEST FAILED{TerminalColors.ENDC!s}")
                print(f"rm -rf {order['OutputLocation']!s}")
                try:
                    print("MAILING\n")
                    msg = EmailMessage()
                    e = f"RCDB Query failed: {query_to_do!s}\n"
                    print("Errors:", e)
                    msg.set_content(
                        (
                            f"Your Project ID {order['ID']!s} failed the test.  Please correct "
                            f"this issue by following the link: https://halldweb.jlab.org/gluex_sim/SubmitSim.html?prefill={order['ID']!s}&mod=1.  "
                            "Do NOT resubmit this request.  Write tbritton@jlab.org for additional "
                            "assistance\n\n The log information is reproduced below:\n\n\nThere "
                            f"was a problem with the RCDB query provided\n\n\nErrors:\n\n\n{e!s}\n\n"
                            "IMPORTANT: Rather than cancelling and submitting a new job, you can "
                            f"correct this issue by following the link: https://halldweb.jlab.org/gluex_sim/SubmitSim.html?prefill={order['ID']!s}&mod=1.  "
                            "Do NOT resubmit this request.  Write tbritton@jlab.org for additional "
                            "assistance"
                        )
                    )
                    print("SET CONTENT")
                    msg["Subject"] = (
                        f"Project ID #{order['ID']!s} Failed to test properly"
                    )
                    print("SET SUB")
                    msg["From"] = str("MCwrapper-bot")
                    print("SET FROM")
                    msg["To"] = str(order["Email"])
                    print("SET SUB TO FROM")
                    s = smtplib.SMTP("localhost")
                    print("SENDING")
                    s.quit()
                    copy = _user_path(
                        f"REQUESTED_FAIL_MAILS/email_{order['ID']!s}.log"
                    ).open("w+")
                    copy.write(
                        (
                            "The log information is reproduced below:\n\n\nThere was a problem "
                            f"with the RCDB query provided\n\n\nErrors:\n\n\n{e!s}"
                        )
                    )
                    copy.close()
                except Exception as me:
                    print(me)
                    pass
                return ["Problem with rcdb query", ProjectTestResult.FAILURE, e]
        working_directory = str(Path.cwd())
        command = (
            f"{MCWRAPPER_BOT_HOME!s}/gluex_MC.py {working_directory!s}/MCDispatched_{project_id!s}.config "
            f"{run_number!s} 500 per_file=250000 base_file_number=0 {_stage_options(order)} "
            f"projid={project_id!s} batch=0 tobundle=0"
        )
        print(command)
        test_status = ProjectTestResult.FAILURE
        my_env = None
        _write_test_script(project_id, version_set, command)
        print(
            (
                "singularity exec --cleanenv --bind /cvmfs/singularity.opensciencegrid.org/ "
                f"--bind /var/run/user/ --bind {working_directory!s}:{working_directory!s} "
                f"--bind /osgpool/halld/{RUNNER_NAME!s}:/osgpool/halld/{RUNNER_NAME!s} "
                "--bind /group/halld/:/group/halld/ --bind /scigroup/mcwrapper/gluex_MCwrapper:/scigroup/mcwrapper/gluex_MCwrapper  "
                "/cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_almalinux_9:latest "
                f"/bin/sh {working_directory!s}/TestProject_runscript_{project_id!s}.sh"
            )
        )
        if run_number != -1:
            p = Popen(
                (
                    "singularity exec --cleanenv --bind /cvmfs/singularity.opensciencegrid.org/ "
                    f"--bind /var/run/user/  --bind {working_directory!s}:{working_directory!s} "
                    f"--bind /osgpool/halld/{RUNNER_NAME!s}:/osgpool/halld/{RUNNER_NAME!s} "
                    "--bind /group/halld/:/group/halld/ --bind /scigroup/mcwrapper/gluex_MCwrapper:/scigroup/mcwrapper/gluex_MCwrapper  "
                    "/cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_almalinux_9:latest "
                    f"/bin/sh {working_directory!s}/TestProject_runscript_{project_id!s}.sh"
                ),
                env=my_env,
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
                bufsize=-1,
                shell=True,
            )
        output, errors = p.communicate()
        output = str(output).replace("\\n", "\n")
        errors = str(errors).replace("\\n", "\n")
        test_status = output.find("Successfully completed")
        if test_status != ProjectTestResult.FAILURE:
            update_query = (
                f"UPDATE Project SET Tested={ProjectStatus.READY}, "
                f'OutputLocation="{output_location!s}" '
                f"WHERE ID={project_id!s};"
            )
            self._cursor.execute(update_query)
            self._connection.commit()
            if staged_config != "True":
                update_config_query = (
                    f'UPDATE Project SET Generator_Config="{staged_config!s}" '
                    f"WHERE ID={project_id!s};"
                )
                print(update_config_query)
                self._cursor.execute(update_config_query)
                self._connection.commit()
            print(f"{TerminalColors.OKGREEN!s}TEST SUCCEEDED{TerminalColors.ENDC!s}")
            print(f"rm -rf {order['OutputLocation']!s}")
        else:
            update_query = (
                f"UPDATE Project SET Tested={ProjectStatus.TEST_FAILED} "
                f"WHERE ID={project_id!s};"
            )
            self._cursor.execute(update_query)
            self._connection.commit()
            print(f"{TerminalColors.FAIL!s}TEST FAILED{TerminalColors.ENDC!s}")
            print(f"rm -rf {order['OutputLocation']!s}")
        return [output, test_status, errors]

    def _create_output_directory(
        self, output_directory_name: str
    ) -> Optional[Tuple[bytes, bytes]]:
        """Create the project output marker through Pelican."""
        try:
            os.environ["BEARER_TOKEN_FILE"] = "/var/run/user/10967/bt_u10967"
            os.environ["XDG_RUNTIME_DIR"] = "/run/user/10967"
            token_str = "eval `ssh-agent`; /usr/bin/ssh-add;"
            agent_kill_str = "; ssh-agent -k"
            PELICAN_SERVER = "osdf://jlab-osdf/gluex/osgpool/"
            mkdir_cmd = (
                f"touch createdir; pelican object put createdir {PELICAN_SERVER!s}REQUESTEDMC_OUTPUT/{output_directory_name!s}/.createdir; "
                "rm createdir"
            )
            print(
                "creating directory on osdf: ", token_str + mkdir_cmd + agent_kill_str
            )
            my_env = os.environ.copy()
            p = Popen(
                token_str + mkdir_cmd + agent_kill_str,
                env=my_env,
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
                bufsize=-1,
                shell=True,
            )
            output, errors = p.communicate()
            if str(errors, "utf-8") != "":
                print("ERROR IN MAKING DIR VIA PELICAN")
                print(errors)
                print("============================")
                print(output)
            return (output, errors)
        except Exception as e:
            print(e)
            pass

    def _notify_test_failure(
        self, row: Mapping[str, Any], status: Sequence[Any]
    ) -> None:
        """Send test diagnostics and save the failure log."""
        try:
            print("MAILING\n")
            msg = EmailMessage()
            print(status[0])
            print(status[2])
            failure_excerpt = extract_job_failure(status[0])
            msg.set_content(
                (
                    f"Your Project ID {row['ID']!s} failed the test.  Please correct this "
                    f"issue by following the link: https://halldweb.jlab.org/gluex_sim/SubmitSim.html?prefill={row['ID']!s}&mod=1.  "
                    "Do NOT resubmit this request.  Write tbritton@jlab.org for additional "
                    f"assistance\n\n The log information is reproduced below:\n\n\n{status[0]!s}\n\n\n"
                    f"Errors:\n\nThe full stderr is reproduced above.\n\n{failure_excerpt!s}\n\n"
                    f"{status[2]!s}\n\nIMPORTANT: Rather than cancelling and submitting "
                    f"a new job, you can correct this issue by following the link: https://halldweb.jlab.org/gluex_sim/SubmitSim.html?prefill={row['ID']!s}&mod=1.  "
                    "Do NOT resubmit this request.  Write tbritton@jlab.org for additional "
                    "assistance"
                )
            )
            print("SET CONTENT")
            msg["Subject"] = f"MC Project ID #{row['ID']!s} Failed to test properly"
            print("SET SUB")
            msg["From"] = str("MCwrapper-bot")
            print("SET FROM")
            msg["To"] = str(row["Email"])
            print("SET SUB TO FROM")
            s = smtplib.SMTP("localhost")
            print("SENDING")
            s.send_message(msg)
            print("SENT")
            s.quit()
            try:
                copy = _user_path(f"REQUESTED_FAIL_MAILS/email_{row['ID']!s}.log").open(
                    "w+"
                )
                copy.write(
                    (
                        f"The log information is reproduced below:\n\n\n{status[0]!s}\n\n\n"
                        f"Errors:\n\nThe full stderr is reproduced above.\n\n{failure_excerpt!s}\n\n"
                        f"{status[2]!s}"
                    )
                )
                copy.close()
            except Exception as e:
                print(e)
                pass
        except BaseException:
            print("UH OH MAILING")
            log = _user_path(f"{row['ID']!s}.err").open("w+")
            log.write(f"this was broke: \n{status[2]!s}")
            log.write(f"this was broke: \n{status[0]!s}")
            log.close()


def parallel_test_project(
    results_q: Any,
    index: int,
    row: Mapping[str, Any],
    project_id: Union[int, str],
    version_set: str,
    commands_to_call: str = "",
) -> Union[str, List[Any]]:
    """Open a worker database session and run its project test."""
    connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
    cursor = connection.cursor(MySQLdb.cursors.DictCursor)
    tester = ProjectTester(connection, cursor)
    return tester.test_in_worker(
        results_q, index, row, project_id, version_set, commands_to_call
    )


def _user_path(*parts: str) -> Path:
    """Build a storage path under the submitting user's OSG directory."""
    return Path("/osgpool/halld") / RUNNER_NAME / Path(*parts)


class ProjectDispatcher:
    """Control project dispatch, retry, cancellation, and automatic launch."""

    def __init__(self, connection: Any, cursor: Any) -> None:
        self._connection = connection
        self._cursor = cursor
        self._payload_writer = PayloadConfigWriter(connection, cursor)
        self._tester = ProjectTester(connection, cursor)

    def recall_all(self) -> None:
        """Recall OSG attempts for stopped, canceled, or manually completed projects."""
        query = (
            "SELECT a.BatchJobID, a.BatchSystem "
            "FROM Attempts a "
            "JOIN Jobs j ON a.Job_ID = j.ID "
            "JOIN Project p ON j.Project_ID = p.ID "
            f'WHERE a.SubmitHost = "{HOST_NAME!s}" '
            f'AND a.Status IN ("{AttemptStatus.IDLE}", "{AttemptStatus.RUNNING}", "{AttemptStatus.HELD}") '
            f"AND p.Tested IN ({ProjectStatus.STOPPED}, {ProjectStatus.CANCEL_REQUESTED}, {ProjectStatus.DECLARED_COMPLETE});"
        )
        print(query)
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        print(f"RECALLING {len(rows)!s}")
        attempt_index = 0
        for row in rows:
            attempt_index = attempt_index + 1
            print("RECALLING:", str(attempt_index), "/", str(len(rows)))
            if row["BatchSystem"] == "OSG":
                command = f"condor_rm {row['BatchJobID']!s}"
                cmd = Popen(command.split(" "), stdout=PIPE, stderr=PIPE)
                out, err = cmd.communicate()
                print(str(err, "utf-8"))
                if "not found" in str(err, "utf-8"):
                    print(f"clear {row['BatchJobID']!s}")
                    update_query = (
                        f'UPDATE Attempts SET Status="{AttemptStatus.REMOVED}" '
                        f'''WHERE BatchJobID="{row["BatchJobID"]!s}" '''
                        f'&& SubmitHost="{HOST_NAME!s}"'
                    )
                    print(update_query)
                    self._cursor.execute(update_query)
                    self._connection.commit()
                if "Failed to end classad" in str(err, "utf-8"):
                    break

    def declare_all_complete(self) -> None:
        """Queue completed projects for bundling and notify after bundling."""
        connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
        cursor = connection.cursor(MySQLdb.cursors.DictCursor)
        query = (
            "SELECT ID,OutputLocation,Email,Completed_Time,Tested "
            "FROM Project "
            f"WHERE Tested={ProjectStatus.DECLARED_COMPLETE} "
            f"OR Tested={ProjectStatus.DECLARED_BUNDLED} "
            "&& Notified IS NULL;"
        )
        cursor.execute(query)
        rows = cursor.fetchall()
        print("DECLARING", rows, "COMPLETE")
        for proj in rows:
            print(proj)
            print("=====================")
            hours_to_wait = 4
            if proj["Completed_Time"] is None:
                continue
            if datetime.datetime.now() < proj["Completed_Time"] + datetime.timedelta(
                hours=hours_to_wait
            ):
                continue
            connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
            cursor = connection.cursor(MySQLdb.cursors.DictCursor)
            if (
                proj["Tested"] != ProjectStatus.BUNDLED
                and proj["Tested"] != ProjectStatus.DECLARED_BUNDLING
                and (proj["ID"] >= 3440)
            ):
                update_status_tobundle_q = (
                    f"UPDATE Project SET Tested={ProjectStatus.DECLARED_BUNDLE_PENDING} "
                    f"WHERE ID={proj['ID']!s}"
                )
                print(update_status_tobundle_q)
                cursor.execute(update_status_tobundle_q)
                connection.commit()
            print(proj.keys())
            if proj["Tested"] == ProjectStatus.DECLARED_BUNDLED:
                del_comm = (
                    f"touch {proj['ID']!s}; pelican object put {proj['ID']!s} osdf://jlab-osdf/gluex/osgpool/to_be_scrubbed/{proj['ID']!s}; "
                    f"rm {proj['ID']!s}"
                )
                print(del_comm)
                try:
                    subprocess.call(del_comm, shell=True)
                except Exception as e:
                    print(e)
                    pass
                connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
                cursor = connection.cursor(MySQLdb.cursors.DictCursor)
                msg = EmailMessage()
                msg.set_content(
                    (
                        f"Your Project ID {proj['ID']!s} has been declared completed.  Outstanding "
                        f"jobs have been recalled. Output may be found here:\n{proj['OutputLocation']!s}"
                    )
                )
                msg["Subject"] = f"GlueX MC Request #{proj['ID']!s} Declared Completed"
                msg["From"] = "MCwrapper-bot"
                msg["To"] = str(proj["Email"])
                s = smtplib.SMTP("localhost")
                s.send_message(msg)
                s.quit()
                update_query = (
                    f"UPDATE Project SET Notified={PROJECT_NOTIFIED},Tested={ProjectStatus.DECLARED_COMPLETE} "
                    f"WHERE ID={proj['ID']!s}"
                )
                cursor.execute(update_query)
                connection.commit()

    def cancel_all(self) -> None:
        """Notify and delete projects whose cancellation has been requested."""
        query = (
            "SELECT ID,OutputLocation,Email "
            "FROM Project "
            f"WHERE Tested={ProjectStatus.CANCEL_REQUESTED};"
        )
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        for proj in rows:
            msg = EmailMessage()
            msg.set_content(
                (
                    f"Your Project ID {proj['ID']!s} has been canceled.  Outstanding jobs "
                    "have been recalled."
                )
            )
            msg["Subject"] = f"GlueX MC Request #{proj['ID']!s} Cancelled"
            msg["From"] = "MCwrapper-bot"
            msg["To"] = str(proj["Email"])
            s = smtplib.SMTP("localhost")
            s.send_message(msg)
            s.quit()
            sql = (
                "DELETE "
                "FROM Attempts "
                "WHERE Job_ID IN ( SELECT ID "
                "FROM Jobs "
                f"WHERE Project_ID={proj['ID']!s} );"
            )
            sql2 = f"DELETE FROM Jobs WHERE Project_ID={proj['ID']!s};"
            sql3 = (
                "UPDATE Project SET Is_Dispatched='0',Completed_Time=NULL,Dispatched_Time=NULL "
                f"WHERE ID={proj['ID']!s}"
            )
            self._cursor.execute(sql)
            self._cursor.execute(sql2)
            self._cursor.execute(sql3)
            delq = f"DELETE FROM Project WHERE ID={proj['ID']!s};"
            self._cursor.execute(delq)
            self._connection.commit()

    def auto_launch(self, running_limit_override: bool) -> None:
        """Recall, finalize, retry, and test eligible projects when storage permits."""
        print("RECALLING...")
        self.recall_all()
        print("CANCELING...")
        self.cancel_all()
        print("DECLARING...")
        self.declare_all_complete()
        print("GETTING DF...")
        disk_usage = str(
            subprocess.check_output("df -h | grep /osgpool/halld", shell=True), "utf-8"
        ).strip()
        print(disk_usage)
        percent = int(disk_usage.split(" ")[-2].split("%")[0])
        print("disk is", percent, "% full")
        if percent > 75:
            print("disk is too full, not launching")
            return
        print("RETRYING...")
        self.retry_all_jobs(running_limit_override)
        print("TESTING...")
        query = (
            "SELECT ID,Email,VersionSet,Tested,UName "
            "FROM Project "
            f"WHERE (Tested = {ProjectStatus.UNTESTED}) "
            "&& Dispatched_Time IS NULL "
            "ORDER BY (SELECT Priority "
            "FROM Users "
            "WHERE name=UName) DESC "
            "LIMIT 10;"
        )
        print(query)
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        print("TESTING: ", rows)
        print("Testing: ", len(rows))
        if len(rows) == 0:
            return
        test_processes = []
        results_array = []
        for row in rows:
            results_array.append([])
        results_q = Queue()
        results_q.put(results_array)
        for i in range(0, len(rows)):
            if rows[i]["Tested"] != ProjectStatus.UNTESTED:
                continue
            print(f"Test process {i!s}")
            p = Process(
                target=parallel_test_project,
                args=(results_q, i, rows[i], rows[i]["ID"], str(rows[i]["VersionSet"])),
            )
            test_processes.append(p)
            time.sleep(1)
        for i in range(0, len(test_processes)):
            time.sleep(5)
            test_processes[i].start()
        for i in range(0, len(test_processes)):
            if test_processes[i].is_alive():
                test_processes[i].join(15 * 60)

    def list_undispatched(self) -> None:
        """Print projects that have not been dispatched."""
        query = "SELECT * FROM Project WHERE Is_Dispatched='0' || Is_Dispatched='0.0'"
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        print(rows)

    def dispatch_project(
        self, project_id: Union[int, str], system: str, percent: Union[float, str]
    ) -> None:
        """Look up a project and dispatch it to the selected batch system."""
        query = f"SELECT * FROM Project WHERE ID={project_id!s}"
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        if len(rows) != 0:
            if system == "INTERACTIVE":
                self.dispatch_to_interactive(project_id, rows[0], percent)
            elif system == "SWIF":
                self.dispatch_to_swif(project_id, rows[0], percent)
            elif system == "OSG":
                self.dispatch_to_osg(project_id, rows[0], percent)
        else:
            print(f"Error: Cannot find Project with ID={project_id!s}")

    def retry_all_jobs(self, running_limit_override: bool = False) -> None:
        """Retry unfinished projects and repair notified completion timestamps."""
        print(f"retrying all jobs. rlim={running_limit_override!s}")
        query = (
            "SELECT ID,Notified "
            "FROM Project "
            "WHERE Completed_Time IS NULL "
            "&& Is_Dispatched=1.0 "
            f"&& Tested!={ProjectStatus.STOPPED} "
            f"&& Tested!={ProjectStatus.DECLARED_COMPLETE} "
            f"&& Tested!={ProjectStatus.RETRY_EXCLUDED} "
            f"&& Tested!={ProjectStatus.CANCEL_REQUESTED};"
        )
        print(query)
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        for row in rows:
            if row["Notified"] != PROJECT_NOTIFIED:
                print(f"Retrying Project {row['ID']!s}")
                self.retry_jobs_from_project(row["ID"], not running_limit_override)
            else:
                print("Attempting to clean up Completed_Time")
                completion_time_query = (
                    "SELECT MAX(Completed_Time) "
                    "FROM Attempts "
                    "WHERE Job_ID IN (SELECT ID "
                    "FROM Jobs "
                    f"WHERE Project_ID={row['ID']!s});"
                )
                print(completion_time_query)
                self._cursor.execute(completion_time_query)
                completion_time_rows = self._cursor.fetchall()
                print("Final Time", completion_time_rows[0]["MAX(Completed_Time)"])
                update_project_status = (
                    f"UPDATE Project SET Completed_Time='{completion_time_rows[0]['MAX(Completed_Time)']!s}' "
                    f"WHERE ID={row['ID']!s};"
                )
                print(update_project_status)
                self._cursor.execute(update_project_status)
                self._connection.commit()

    def remove_all_jobs(self, project_id: Union[int, str]) -> None:
        """Print OSG batch IDs for the selected project."""
        query = (
            "SELECT * "
            "FROM Attempts "
            "WHERE ID IN (SELECT MAX(ID) "
            "FROM Attempts "
            "GROUP BY Job_ID) "
            f'&& SubmitHost="{HOST_NAME!s}" '
            "&& Job_ID IN (SELECT ID "
            "FROM Jobs "
            f"WHERE IsActive={JOB_ACTIVE} "
            f"&& Project_ID={project_id!s});"
        )
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        for row in rows:
            if row["BatchSystem"] == "OSG":
                print(row["BatchJobID"])

    def retry_jobs_from_project(
        self, project_id: Union[int, str], count_limit: bool
    ) -> None:
        """Retry failed project attempts with the configured retry count limit."""
        all_osg = True
        query = (
            "SELECT Attempts.* "
            "FROM Jobs "
            "INNER JOIN Attempts ON Attempts.Job_ID = Jobs.id "
            "AND Attempts.id = (SELECT MAX(id) "
            "FROM Attempts latest_attempts "
            "WHERE latest_attempts.job_id = Jobs.id) "
            f"WHERE Project_ID = {project_id!s}"
        )
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        project_status_query = f"SELECT Tested FROM Project WHERE ID={project_id!s}"
        self._cursor.execute(project_status_query)
        proj = self._cursor.fetchall()[0]
        retried_count = 0
        over_limit_count = 0
        job_index = 0
        swif_retry_ids = []
        print(len(rows), "Jobs to retry")
        for row in rows:
            print(
                "Project",
                project_id,
                "   ",
                job_index + 1,
                "/",
                len(rows),
                ":",
                row["Job_ID"],
                ":",
                row["BatchSystem"],
            )
            if row["BatchSystem"] == "SWIF":
                if (
                    row["Status"] == "succeeded"
                    and row["ExitCode"] != ExitCode.SUCCESS
                    or (
                        row["Status"] == "problem"
                        and row["ExitCode"] != str(ExitCode.RANDOM_TRIGGER_NOT_FOUND)
                    )
                    or (
                        proj["Tested"] == ProjectStatus.READY
                        and row["Status"] == "canceled"
                    )
                    or (
                        proj["Tested"] == ProjectStatus.READY
                        and row["Status"] == "failed"
                    )
                ):
                    print("Retrying SWIF job: ", row["Job_ID"])
                    limit_query = f"SELECT COUNT(*) FROM Attempts WHERE BatchJobID={row['BatchJobID']!s}"
                    self._cursor.execute(limit_query)
                    attempt_count_row = self._cursor.fetchall()[0]
                    print(attempt_count_row)
                    if attempt_count_row["COUNT(*)"] < 15:
                        swif_retry_ids.append(row["BatchJobID"])
                        retried_count = retried_count + 1
                    if all_osg:
                        self.retry_job(row["Job_ID"], all_osg)
            elif row["BatchSystem"] == "OSG":
                if (
                    row["Status"] == str(AttemptStatus.COMPLETED)
                    and row["ExitCode"] != ExitCode.SUCCESS
                    or row["Status"] == str(AttemptStatus.REMOVED)
                    or row["Status"] == str(AttemptStatus.HELD)
                    or (row["Status"] == str(AttemptStatus.UNCLASSIFIED))
                ):
                    print("Retrying OSG job: ", row["Job_ID"])
                    if count_limit:
                        count_query = f"SELECT COUNT(Job_ID) FROM Attempts WHERE Job_ID={row['Job_ID']!s}"
                        self._cursor.execute(count_query)
                        count = self._cursor.fetchall()
                        if int(count[0]["COUNT(Job_ID)"]) > 15:
                            over_limit_count = over_limit_count + 1
                            print("Job above count limit")
                            continue
                        if row["Status"] == str(AttemptStatus.UNCLASSIFIED):
                            status_update = (
                                f'UPDATE Attempts SET Status="{AttemptStatus.COMPLETED}" '
                                f"WHERE ID ={row['ID']!s}"
                            )
                            self._cursor.execute(status_update)
                            self._connection.commit()
                    self.retry_job(row["Job_ID"], all_osg)
                    retried_count = retried_count + 1
            job_index = job_index + 1
        print(swif_retry_ids)
        if len(swif_retry_ids) != 0 and (not all_osg):
            project_query = f"SELECT * FROM Project WHERE ID={project_id!s}"
            self._cursor.execute(project_query)
            proj = self._cursor.fetchall()
            location_parts_count = len(proj[0]["OutputLocation"].split("/"))
            retry_swif_command = (
                f"swif retry-jobs -workflow proj{project_id!s}_{proj[0]['OutputLocation'].split('/')[location_parts_count - 2]!s} "
                f"{' '.join(swif_retry_ids)!s}"
            )
            print(retry_swif_command)
            subprocess.call(retry_swif_command, shell=True)
        print(f"retried {retried_count!s} Jobs")
        print(f"{over_limit_count!s} jobs over restart limit of 15")

    def retry_job(self, job_id: Union[int, str], all_osg: bool = False) -> None:
        """Retry a SWIF job or submit a replacement OSG attempt."""
        query = (
            "SELECT Attempts.*,MAX(Attempts.Creation_Time) "
            "FROM Attempts "
            f"WHERE Attempts.Job_ID = {job_id!s}"
        )
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        job_query = f"SELECT * FROM Jobs WHERE ID={job_id!s}"
        self._cursor.execute(job_query)
        job = self._cursor.fetchall()
        project_query = (
            "SELECT * "
            "FROM Project "
            "WHERE ID IN (SELECT Project_ID "
            "FROM Jobs "
            f"WHERE ID={job_id!s})"
        )
        self._cursor.execute(project_query)
        proj = self._cursor.fetchall()
        print(f"AllOSG? {all_osg!s}")
        if rows[0]["BatchSystem"] == "SWIF" and (not all_osg):
            location_parts_count = len(proj[0]["OutputLocation"].split("/"))
            command = (
                f"swif retry-jobs -workflow proj{proj[0]['ID']!s}_{proj[0]['OutputLocation'].split('/')[location_parts_count - 2]!s} "
                f"{rows[0]['BatchJobID']!s}"
            )
            print(command)
            subprocess.call(command, shell=True)
        elif rows[0]["BatchSystem"] == "OSG" or all_osg:
            _copy_payload_template("OSGShell.config", job_id)
            print("writing payload")
            self._payload_writer.write(proj[0], "True", job_id)
            print("payload written")
            events_per_file = 20000
            events_per_file_query = (
                "SELECT PerFile "
                "FROM Generator_perfiles "
                f'''WHERE GenName="{proj[0]["Generator"]!s}";'''
            )
            print(events_per_file_query)
            self._cursor.execute(events_per_file_query)
            generator_rows = self._cursor.fetchall()
            try:
                events_per_file = generator_rows[0]["PerFile"]
            except Exception as e:
                print("exception in per file num")
                print("genrow:", generator_rows)
                print(e)
                print("Using default per_file_num")
                pass
            print("per file num", events_per_file)
            command = (
                f"python3 {MCWRAPPER_BOT_HOME!s}/gluex_MC.py MCDispatched_{job_id!s}.config "
                f"{job[0]['RunNumber']!s} {job[0]['NumEvts']!s} per_file={events_per_file!s}  "
                f"base_file_number={job[0]['FileNumber']!s} {_stage_options(proj[0])} "
                f"projid=-{job_id!s} batch=1 tobundle=0"
            )
            print(command)
            os.environ["BEARER_TOKEN_FILE"] = "/var/run/user/10967/bt_u10967"
            os.environ["XDG_RUNTIME_DIR"] = "/run/user/10967"
            status_out, status_err = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ,
                executable="/bin/bash",
            ).communicate()
            print(command, "STATUS:")
            print(str(status_out, "utf-8"))

    def cancel_job(self, job_id: Union[int, str]) -> None:
        """Deactivate a job and update its project dispatch fraction."""
        query = f"UPDATE Jobs SET IsActive={JOB_INACTIVE} WHERE ID={job_id!s}"
        self._cursor.execute(query)
        self._connection.commit()
        project_id_query = f"SELECT Project_ID FROM Jobs WHERE ID={job_id!s}"
        self._cursor.execute(project_id_query)
        project_id_rows = self._cursor.fetchall()
        project_query = (
            "SELECT SUM(NumEvts) "
            "FROM Jobs "
            f"WHERE IsActive={JOB_ACTIVE} "
            f"&& Project_ID={project_id_rows[0]['Project_ID']!s}"
        )
        self._cursor.execute(project_query)
        proj = self._cursor.fetchall()
        project_events_query = f"SELECT NumEvents FROM Project WHERE ID={project_id_rows[0]['Project_ID']!s}"
        self._cursor.execute(project_events_query)
        project_event_rows = self._cursor.fetchall()
        active_events = 0
        if str(proj[0]["SUM(NumEvts)"]) != "None":
            active_events = proj[0]["SUM(NumEvts)"]
        total_events = 1
        if project_event_rows[0]["NumEvents"] != "None":
            total_events = project_event_rows[0]["NumEvents"]
        dispatched_fraction = float(active_events) / float(total_events)
        update_query = (
            f"UPDATE Project SET Is_Dispatched='{dispatched_fraction!s}' "
            f"WHERE ID={project_id_rows[0]['Project_ID']!s}"
        )
        self._cursor.execute(update_query)
        self._connection.commit()

    def dispatch_to_interactive(
        self,
        project_id: Union[int, str],
        order: Mapping[str, Any],
        percent: Union[float, str],
    ) -> None:
        """Submit the remaining requested events to an interactive run."""
        Path(f"MCDispatched_{project_id}.config").unlink(missing_ok=True)
        self._payload_writer.write(order, "True")
        run_number = _run_range(order)
        completed_events_query = (
            "SELECT SUM(NumEvts), MAX(FileNumber) "
            "FROM Jobs "
            f"WHERE IsActive={JOB_ACTIVE} "
            f"&& Project_ID={project_id!s} "
            "&& ID IN (SELECT Job_ID "
            "FROM Attempts "
            f"WHERE ExitCode={ExitCode.SUCCESS});"
        )
        self._cursor.execute(completed_events_query)
        completed_event_rows = self._cursor.fetchall()
        requested_events_query = (
            f"SELECT NumEvents FROM Project WHERE ID={project_id!s};"
        )
        self._cursor.execute(requested_events_query)
        requested_event_rows = self._cursor.fetchall()
        requested_events = requested_event_rows[0]["NumEvents"]
        completed_events = 0
        if completed_event_rows[0]["SUM(NumEvts)"]:
            completed_events = completed_event_rows[0]["SUM(NumEvts)"]
        first_file_number = -1
        if completed_event_rows[0]["MAX(FileNumber)"]:
            first_file_number = completed_event_rows[0]["MAX(FileNumber)"]
        first_file_number += 1
        events_to_produce = min(
            int(float(requested_events) * float(percent)),
            requested_events - completed_events,
        )
        dispatched_fraction = float(events_to_produce + completed_events) / float(
            requested_events
        )
        if events_to_produce > 0:
            update_query = (
                f"UPDATE Project SET Is_Dispatched='{dispatched_fraction!s}', "
                "Dispatched_Time=NOW() "
                f"WHERE ID={project_id!s};"
            )
            self._cursor.execute(update_query)
            self._connection.commit()
            command = (
                f"python3 {MCWRAPPER_BOT_HOME!s}/gluex_MC.py MCDispatched_{project_id!s}.config "
                f"{run_number!s} {events_to_produce!s} per_file=250000 base_file_number={first_file_number!s} "
                f"{_stage_options(order)} projid={project_id!s} batch=0 tobundle=0"
            )
            print(command)
            subprocess.call(command, shell=True)
        else:
            print("All jobs submitted for this order")

    def dispatch_to_swif(
        self,
        project_id: Union[int, str],
        order: Mapping[str, Any],
        percent: Union[float, str],
    ) -> None:
        """Submit the remaining requested events to SWIF."""
        _copy_payload_template("SWIFShell.config", project_id)
        self._payload_writer.write(order, "True")
        run_number = _run_range(order)
        completed_events_query = (
            "SELECT SUM(NumEvts), MAX(FileNumber) "
            "FROM Jobs "
            f"WHERE IsActive={JOB_ACTIVE} "
            f"&& Project_ID={project_id!s} "
            "&& ID IN (SELECT Job_ID "
            "FROM Attempts "
            f"WHERE ExitCode={ExitCode.SUCCESS});"
        )
        self._cursor.execute(completed_events_query)
        completed_event_rows = self._cursor.fetchall()
        requested_events_query = (
            f"SELECT NumEvents FROM Project WHERE ID={project_id!s};"
        )
        self._cursor.execute(requested_events_query)
        requested_event_rows = self._cursor.fetchall()
        requested_events = requested_event_rows[0]["NumEvents"]
        completed_events = 0
        if completed_event_rows[0]["SUM(NumEvts)"]:
            completed_events = completed_event_rows[0]["SUM(NumEvts)"]
        first_file_number = -1
        if completed_event_rows[0]["MAX(FileNumber)"]:
            first_file_number = completed_event_rows[0]["MAX(FileNumber)"]
        first_file_number += 1
        events_to_produce = min(
            int(float(requested_events) * float(percent)),
            requested_events - completed_events,
        )
        dispatched_fraction = float(events_to_produce + completed_events) / float(
            requested_events
        )
        if events_to_produce > 0:
            update_query = (
                f"UPDATE Project SET Is_Dispatched='{dispatched_fraction!s}', "
                "Dispatched_Time=NOW() "
                f"WHERE ID={project_id!s};"
            )
            self._cursor.execute(update_query)
            self._connection.commit()
            events_per_file = 50000
            events_per_file_query = (
                "SELECT PerFile "
                "FROM Generator_perfiles "
                f'''WHERE GenName="{order["Generator"]!s}";'''
            )
            self._cursor.execute(events_per_file_query)
            rows = self._cursor.fetchall()
            try:
                events_per_file = rows[0]["PerFile"]
            except Exception as e:
                print(e)
                pass
            command = (
                f"python3 {MCWRAPPER_BOT_HOME!s}/gluex_MC.py MCDispatched_{project_id!s}.config "
                f"{run_number!s} {events_to_produce!s} per_file={events_per_file!s} "
                f"base_file_number={first_file_number!s} {_stage_options(order)} projid={project_id!s} "
                "batch=2 tobundle=0"
            )
            print(command)
            subprocess.call(command, shell=True)
        else:
            print("All jobs submitted for this order")

    def dispatch_to_osg(
        self,
        project_id: Union[int, str],
        order: Mapping[str, Any],
        percent: Union[float, str],
    ) -> None:
        """Submit the full project event count to OSG."""
        print("Dispatching to OSG")
        _copy_payload_template("OSGShell.config", project_id)
        self._payload_writer.write(order, "True")
        run_number = _run_range(order)
        update_query = (
            "UPDATE Project SET Is_Dispatched='1.0', "
            "Dispatched_Time=NOW() "
            f"WHERE ID={project_id!s};"
        )
        self._cursor.execute(update_query)
        self._connection.commit()
        events_per_file = 20000
        events_per_file_query = (
            "SELECT PerFile "
            "FROM Generator_perfiles "
            f'''WHERE GenName="{order["Generator"]!s}";'''
        )
        self._cursor.execute(events_per_file_query)
        rows = self._cursor.fetchall()
        try:
            events_per_file = rows[0]["PerFile"]
        except Exception as e:
            print(e)
            pass
        command = (
            f"python3 {MCWRAPPER_BOT_HOME!s}/gluex_MC.py MCDispatched_{project_id!s}.config "
            f"{run_number!s} {order['NumEvents']!s} per_file={events_per_file!s} "
            f"base_file_number=0 {_stage_options(order)} projid={project_id!s} "
            f"logdir=/osgpool/halld/{RUNNER_NAME!s}/REQUESTEDMC_LOGS/{order['OutputLocation'].split('/')[7]!s} "
            "batch=1 tobundle=0"
        )
        print(command)
        status_out, status_error = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ,
        ).communicate()

    def write_config(self, project_id: Union[int, str]) -> None:
        """Stage the generator configuration and print the project payload."""
        query = f"SELECT * FROM Project WHERE ID={project_id!s}"
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        print(rows)
        staged_config = self._tester.stage_generator_config(rows[0])
        self._payload_writer.render(rows[0], staged_config)

    def test_project(self, project_id: Union[int, str]) -> None:
        """Test a requested project and dispatch it or save its diagnostics."""
        query = (
            f"SELECT Email,VersionSet,Tested,UName FROM Project WHERE ID={project_id!s}"
        )
        self._cursor.execute(query)
        row = self._cursor.fetchall()[0]
        status = self._tester.test(project_id, row["VersionSet"], "")
        if status[1] != ProjectTestResult.FAILURE:
            subprocess.call(
                (
                    f"{MCWRAPPER_BOT_HOME!s}/Utilities/MCDispatcher.py dispatch -rlim "
                    f"-sys OSG {project_id!s}"
                ),
                shell=True,
            )
        else:
            Path(f"{project_id}.out").write_text(str(status[0]))
            Path(f"{project_id}.err").write_text(str(status[2]))

    def dispatch_all(self, system: str, percent: Union[float, str]) -> None:
        """Dispatch each project whose dispatch fraction is not one."""
        query = "SELECT ID FROM Project WHERE Is_Dispatched!='1.0'"
        self._cursor.execute(query)
        rows = self._cursor.fetchall()
        for row in rows:
            self.dispatch_project(row["ID"], system, percent)


def main(argv: Sequence[str]) -> None:
    """Parse dispatcher options and execute the selected operation."""
    if RUNNER_NAME not in ALLOWED_USERS:
        print("ERROR: You must be tbritton or mcwrap to run this script")
        sys.exit(1)
    connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
    cursor = connection.cursor(MySQLdb.cursors.DictCursor)
    dispatcher = ProjectDispatcher(connection, cursor)
    if _user_path(".ALLSTOP").is_file():
        print("ALL STOP DETECTED")
        sys.exit(1)
    numprocesses_running = subprocess.check_output(
        [
            (
                f"echo `ps all -u {RUNNER_NAME!s} | grep MCDispatcher.py | grep -v "
                "grep | wc -l`"
            )
        ],
        shell=True,
    )
    project_id = -1
    mode = ""
    system = "NULL"
    percent = 1.0
    running_limit_override = False
    for argument_index, argument in enumerate(argv):
        if argument_index == 1 or len(argv) == 1:
            mode = str(argv[0]).upper()
        if argument_index == len(argv) - 1:
            project_id = argv[argument_index]
        if argument[0] == "-":
            print(argument)
            if argument == "-sys":
                system = str(argv[argument_index + 1]).upper()
            if argument == "-percent":
                percent = argv[argument_index + 1]
            if argument == "-rlim":
                running_limit_override = True
    print("num running", int(numprocesses_running))
    if int(numprocesses_running) < 2 or running_limit_override:
        print("RUNNING", mode, running_limit_override)
        if mode == "DISPATCH":
            if project_id != "All":
                dispatcher.dispatch_project(project_id, system, percent)
            elif project_id == "All":
                dispatcher.dispatch_all(system, percent)
        elif mode == "VIEW":
            dispatcher.list_undispatched()
        elif mode == "TEST":
            dispatcher.test_project(project_id)
        elif mode == "RETRYJOB":
            dispatcher.retry_job(project_id)
        elif mode == "RETRYJOBS":
            dispatcher.retry_jobs_from_project(project_id, False)
        elif mode == "RETRYALLJOBS":
            dispatcher.retry_all_jobs(running_limit_override)
        elif mode == "CANCELJOB":
            dispatcher.cancel_job(project_id)
        elif mode == "AUTOLAUNCH":
            print("AUTOLAUNCHING NOW")
            dispatcher.auto_launch(running_limit_override)
        elif mode == "REMOVEJOBS":
            dispatcher.remove_all_jobs(project_id)
        elif mode == "WRITECONFIG":
            dispatcher.write_config(project_id)
        else:
            print("MODE NOT FOUND")
    connection.close()


if __name__ == "__main__":
    main(sys.argv[1:])
