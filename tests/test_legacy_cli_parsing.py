import json
from pathlib import Path

import pytest

from tests.legacy_subprocess import LegacyRun, run_legacy


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GOLDENS = json.loads(
    (REPOSITORY_ROOT / "tests" / "golden" / "legacy_cli_parsing.json").read_text(
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
VARIATION=first_config_version calibtime=first_config_time
VARIATION=config_version calibtime=config_time
"""


def _effect_names(result):
    return [
        "{}.{}".format(effect["boundary"], effect["operation"])
        for effect in result.effects
    ]


def _stderr_last_line(result):
    return result.stderr.rstrip().splitlines()[-1]


def _line_starting_with(result, prefix):
    return next(line for line in result.stdout.splitlines() if line.startswith(prefix))


def _version_sql(filename):
    return {
        "query": (
            "select OSName from versionSet inner join OSVersions on "
            "versionSet.OS_ID=OSVersions.ID where versionSet.filename='{}'"
        ).format(filename),
        "rows": [["Alma9"]],
    }


def _configured_run(argv, *, rcdb_results=()):
    return run_legacy(
        LegacyRun(
            entry_point=REPOSITORY_ROOT / "gluex_MC.py",
            argv=argv,
            environment={
                "MCWRAPPER_CENTRAL": "/central",
                "RCDB_CONNECTION": "sqlite:///fixture",
            },
            files={"case.config": BASE_CONFIG},
            mysql_results=tuple(
                _version_sql(filename)
                for filename in ("recon.xml", "sim.xml", "ana.xml")
            ),
            rcdb_results=rcdb_results,
        )
    )


@pytest.mark.parametrize("argv", [(), ("--help",), ("unused.config", "run=100", "20")])
def test_help_and_missing_arguments_match_legacy_golden(argv):
    result = run_legacy(
        LegacyRun(entry_point=REPOSITORY_ROOT / "gluex_MC.py", argv=argv)
    )
    golden = GOLDENS["help"]

    assert result.exit_status == golden["exit_status"]
    assert result.stderr == ""
    assert result.stdout.splitlines()[0] == golden["first_line"]
    assert result.stdout.splitlines()[-1] == golden["last_line"]
    assert len(result.stdout.splitlines()) == golden["line_count"]
    assert _effect_names(result) == GOLDENS["import_effects"]


def test_malformed_event_count_matches_legacy_golden():
    result = run_legacy(
        LegacyRun(
            entry_point=REPOSITORY_ROOT / "gluex_MC.py",
            argv=("unused.config", "100", "abc"),
        )
    )
    golden = GOLDENS["malformed_event_count"]

    assert result.exit_status == golden["exit_status"]
    assert result.stdout == golden["stdout"]
    assert _stderr_last_line(result) == golden["stderr_last_line"]
    assert _effect_names(result) == GOLDENS["import_effects"]


def test_repeated_config_values_use_the_last_value():
    result = _configured_run(
        ("case.config", "001234", "1", "per_file=1", "base_file_number=7")
    )
    golden = GOLDENS["config_precedence"]

    assert result.exit_status == golden["exit_status"]
    assert _line_starting_with(result, "COMMAND PRINTOUT:") == golden["command_line"]
    assert _stderr_last_line(result) == golden["stderr_last_line"]


def test_key_value_overrides_win_and_unknown_keys_only_warn():
    result = _configured_run(
        (
            "case.config",
            "001234",
            "1",
            "variation=cli_version",
            "calibtime=cli_time",
            "per_file=1",
            "base_file_number=7",
            "unknown=value",
        )
    )
    golden = GOLDENS["key_value_overrides"]

    assert result.exit_status == golden["exit_status"]
    assert golden["unknown_option"] in result.stdout.splitlines()
    assert _line_starting_with(result, "COMMAND PRINTOUT:") == golden["command_line"]


def test_malformed_numeric_override_matches_legacy_golden():
    result = _configured_run(("case.config", "1234", "1", "per_file=nope"))
    golden = GOLDENS["malformed_override"]

    assert result.exit_status == golden["exit_status"]
    assert _stderr_last_line(result) == golden["stderr_last_line"]
    assert _effect_names(result) == GOLDENS["import_effects"]


def test_run_range_strips_endpoint_zeroes_before_rcdb_selection():
    result = _configured_run(
        ("case.config", "001234-001235", "0"),
        rcdb_results=(
            {
                "query": "@is_production and @status_approved",
                "minimum_run": "1234",
                "maximum_run": "1235",
                "fields": ["event_count", "polarimeter_converter"],
                "insert_run_number": True,
                "rows": [[1234, 0, "diamond"]],
            },
        ),
    )
    golden = GOLDENS["run_range"]
    select_runs = next(
        effect
        for effect in result.effects
        if effect["boundary"] == "rcdb" and effect["operation"] == "select_runs"
    )

    assert result.exit_status == golden["exit_status"]
    assert golden["rcdb_range_line"] in result.stdout.splitlines()
    assert select_runs["args"] == golden["select_runs_args"]
    assert result.stdout.splitlines()[-1] == golden["terminal_line"]
    assert result.stderr == ""
