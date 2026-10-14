#!/usr/bin/env python3
"""Bundle pending MC projects and record their completion or retry status."""

import os
import pwd
import re
import shlex
import subprocess
import sys
from datetime import datetime
from typing import Any, Mapping, NamedTuple, Sequence

import MySQLdb

DB_HOST = "hallddb.jlab.org"
DB_USER = "mcuser"
DB_NAME = "gluex_mc"
MCWRAPPER_BOT_HOME = "/scigroup/mcwrapper/gluex_MCwrapper/"
LOG_DIR = "/scratch/mcwrap/mergetemp/"
CACHE_OUTPUT_ROOT = "/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/"
INPUT_OUTPUT_ROOT = "/work/osgpool/halld/REQUESTEDMC_OUTPUT/"
MAX_RUNNING_WRAPPERS = 4
BUNDLING_STATUS = {20: 21, 40: 41}
COMPLETED_STATUS = {21: 100, 41: 400}
RETRY_STATUS = {21: 20, 41: 40}
PENDING_PROJECTS_QUERY = (
    "SELECT * FROM Project WHERE (Tested=20 OR Tested=40) "
    "AND Notified is NULL order by ID asc LIMIT 1"
)

try:
    database_connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
    database_cursor = database_connection.cursor(MySQLdb.cursors.DictCursor)
except BaseException:
    print("WARNING: CANNOT CONNECT TO DATABASE. DON'T KNOW WHAT TO DO.")
    sys.exit(1)


class HostSettings(NamedTuple):
    """Host-specific directories and the current Python interpreter."""

    merge_dir: str
    staging_dir: str
    python_command: str

    @classmethod
    def from_hostname(cls, hostname: str) -> "HostSettings":
        """Return this host's existing paths, using the wrapper's interpreter."""
        merge_dirs = {
            "dtn2303.jlab.org": "/export/halld/mcwrap/mergetemp/",
            "ifarm2402.jlab.org": "/scratch/mcwrap/mergetemp/",
        }
        merge_dir = merge_dirs.get(hostname, "/osgpool/halld/mcwrap/mergetemp/")
        if hostname in merge_dirs:
            return cls(merge_dir, "/work/osgpool/halld//REQUESTED_MC/", sys.executable)
        return cls(
            merge_dir,
            "/volatile/halld/gluex_simulations/REQUESTED_MC/",
            sys.executable,
        )


def _get_hostname() -> str:
    """Read the hostname using the existing shell command."""
    return subprocess.check_output(["hostname"], shell=True).decode().strip()


def _project_name(input_dir: str) -> str:
    """Read the final directory name, allowing one trailing slash."""
    return (
        input_dir.split("/")[-2] if input_dir[-1] == "/" else input_dir.split("/")[-1]
    )


def _remove_merge_marker(merge_dir: str, project_name: str) -> None:
    """Run the existing command to remove the project's merging marker."""
    subprocess.run([f"rm {merge_dir}/{project_name}/.merging"], shell=True)


def _write_bundle_log(project_name: str, output: bytes, suffix: str = "") -> None:
    """Write merger output using the existing timestamped log naming scheme."""
    timestamp = datetime.now().strftime("%Y_%m_%d-%p%I_%M_%S")
    with open(f"{LOG_DIR}{project_name}_{timestamp}{suffix}.log", "w") as log:
        log.write(output.decode("utf-8"))


def bundle_files(input_dir: str, output_dir: str, merge_dir: str) -> str:
    """Run the merger and return its existing SUCCESS, ONGOING, or ERROR result."""
    project_name = _project_name(input_dir)
    for directory in (merge_dir + project_name, output_dir):
        command = "mkdir -p " + directory
        print(command)
        subprocess.call(command.split(" "))
    settings = HostSettings.from_hostname(_get_hostname())
    command = (
        shlex.quote(settings.python_command)
        + " "
        + MCWRAPPER_BOT_HOME
        + "/Utilities/MCMerger.py -tempdir "
        + merge_dir
        + project_name
        + "/ "
        + input_dir
        + " "
        + output_dir
        + " -noclean"
    )
    print("BUNDLING WITH", command)
    try:
        output = subprocess.check_output(shlex.split(command), stderr=subprocess.STDOUT)
        result = int(
            re.findall(r"Returning final_success: (\d+)", output.decode("utf-8"))[0]
        )
        print("subprocess output", result)
        if result == -666:
            print("Bundling ongoing")
            return "ONGOING"
        print("Bundler return code", result)
        _remove_merge_marker(merge_dir, project_name)
        if result == 0:
            return "SUCCESS"
        _write_bundle_log(project_name, output)
        return "ERROR"
    except subprocess.CalledProcessError as error:
        print(error.output)
        _write_bundle_log(project_name, error.output, suffix="_2")
        _remove_merge_marker(merge_dir, project_name)
        return "ERROR"


