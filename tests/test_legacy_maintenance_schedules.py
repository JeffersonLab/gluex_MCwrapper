from pathlib import Path

import pytest

from tests.legacy_subprocess import FakeCommandResult
from tests.legacy_subprocess import LegacyShellCommandRun
from tests.legacy_subprocess import LegacyShellRun
from tests.legacy_subprocess import run_legacy_shell
from tests.legacy_subprocess import run_legacy_shell_command


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRUBBER = REPOSITORY_ROOT / "Utilities" / "scrub_finished_projects.sh"

TWICE_DAILY = "1 0,12 * * *"
EVERY_FIFTEEN_MINUTES = "*/15 * * * *"
RANDOM_TRIGGER_RSYNC = (
    "rsync -Lpruvt "
    "/lustre24/expphy/cache/halld/gluex_simulations/random_triggers/* "
    "/work/osgpool/halld/random_triggers/"
)
JMIGRATE = (
    "export JMIRROR_MIN_MODIFICATION_AGE_SECONDS=600; "
    "jmigrate -cache -delete written /work/osgpool/halld/REQUESTED_MC "
    "/work/osgpool/halld /mss/halld/gluex_simulations/"
)
EMPTY_REQUESTED_MC = (
    "find /work/osgpool/halld/REQUESTED_MC/* -type d -empty -delete"
)
EMPTY_MERGE_TEMP = "find /scratch/mcwrap/mergetemp/* -type d -empty -delete"
SCRUB_FINISHED = (
    "/scigroup/mcwrapper/gluex_MCwrapper/Utilities/scrub_finished_projects.sh"
)


def test_random_trigger_rsync_schedule_records_the_exact_mapped_transfer():
    assert TWICE_DAILY + " " + RANDOM_TRIGGER_RSYNC == (
        "1 0,12 * * * rsync -Lpruvt "
        "/lustre24/expphy/cache/halld/gluex_simulations/random_triggers/* "
        "/work/osgpool/halld/random_triggers/"
    )
    result = run_legacy_shell_command(
        LegacyShellCommandRun(
            command=RANDOM_TRIGGER_RSYNC,
            path_mappings={
                "/lustre24/expphy/cache/halld/gluex_simulations/random_triggers/": (
                    "mapped/random-source/"
                ),
                "/work/osgpool/halld/random_triggers/": "mapped/random-target/",
            },
            files={"mapped/random-source/run-120001.hddm": "fixture"},
            commands={"rsync": FakeCommandResult()},
        )
    )

    assert result.exit_status == 0
    assert result.stderr == ""
    assert result.commands == [
        {
            "argv": [
                "rsync",
                "-Lpruvt",
                "<WORKDIR>/mapped/random-source/run-120001.hddm",
                "<WORKDIR>/mapped/random-target/",
            ]
        }
    ]


def test_jmigrate_schedule_records_deletion_intent_and_age_environment():
    assert EVERY_FIFTEEN_MINUTES + " " + JMIGRATE == (
        "*/15 * * * * export JMIRROR_MIN_MODIFICATION_AGE_SECONDS=600; "
        "jmigrate -cache -delete written /work/osgpool/halld/REQUESTED_MC "
        "/work/osgpool/halld /mss/halld/gluex_simulations/"
    )
    result = run_legacy_shell_command(
        LegacyShellCommandRun(
            command=JMIGRATE,
            path_mappings={
                "/work/osgpool/halld/REQUESTED_MC": "mapped/requested-mc",
                "/work/osgpool/halld": "mapped/osgpool-halld",
                "/mss/halld/gluex_simulations/": "mapped/mass-storage/",
            },
            commands={
                "jmigrate": FakeCommandResult(
                    recorded_environment=("JMIRROR_MIN_MODIFICATION_AGE_SECONDS",)
                )
            },
        )
    )

    assert result.exit_status == 0
    assert result.stderr == ""
    assert result.commands == [
        {
            "argv": [
                "jmigrate",
                "-cache",
                "-delete",
                "written",
                "<WORKDIR>/mapped/requested-mc",
                "<WORKDIR>/mapped/osgpool-halld",
                "<WORKDIR>/mapped/mass-storage/",
            ],
            "environment": {"JMIRROR_MIN_MODIFICATION_AGE_SECONDS": "600"},
        }
    ]


@pytest.mark.parametrize(
    ("command", "production_root", "fixture_root"),
    [
        (
            EMPTY_REQUESTED_MC,
            "/work/osgpool/halld/REQUESTED_MC/",
            "mapped/requested-mc/",
        ),
        (
            EMPTY_MERGE_TEMP,
            "/scratch/mcwrap/mergetemp/",
            "mapped/merge-temp/",
        ),
    ],
)
def test_empty_directory_schedules_record_exact_find_deletion_intent(
    command, production_root, fixture_root
):
    assert TWICE_DAILY + " " + command in {
        "1 0,12 * * * find /work/osgpool/halld/REQUESTED_MC/* "
        "-type d -empty -delete",
        "1 0,12 * * * find /scratch/mcwrap/mergetemp/* -type d -empty -delete",
    }
    result = run_legacy_shell_command(
        LegacyShellCommandRun(
            command=command,
            path_mappings={production_root: fixture_root},
            files={fixture_root + "candidate/.keep": "fixture"},
            commands={"find": FakeCommandResult()},
        )
    )

    assert result.exit_status == 0
    assert result.stderr == ""
    assert result.commands == [
        {
            "argv": [
                "find",
                "<WORKDIR>/" + fixture_root + "candidate",
                "-type",
                "d",
                "-empty",
                "-delete",
            ]
        }
    ]


def test_scrubber_schedule_records_only_mapped_recursive_removals():
    assert TWICE_DAILY + " " + SCRUB_FINISHED == (
        "1 0,12 * * * "
        "/scigroup/mcwrapper/gluex_MCwrapper/Utilities/scrub_finished_projects.sh"
    )
    result = run_legacy_shell(
        LegacyShellRun(
            entry_point=SCRUBBER,
            path_mappings={
                "/work/osgpool/halld/to_be_scrubbed/": "mapped/markers/",
                "/work/osgpool/halld/REQUESTEDMC_OUTPUT/": "mapped/output/",
            },
            files={
                "mapped/markers/project-42.done": "",
                "mapped/output/prefix-project-42/.keep": "fixture",
            },
            commands={
                "basename": FakeCommandResult(stdout="project-42.done\n"),
                "ls": FakeCommandResult(stdout_arg=-1),
                "rm": FakeCommandResult(),
            },
        )
    )

    assert result.exit_status == 0
    assert result.stderr == ""
    assert [command["argv"] for command in result.commands] == [
        ["basename", "<WORKDIR>/mapped/markers/project-42.done"],
        ["ls", "-d", "<WORKDIR>/mapped/output/prefix-project-42"],
        ["rm", "-rf", "<WORKDIR>/mapped/output/prefix-project-42"],
        ["rm", "<WORKDIR>/mapped/markers/project-42.done"],
    ]
    assert all(not path.startswith("/") for path in result.files)
