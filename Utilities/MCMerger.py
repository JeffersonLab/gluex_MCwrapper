"""Bundle MCwrapper output by run, then move the merged results to their destination.

Originally written by Darius Darulis, 2022.
"""

import argparse
import glob
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import (
    Any,
    DefaultDict,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    cast,
)

import MySQLdb
from mc_status import MergerResult

DB_HOST = "hallddb.jlab.org"
DB_USER = "mcuser"
DB_NAME = "gluex_mc"
MCWRAPPER_BOT_HOME = "/scigroup/mcwrapper/gluex_MCwrapper/"
SUPPORTED_EXTENSIONS = (".root", ".hddm", ".hdds", ".conf", ".in")
FilePattern = Tuple[str, str]
FileGroups = Mapping[FilePattern, Mapping[str, Set[str]]]
NameMap = Mapping[Any, Any]
ARCHIVE_ERROR = 2
"""An archive could not be created or extracted."""

try:
    database_connection = MySQLdb.connect(host=DB_HOST, user=DB_USER, db=DB_NAME)
    database_cursor = database_connection.cursor(MySQLdb.cursors.DictCursor)
except BaseException:
    print("Could not connect to database")
    sys.exit(1)


def directory_path(path: str) -> str:
    """Validate a directory argument and print the supplied path."""
    print("given path: ", path)
    if path and Path(path).is_dir():
        return path
    raise argparse.ArgumentTypeError(f"{path} is not a valid path.")


def _make_directory(path: Path) -> int:
    """Create parents and translate I/O errors into the merger's status codes."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(error, file=sys.stderr)
        return 1
    return MergerResult.SUCCESS


def _remove_input_directory(path: Path) -> None:
    """Remove the input after success, without following a directory symlink."""
    try:
        if path.is_symlink():
            path.unlink()
        else:
            shutil.rmtree(path)
    except OSError as error:
        print(error, file=sys.stderr)


def _archive_member_name(file_name: str) -> str:
    """Build relative archive member names, including an explicit ./ prefix."""
    parts = file_name.lstrip("/").split("/")
    # Like tar, discard the prefix through the final parent-directory component.
    for index in range(len(parts) - 1, -1, -1):
        if parts[index] == "..":
            return "/".join(parts[index + 1 :])
    return "/".join(parts)


def _log_archive_member(member: tarfile.TarInfo) -> tarfile.TarInfo:
    """Print archive member names in the bundler's captured output."""
    print(f"{member.name}{'/' if member.isdir() else ''}")
    return member


def _create_archive(
    archive_path: Path, file_names: Sequence[str], remove_files: bool = False
) -> int:
    """Write an uncompressed archive; remove inputs only after successful close."""
    try:
        with tarfile.open(archive_path, "w", format=tarfile.GNU_FORMAT) as archive:
            for file_name in file_names:
                archive.add(
                    file_name,
                    arcname=_archive_member_name(file_name),
                    filter=_log_archive_member,
                )
        if remove_files:
            for file_name in file_names:
                path = Path(file_name)
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
    except (OSError, tarfile.TarError) as error:
        print(error, file=sys.stderr)
        return ARCHIVE_ERROR
    return MergerResult.SUCCESS


def _extract_archive(archive_path: Path, output_dir: Path, strip_count: int) -> int:
    """Extract a locally created bundle, stripping the specified prefix components."""
    try:
        with tarfile.open(archive_path, "r:*", errorlevel=2) as archive:
            members: List[tarfile.TarInfo] = []
            for member in archive.getmembers():
                parts = member.name.split("/")
                if len(parts) <= strip_count:
                    continue
                member.name = "/".join(parts[strip_count:]).lstrip("/")
                if not member.name:
                    continue
                if member.islnk():
                    member.linkname = "/".join(
                        member.linkname.split("/")[strip_count:]
                    ).lstrip("/")
                _log_archive_member(member)
                members.append(member)
            # These bundles are created locally. Preserve extraction behavior on
            # newer Python versions without requiring their filter API on 3.8.
            setattr(
                archive,
                "extraction_filter",
                getattr(tarfile, "fully_trusted_filter", None),
            )
            archive.extractall(output_dir, members=members)
    except (OSError, tarfile.TarError) as error:
        print(error, file=sys.stderr)
        return ARCHIVE_ERROR
    return MergerResult.SUCCESS