class ProjectBundler:
    """Coordinate pending projects, merger execution, and database status updates."""

    def __init__(self, merge_dir: str, staging_dir: str) -> None:
        self._merge_dir = merge_dir
        self._staging_dir = staging_dir

    def _connect(self) -> None:
        """Open a database session at the same points as the existing workflow."""
        self._connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
        self._cursor = self._connection.cursor(MySQLdb.cursors.DictCursor)

    def run(self) -> None:
        """Select pending projects and bundle those not already marked as merging."""
        print(PENDING_PROJECTS_QUERY)
        self._connect()
        self._cursor.execute(PENDING_PROJECTS_QUERY)
        projects = self._cursor.fetchall()
        print(projects)
        for project in projects:
            if not self._bundle_project(project):
                return

    def _update_status(
        self, project_id: int, status: int, print_query: bool = False
    ) -> None:
        """Update and commit the project's Tested status."""
        query = f"UPDATE Project SET Tested={status} WHERE ID={project_id}"
        if print_query:
            print(query)
        self._cursor.execute(query)
        self._connection.commit()

    def _bundle_project(self, project: Mapping[str, Any]) -> bool:
        """Process a project; return False to retain the existing early-stop case."""
        print(project)
        input_dir = project["OutputLocation"].replace(
            CACHE_OUTPUT_ROOT, INPUT_OUTPUT_ROOT
        )
        input_dir = input_dir.replace("//", "/")
        output_dir = "/".join(project["OutputLocation"].split("/")[:-1]) + "/"
        output_dir = output_dir.replace(CACHE_OUTPUT_ROOT, self._staging_dir)
        print(project["ID"])
        project_name = _project_name(input_dir)
        marker = self._merge_dir + project_name + "/.merging"
        print(marker)
        if os.path.isfile(marker):
            print("Currently being bundled")
            return True

        running_status = BUNDLING_STATUS.get(project["Tested"], 50)
        if running_status == 50:
            return False
        self._update_status(project["ID"], running_status, print_query=True)
        self._cursor.execute(f"SELECT Tested FROM Project WHERE ID={project['ID']}")
        verified = self._cursor.fetchone()
        if verified["Tested"] != running_status:
            print(
                f"ERROR: Tried to update project status to {running_status} "
                f"but it is {verified['Tested']}"
            )
            sys.exit(1)
        self._connection.close()

        print("BEGINNING BUNDLE")
        outcome = bundle_files(input_dir, output_dir, self._merge_dir)
        self._connect()
        print("OUT: ", outcome)
        if outcome == "SUCCESS":
            completed_status = COMPLETED_STATUS.get(running_status, 500)
            self._update_status(project["ID"], completed_status)
        elif outcome == "ONGOING":
            print("Bundling ongoing. Will try again later, if needed.")
        else:
            original_status = int(project["Tested"])
            retry_status = RETRY_STATUS.get(original_status, original_status)
            self._update_status(project["ID"], retry_status)
        self._connection.close()
        return True


def _count_running_wrappers(user_name: str) -> int:
    """Count wrapper processes using the existing shell command."""
    command = (
        f"echo `ps all -u {user_name} | grep MCBundle_wrapper.py "
        "| grep -v grep | wc -l`"
    )
    return int(subprocess.check_output([command], shell=True))


def main(argv: Sequence[str]) -> None:
    """Bundle pending projects unless the existing process limit is exceeded."""
    runner_name = pwd.getpwuid(os.getuid())[0]
    process_count = _count_running_wrappers(runner_name)
    print(f"numprocesses_running: {process_count}")
    hostname = _get_hostname()
    print("Hostname:", hostname)
    settings = HostSettings.from_hostname(hostname)
    if process_count > MAX_RUNNING_WRAPPERS:
        print(
            f"{process_count} process(es) of MCBundle_wrapper.py "
            "already running.  Exiting."
        )
        sys.exit(0)
    print(f"{process_count} process(es) of MCBundle_wrapper.py running.  Continuing.")
    ProjectBundler(settings.merge_dir, settings.staging_dir).run()


if __name__ == "__main__":
    main(sys.argv[1:])
