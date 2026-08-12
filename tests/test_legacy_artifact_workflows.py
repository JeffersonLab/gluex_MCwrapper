from collections import Counter
from pathlib import Path

from tests.legacy_subprocess import FakeCommandResult
from tests.legacy_subprocess import LegacyRun
from tests.legacy_subprocess import LegacyShellRun
from tests.legacy_subprocess import run_legacy
from tests.legacy_subprocess import run_legacy_shell


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
UTILITIES = REPOSITORY_ROOT / "Utilities"


def test_bundle_wrapper_duplicate_process_smoke_characterization():
    process_probe = (
        "echo `ps all -u mcwrap | grep MCBundle_wrapper.py | grep -v grep | wc -l`"
    )
    result = run_legacy(
        LegacyRun(
            entry_point=UTILITIES / "MCBundle_wrapper.py",
            username="mcwrap",
            intercepted_commands={
                process_probe: FakeCommandResult(stdout="5\n"),
                "hostname": FakeCommandResult(stdout="ifarm2402.jlab.org\n"),
            },
        )
    )

    assert result.exit_status == 0
    assert result.stderr == ""
    assert result.stdout.rstrip().splitlines() == [
        "numprocesses_running: 5",
        "Hostname: ifarm2402.jlab.org",
        "5 process(es) of MCBundle_wrapper.py already running.  Exiting.",
    ]
    assert [effect["operation"] for effect in result.sql] == ["connect", "cursor"]
    assert [effect["operation"] for effect in result.effects] == [
        "connect",
        "cursor",
        "run",
        "run",
    ]
    assert result.files == {}


def test_merger_existing_marker_smoke_characterization():
    result = run_legacy(
        LegacyRun(
            entry_point=UTILITIES / "MCMerger.py",
            argv=("input", "output", "-noclean"),
            files={"input/.keep": "", "output/.merging": ""},
        )
    )

    assert result.exit_status == 102  # Legacy sys.exit(-666), truncated by POSIX.
    assert result.stderr == ""
    assert result.stdout.rstrip().splitlines() == [
        "given path:  input",
        "given path:  output",
        "Merging already in progress.  Exiting.",
    ]
    assert [effect["operation"] for effect in result.sql] == ["connect", "cursor"]
    assert result.commands == []
    assert result.files == {"input/.keep": "", "output/.merging": ""}


def test_hddm_helper_simulation_stream_smoke_characterization():
    result = run_legacy(
        LegacyRun(
            entry_point=UTILITIES / "merge_hddm.py",
            argv=("merged.hddm", "first.hddm", "second.hddm"),
            hddm_inputs=(
                {"flavor": "s", "path": "first.hddm", "entries": ["one", "two"]},
                {"flavor": "s", "path": "second.hddm", "entries": ["three"]},
            ),
        )
    )

    assert result.exit_status == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.sql == []
    assert result.commands == []
    assert [
        (effect["operation"], effect["args"])
        for effect in result.effects
        if effect["boundary"] == "hddm"
    ] == [
        ("ostream", ["s", "merged.hddm"]),
        ("istream", ["s", "first.hddm"]),
        ("write", ["s", "merged.hddm", "one"]),
        ("write", ["s", "merged.hddm", "two"]),
        ("istream", ["s", "second.hddm"]),
        ("write", ["s", "merged.hddm", "three"]),
    ]


def test_mover_python_duplicate_process_smoke_characterization():
    process_probe = (
        "echo `ps all -u tbritton | grep MCMover.py | grep -v grep | wc -l`"
    )
    result = run_legacy(
        LegacyRun(
            entry_point=UTILITIES / "MCMover.py",
            intercepted_commands={
                process_probe: FakeCommandResult(stdout="2\n"),
            },
        )
    )

    assert result.exit_status == 0
    assert result.stdout == "2\n"
    assert result.stderr == ""
    assert [effect["operation"] for effect in result.sql] == [
        "connect",
        "cursor",
        "connection_close",
    ]
    assert [effect["operation"] for effect in result.effects] == [
        "connect",
        "cursor",
        "run",
        "connection_close",
    ]
    assert result.files == {}


def test_mover_shell_worker_no_work_smoke_uses_only_mapped_roots():
    mapped_home = "mapped/osgpool/halld/mcwrap"
    result = run_legacy_shell(
        LegacyShellRun(
            entry_point=UTILITIES / "MCMover.csh",
            path_mappings={
                "/osgpool/halld/$runner": mapped_home,
                "/w/halld-scshelf2101/halld3/home/mcwrap/": "mapped/shared/",
                "/work/halld/gluex_simulations/REQUESTED_MC/": "mapped/output/",
                "/work/halld3/REQUESTED_MC/": "mapped/output-halld3/",
                "/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC": (
                    "mapped/legacy-output"
                ),
                "/tmp": "mapped/tmp",
            },
            files={
                mapped_home + "/local_setup.sh": "export FIXTURE_SETUP=1\n",
                mapped_home + "/MCWrapper_Logs/.keep": "",
            },
            commands={
                "date": FakeCommandResult(stdout="Wed Aug 12 12:00:00 EDT 2026\n"),
                "whoami": FakeCommandResult(stdout="mcwrap\n"),
                "hostname": FakeCommandResult(stdout="fixture-host.jlab.org\n"),
                "ps": FakeCommandResult(stdout="fixture process\n"),
                "grep": FakeCommandResult(stdout="fixture process\n"),
                "wc": FakeCommandResult(stdout="1\n"),
            },
        )
    )

    assert result.exit_status == 0
    assert result.stdout == "too many running\n"
    assert result.stderr == ""
    assert Counter(command["argv"][0] for command in result.commands) == Counter(
        {"date": 1, "whoami": 1, "hostname": 1, "ps": 1, "grep": 2, "wc": 1}
    )
    log_name = mapped_home + "/MCWrapper_Logs/MCWrapperMover.log"
    assert result.files[log_name] == (
        "Current date and time: Wed Aug 12 12:00:00 EDT 2026\n"
    )
    assert all(not path.startswith("/") for path in result.files)