def parse_file_name(file_name: str) -> Optional[Tuple[str, str, str]]:
    """Split a recognized six-digit run and three- or four-digit file number."""
    match = re.search(r"([0-9]{6})_([0-9]{3,4})(?![0-9])", file_name)
    if match:
        return file_name[: match.start()], match.group(1), file_name[match.end() :]
    return None


def collect_file_groups(
    files: Sequence[str],
) -> DefaultDict[FilePattern, DefaultDict[str, Set[str]]]:
    """Group supported file names by prefix and suffix, with unique runs per group."""
    groups: DefaultDict[FilePattern, DefaultDict[str, Set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for file_name in files:
        if file_name.endswith(SUPPORTED_EXTENSIONS):
            entry = parse_file_name(file_name)
            if entry:
                prefix, run_number, suffix = entry
                groups[(prefix, suffix)]["run_nums"].add(run_number)
    return groups


def get_run_range(name_map: NameMap) -> Tuple[int, int]:
    """Find run bounds; return (100000000000000, -1) when no runs are present."""
    minimum, maximum = 100000000000000, -1
    for name in name_map:
        if name == "trees":
            for reaction in name_map[name]:
                for run_number in name_map[name][reaction]["run_nums"]:
                    run = int(run_number)
                    minimum, maximum = min(run, minimum), max(run, maximum)
        else:
            for run_number in name_map[name]["run_nums"]:
                run = int(run_number)
                minimum, maximum = min(run, minimum), max(run, maximum)
    return minimum, maximum


def get_directory_structure(root_dir: str) -> Dict[str, Any]:
    """Build a nested directory and file-group map in filesystem walk order."""
    name_map: Dict[str, Any] = {}
    root_dir = root_dir.rstrip(os.sep)
    if not root_dir:
        return name_map
    root_path = Path(root_dir)
    for path, _directories, files in os.walk(root_path):
        folders = Path(path).relative_to(root_path.parent).parts
        parent = name_map
        for folder in folders[:-1]:
            parent = cast(Dict[str, Any], dict.get(parent, folder))
        if files:
            parent[folders[-1]] = collect_file_groups(files)
        else:
            parent[folders[-1]] = dict.fromkeys(files)
    return name_map


def count_file_groups(name_map: NameMap) -> int:
    """Sum per-group unique run counts across nested directories."""
    count = 0
    for value in name_map.values():
        if isinstance(value, dict):
            count += count_file_groups(value)
        elif isinstance(value, set):
            count += len(value)
    return count


def check_success(name_map: NameMap, output_path: str) -> bool:
    """Compare the expected group count with all non-hidden output files."""
    expected_count = count_file_groups(name_map)
    print(f"Number of unique files to be output is {expected_count}")
    output_count = sum(
        len([file_name for file_name in files if not file_name.startswith(".")])
        for _root, _directories, files in os.walk(Path(output_path))
    )
    print(f"Number of unique files output is {output_count}")
    return expected_count == output_count


class BundleActions:
    """Bundle ROOT, HDDM, and configuration files using per-run checkpoints."""

    def __init__(self, source_dir: str) -> None:
        self._source_dir = source_dir
        self._source_path = Path(source_dir)

    def _archive_input(self, path: Path) -> str:
        """Include the source-directory prefix in archive input paths."""
        return f"{self._source_dir}/{path.relative_to(self._source_path)}"

    def _archive_pattern(self, archive_path: Path, pattern: Path) -> int:
        """Archive files matching a wildcard; report an error when no inputs match."""
        file_pattern = self._archive_input(pattern)
        file_names = sorted(glob.glob(file_pattern)) or [file_pattern]
        return _create_archive(archive_path, file_names)

    def bundle_root(self, name_map: NameMap, path: str) -> int:
        """Merge ROOT files with hadd; archive monitoring histograms with tar."""
        return_code = MergerResult.SUCCESS
        print("Path: ", path)
        # The prefix preceding // determines the checkpoint root.
        root_prefix = path.split("//")[0]
        root_path = Path(root_prefix or "/")
        output_dir = Path(path)
        print("Root path: ", root_prefix)
        if (root_path / ".bash_root").is_file():
            print("Skipping bash_root step")
            return return_code
        checkpoint_path = root_path / ".checkpoints" / "root"
        for directory in name_map:
            print(f"Path: {path}    dir_type: {directory}")
            if not isinstance(directory, str):
                continue
            _make_directory(output_dir / directory)
            _make_directory(checkpoint_path / directory)
            if directory == "trees":
                for pattern in name_map["trees"]:
                    prefix, suffix = pattern
                    folder_name = prefix.rstrip("_")
                    return_code += _make_directory(output_dir / directory / folder_name)
                    return_code += _make_directory(
                        checkpoint_path / directory / folder_name
                    )
                    for run_number in name_map["trees"][pattern]["run_nums"]:
                        output_path = (
                            output_dir
                            / directory
                            / folder_name
                            / f"{prefix}{run_number}{suffix}"
                        )
                        checkpoint = (
                            checkpoint_path
                            / directory
                            / folder_name
                            / f"{prefix}{run_number}{suffix}.done"
                        )
                        if checkpoint.is_file():
                            continue
                        inputs = (
                            self._source_path
                            / "root"
                            / directory
                            / f"{prefix}{run_number}*{suffix}"
                        )
                        command = f"hadd -v 1 -f {output_path} {inputs}"
                        result = subprocess.run([command], shell=True)
                        return_code += result.returncode
                        if result.returncode == MergerResult.SUCCESS:
                            checkpoint.open("a").close()
            else:
                _make_directory(output_dir / directory)
                _make_directory(checkpoint_path / directory)
                for pattern in name_map[directory]:
                    prefix, suffix = pattern
                    for run_number in name_map[directory][pattern]["run_nums"]:
                        output_path = (
                            output_dir / directory / f"{prefix}{run_number}{suffix}"
                        )
                        checkpoint = (
                            checkpoint_path
                            / directory
                            / f"{prefix}{run_number}{suffix}"
                        )
                        inputs = (
                            self._source_path
                            / "root"
                            / directory
                            / f"{prefix}{run_number}*{suffix}"
                        )
                        if directory == "monitoring_hists":
                            checkpoint = checkpoint.with_name(
                                f"{checkpoint.name}.tar.done"
                            )
                        else:
                            checkpoint = checkpoint.with_name(f"{checkpoint.name}.done")
                            command = f"hadd -v 1 -f {output_path} {inputs}"
                        if checkpoint.is_file():
                            continue
                        if directory == "monitoring_hists":
                            result_code = self._archive_pattern(
                                output_path.with_name(f"{output_path.name}.tar"), inputs
                            )
                        else:
                            result_code = subprocess.run(
                                [command], shell=True
                            ).returncode
                        return_code += result_code
                        if result_code == MergerResult.SUCCESS:
                            checkpoint.open("a").close()
        if return_code == MergerResult.SUCCESS:
            print(f"Creating .bash_root file in {path}")
            (root_path / ".bash_root").open("a").close()
        return return_code

    def archive_hddm(self, name_map: FileGroups, path: str) -> int:
        """Archive run files whose indices contain three or four digits."""
        return_code = MergerResult.SUCCESS
        # The prefix preceding // determines the checkpoint root.
        root_path = Path(path.split("//")[0] or "/")
        output_dir = Path(path)
        if (root_path / ".bash_hddm").is_file():
            print("Skipping bash_hddm step")
            return return_code
        checkpoint_path = root_path / ".checkpoints" / "hddm"
        print("Checkpoint path: ", checkpoint_path)
        _make_directory(output_dir)
        _make_directory(checkpoint_path)
        for (prefix, suffix), group in name_map.items():
            for run_number in group["run_nums"]:
                checkpoint = checkpoint_path / f"{prefix}{run_number}{suffix}.tar.done"
                if checkpoint.is_file():
                    continue
                pattern = re.compile(
                    rf"^{re.escape(prefix)}{re.escape(run_number)}_(\d{{3,4}}){re.escape(suffix)}$"
                )
                file_names = [
                    entry
                    for entry in (self._source_path / "hddm").iterdir()
                    if pattern.match(entry.name)
                ]
                if not file_names:
                    continue
                archive = output_dir / f"{prefix}{run_number}{suffix}.tar"
                result_code = _create_archive(
                    archive,
                    [self._archive_input(file_name) for file_name in file_names],
                )
                return_code += result_code
                if result_code == MergerResult.SUCCESS:
                    checkpoint.open("a").close()
        if return_code == MergerResult.SUCCESS:
            print(f"Creating .bash_hddm file in {path}")
            (root_path / ".bash_hddm").open("a").close()
        return return_code

    def archive_configurations(self, name_map: NameMap, path: str) -> int:
        """Archive configuration groups and write per-run and completion markers."""
        return_code = MergerResult.SUCCESS
        # The prefix preceding // determines the checkpoint root.
        root_path = Path(path.split("//")[0] or "/")
        output_dir = Path(path)
        if (root_path / ".bash_configurations").is_file():
            print("Skipping bash_configurations step")
            return return_code
        checkpoint_path = root_path / ".checkpoints" / "configurations"
        print("Checkpoint path: ", checkpoint_path)
        for directory, groups in name_map.items():
            _make_directory(output_dir / directory)
            _make_directory(checkpoint_path / directory)
            for (prefix, suffix), group in groups.items():
                for run_number in group["run_nums"]:
                    checkpoint = (
                        checkpoint_path
                        / directory
                        / f"{prefix}{run_number}{suffix}.tar.done"
                    )
                    if checkpoint.is_file():
                        continue
                    archive = (
                        output_dir / directory / f"{prefix}{run_number}{suffix}.tar"
                    )
                    inputs = (
                        self._source_path
                        / "configurations"
                        / directory
                        / f"{prefix}{run_number}_*{suffix}"
                    )
                    result_code = self._archive_pattern(archive, inputs)
                    return_code += result_code
                    if result_code == MergerResult.SUCCESS:
                        checkpoint.open("a").close()
        if return_code == MergerResult.SUCCESS:
            print(f"Creating .bash_configurations file in {path}")
            (root_path / ".bash_configurations").open("a").close()
        return return_code

    def merge_hddm(self, name_map: FileGroups, path: str) -> int:
        """Merge HDDM runs with merge_hddm.py using the running Python interpreter."""
        return_code = MergerResult.SUCCESS
        # The prefix preceding // determines the checkpoint root.
        root_path = Path(path.split("//")[0] or "/")
        output_dir = Path(path)
        marker = root_path / ".bash_hddm_merge"
        if marker.is_file():
            print("Skipping bash_hddm_merge step")
            return return_code
        checkpoint_path = root_path / ".checkpoints" / "hddm"
        _make_directory(output_dir)
        _make_directory(checkpoint_path)
        for (prefix, suffix), group in name_map.items():
            for run_number in group["run_nums"]:
                print(f"hddm add {run_number}", flush=True)
                checkpoint = checkpoint_path / f"{prefix}{run_number}{suffix}.done"
                if checkpoint.is_file():
                    continue
                command = (
                    f"{shlex.quote(sys.executable)} "
                    f"{Path(MCWRAPPER_BOT_HOME) / 'Utilities' / 'merge_hddm.py'} "
                    f"{output_dir / f'{prefix}{run_number}{suffix}'} "
                    f"{self._source_path / 'hddm' / f'{prefix}{run_number}*{suffix}'}"
                )
                result = subprocess.run([command], shell=True)
                return_code += result.returncode
                if result.returncode == MergerResult.SUCCESS:
                    checkpoint.open("a").close()
        if return_code == MergerResult.SUCCESS:
            print(f"Creating .bash_hddm_merge file in {path}")
            marker.open("a").close()
        return return_code

    def dispatch(self, name_map: NameMap, path: str, merge_hddm: bool = False) -> int:
        """Choose a bundling operation for each directory's file groups."""
        actions = {
            "root": self.bundle_root,
            "hddm": self.merge_hddm if merge_hddm else self.archive_hddm,
            "configurations": self.archive_configurations,
        }
        return_code = MergerResult.SUCCESS
        for directory, groups in name_map.items():
            if type(directory) is not str:
                print(f"{directory} is not a string! Continue recurse_name_map...")
                continue
            if directory in actions:
                # Merged HDDM files are written to the hddm_merge directory.
                output_name = (
                    "hddm_merge" if directory == "hddm" and merge_hddm else directory
                )
                return_code += actions[directory](groups, f"{path}{output_name}/")
        return return_code

    def bundle(
        self, name_map: NameMap, temp_dir: Optional[str], merge_hddm: bool = False
    ) -> int:
        """Run format-specific operations and wrap their outputs in output.tar."""
        return_code = MergerResult.SUCCESS
        if temp_dir is None:
            print("MC", self._source_dir)
            working_dir = self._source_dir
        else:
            print("TEMP", temp_dir)
            working_dir = temp_dir
        return_code += _make_directory(Path(working_dir) / "output")
        return_code += _make_directory(Path(working_dir) / ".checkpoints")
        print("INITIAL BUNDLE STEP DONE")
        return_code += self.dispatch(name_map, f"{working_dir}/output/", merge_hddm)
        # Member prefixes determine the number of components stripped during
        # extraction, including extra separators in the supplied directory.
        return_code += _create_archive(
            Path(working_dir) / "output.tar",
            [f"{working_dir}/output/"],
            remove_files=True,
        )
        return return_code


def move_bundle(source_dir: str, temp_dir: Optional[str], output_dir: str) -> int:
    """Move and extract output.tar using the source path's component count."""
    output_path = Path(output_dir)
    _make_directory(output_path)
    strip_count = source_dir.strip(os.sep).count(os.sep) + 1
    working_dir = source_dir if temp_dir is None else temp_dir
    try:
        shutil.move(
            str(Path(working_dir) / "output.tar"), str(output_path / "output.tar")
        )
    except OSError as error:
        print(error, file=sys.stderr)
    _extract_archive(output_path / "output.tar", output_path, strip_count)
    try:
        (output_path / "output.tar").unlink()
    except OSError as error:
        print(error, file=sys.stderr)
        return 1
    return MergerResult.SUCCESS


class ProjectMerger:
    """Coordinate merging markers, project lookup, bundling, moving, and cleanup."""

    def __init__(self, cursor: "MySQLdb.cursors.DictCursor") -> None:
        self._cursor = cursor

    def run(self, args: argparse.Namespace) -> int:
        """Bundle CLI input paths, check output counts, and clean up successful runs."""
        if args.tempdir is None:
            marker_path = Path(args.output_path) / ".merging"
        else:
            print("Tempdir: ", args.tempdir)
            marker_path = Path(args.tempdir) / ".merging"
        if marker_path.is_file():
            print("Merging already in progress.  Exiting.")
            return MergerResult.ONGOING
        print("Creating .merging file")
        marker_path.open("a").close()
        print("args: ", args)
        if args.P:
            self._cursor.execute("SELECT * FROM Project WHERE ID = %s", args.P)
            project = self._cursor.fetchone()
            # Read project metadata for -P; merge using the CLI directory arguments.
            _project_input = project["OutputLocation"].replace(
                "/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/",
                "/work/halld/gluex_simulations/REQUESTED_MC/",
            )
            location = project["OutputLocation"]
            _project_output = (
                Path(location) if location.endswith("/") else Path(location).parent
            )
        print(f"Moving from: {args.input_path} to {args.output_path}")
        if not args.f and self._has_existing_output(args):
            return -1
        print("INPUT:", args.input_path)
        name_map = get_directory_structure(args.input_path)
        directory_name = Path(args.input_path).name
        print("===================================")
        print(name_map)
        print("dir_type", directory_name)
        print(name_map.keys())
        actions = BundleActions(args.input_path.rstrip(os.sep))
        bundle_result = actions.bundle(
            name_map[directory_name], args.tempdir, args.hddm
        )
        move_result = move_bundle(args.input_path, args.tempdir, args.output_path)
        final_result = bundle_result + move_result
        success_check = check_success(name_map, args.output_path)
        print(
            f"bundle_success: {bundle_result}, move_success: {move_result}, "
            f"final_success: {final_result}, success_check: {success_check}"
        )
        if final_result == MergerResult.SUCCESS and success_check:
            print("Bundling and moving completed succesfully")
            if not args.noclean:
                print(f"Removing {args.input_path}.")
                _remove_input_directory(Path(args.input_path))
        else:
            print(f"Bundling and moving failed with error code {final_result}.")
        print(f"Returning final_success: {final_result}")
        return final_result

    def _has_existing_output(self, args: argparse.Namespace) -> bool:
        search_path = args.input_path if args.tempdir is None else args.tempdir
        for _path, directories, _files in os.walk(Path(search_path)):
            if "output" in directories:
                print(
                    "The directory in the input path might already be in the process "
                    "of bundling. Use the -f flag to clear out and start fresh."
                )
                for _output_path, output_directories, _output_files in os.walk(
                    Path(args.output_path)
                ):
                    for existing_directory in ("configurations", "root", "hddm"):
                        if existing_directory in output_directories:
                            print(
                                "Output path might already contain bundled files. "
                                "Use the -f flag to clear out and start fresh."
                            )
                            return True
        return False


def _parse_args() -> argparse.Namespace:
    """Parse input and output directories, merge options, and cleanup flags."""
    parser = argparse.ArgumentParser(
        description="Bundle and move MCwrapper outputs to another directory."
    )
    parser.add_argument(
        "-f",
        action="store_true",
        help="Force overwrite of any potential existing output.",
    )
    parser.add_argument(
        "input_path",
        type=directory_path,
        help="The input path for directory to be merged.",
    )
    parser.add_argument(
        "output_path",
        type=directory_path,
        help="The output path for the merged directory.",
    )
    parser.add_argument(
        "-hddm",
        action="store_true",
        help=(
            "Use the Python hddm interfaces to merge hddm files instead of bundling "
            "with tar. Warning: may be very slow."
        ),
    )
    parser.add_argument(
        "-noclean",
        action="store_true",
        help="Do not remove the input directory after a succesful merge.",
    )
    parser.add_argument(
        "-tempdir",
        type=directory_path,
        help="Specify a temporary directory in which the bundling will take place.",
    )
    parser.add_argument("-P", help="ID number of the project to bundle.")
    return parser.parse_args()


def main(args: argparse.Namespace) -> int:
    """Run the merger using CLI arguments and the configured database cursor."""
    return ProjectMerger(database_cursor).run(args)


if __name__ == "__main__":
    sys.exit(main(_parse_args()))
