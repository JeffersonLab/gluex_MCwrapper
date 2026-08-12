import json
from pathlib import Path

import pytest

from tests.legacy_subprocess import FakeCommandResult, LegacyRun, run_legacy


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GOLDENS = json.loads(
    (REPOSITORY_ROOT / "tests" / "golden" / "legacy_command_generation.json").read_text(
        encoding="utf-8"
    )
)
BASE_CONFIG = """\
DATA_OUTPUT_BASE_DIR=/output
ENVIRONMENT_FILE=recon.xml
SIM_ENVIRONMENT_FILE=sim.xml
ANA_ENVIRONMENT_FILE=ana.xml
GENERATOR_CONFIG=gen.cfg
BKG=BEAMPHOTONS:0
VARIATION=config_version calibtime=config_time
WORKFLOW_NAME=fixture_workflow
NCORES=4
RAM=8GB
TIMELIMIT=30minutes
CONDOR_MAGIC=+FixtureFlag = \"yes\"
"""


def _version_sql(filename):
    return {
        "query": (
            "select OSName from versionSet inner join OSVersions on "
            "versionSet.OS_ID=OSVersions.ID where versionSet.filename='{}'"
        ).format(filename),
        "rows": [["Alma9"]],
    }


def _run(mode, *, config=BASE_CONFIG, argv=(), bare_osg_auxiliary_paths=False):
    intercepted = {
        "MakeMC.csh": FakeCommandResult(),
        "MakeMC.sh": FakeCommandResult(),
        "mkdir": FakeCommandResult(),
        "rm": FakeCommandResult(),
        "condor_submit": FakeCommandResult(
            stdout="Submitting job(s).\n1 job(s) submitted to cluster 42.\n"
        ),
        "sbatch": FakeCommandResult(stdout="Submitted batch job 42\n"),
        "swif": FakeCommandResult(stdout="job_id=42\n"),
        "swif2": FakeCommandResult(stdout="job_id=42\n"),
    }
    mode_config = config + "BATCH_SYSTEM={}\n".format(mode)
    version_files = ("recon.xml", "sim.xml", "ana.xml")
    if mode == "OSG" and not bare_osg_auxiliary_paths:
        mode_config = mode_config.replace(
            "SIM_ENVIRONMENT_FILE=sim.xml",
            "SIM_ENVIRONMENT_FILE=/fixtures/sim.xml",
        ).replace(
            "ANA_ENVIRONMENT_FILE=ana.xml",
            "ANA_ENVIRONMENT_FILE=/fixtures/ana.xml",
        )
        version_files = ("recon.xml", "sim.xml", "ana.xml")
    return run_legacy(
        LegacyRun(
            entry_point=REPOSITORY_ROOT / "gluex_MC.py",
            argv=(
                "case.config",
                "1234",
                "10",
                "per_file=10",
                "base_file_number=3",
                "logdir=/logs",
            )
            + tuple(argv),
            environment={
                "MCWRAPPER_CENTRAL": "/central",
                "RCDB_CONNECTION": "sqlite:///fixture",
            },
            files={"case.config": mode_config},
            intercepted_commands=intercepted,
            mysql_results=tuple(
                _version_sql(filename)
                for filename in version_files
            ),
        )
    )


def _summary(result):
    generated_files = {
        name: content
        for name, content in result.files.items()
        if name != "case.config"
    }
    process_calls = []
    for effect in result.effects:
        if effect["boundary"] != "process":
            continue
        argv = list(effect["args"][0])
        payload_index = next(
            (
                index
                for index, value in enumerate(argv)
                if value in ("/central/MakeMC.csh", "/central/MakeMC.sh")
            ),
            None,
        )
        if payload_index is not None:
            argv = argv[: payload_index + 1] + ["<PAYLOAD>"]
        process_calls.append(
            {"argv": argv, "shell": effect["kwargs"].get("shell", False)}
        )
    sql_intentions = [
        effect["args"][1:]
        for effect in result.sql
        if effect["operation"] == "execute"
    ]
    command_line = next(
        (line for line in result.stdout.splitlines() if line.startswith("COMMAND PRINTOUT:")),
        None,
    )
    return {
        "exit_status": result.exit_status,
        "stderr": result.stderr,
        "terminal_line": result.stdout.rstrip().splitlines()[-1],
        "payload_command": command_line,
        "generated_files": generated_files,
        "commands": process_calls,
        "sql_intentions": sql_intentions,
    }


@pytest.mark.parametrize("mode", ["NULL", "CONDOR", "OSG", "SWIF", "SWIF2", "SLURM"])
def test_representative_command_generation_matches_legacy_golden(mode):
    result = _run(mode, argv=() if mode == "NULL" else ("batch=1",))
    summary = _summary(result)

    assert summary.pop("sql_intentions") == GOLDENS["sql_intentions"]
    assert summary == GOLDENS["normal"][mode]


@pytest.mark.parametrize(
    ("name", "mode", "config", "expected_lines"),
    [
        (
            "unsafe_workflow",
            "CONDOR",
            BASE_CONFIG.replace("fixture_workflow", "fixture;workflow"),
            ["Nice try.....you cannot use ; or & in the name"],
        ),
        (
            "generator_config_with_spaces",
            "NULL",
            BASE_CONFIG.replace("gen.cfg", "gen config.cfg"),
            ["gen config.cfg is an invalid GENERATOR_CONFIG parameter."],
        ),
        (
            "swif_ram_per_thread",
            "SWIF",
            BASE_CONFIG.replace("NCORES=4", "NCORES=1").replace("RAM=8GB", "RAM=10GB"),
            [
                "SciComp has a limit on RAM requested per thread, as RAM is the limiting factor.",
                "Please either increase NCORES or decrease RAM requested and try again.",
            ],
        ),
    ],
)
def test_important_validation_failures_are_characterized(
    name, mode, config, expected_lines
):
    extra_argv = ("batch=1",) if mode != "NULL" else ()
    result = _run(mode, config=config, argv=extra_argv)

    assert result.exit_status == GOLDENS["validation"][name]["exit_status"]
    for line in expected_lines:
        assert any(line in actual for actual in result.stdout.splitlines())
    assert [
        effect for effect in result.effects if effect["boundary"] == "process"
    ] == GOLDENS["validation"][name]["commands"]


def test_osg_accepts_bare_auxiliary_environment_paths():
    result = _run(
        "OSG",
        argv=("batch=1",),
        bare_osg_auxiliary_paths=True,
    )
    summary = _summary(result)
    golden = GOLDENS["validation"]["osg_bare_auxiliary_paths"]
    submit_file = summary["generated_files"]["MCOSG_0.submit"]

    assert summary.pop("sql_intentions") == GOLDENS["sql_intentions"]
    assert summary["exit_status"] == golden["exit_status"]
    assert summary["stderr"] == ""
    assert summary["terminal_line"] == "ending gluex_MC.py"
    assert summary["commands"] == GOLDENS["normal"]["OSG"]["commands"]
    assert all(fragment in submit_file for fragment in golden["submit_contains"])
