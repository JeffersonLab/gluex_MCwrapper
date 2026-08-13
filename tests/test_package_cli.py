import json
import runpy
import sys

import mcwrapper
import pytest
from mcwrapper.cli import build_parser, main
from mcwrapper.contracts import (
    ACTION_PLAN_SCHEMA_VERSION,
    ActionPlan,
    ExecutionPolicy,
    ExitCode,
    MutationRefusedError,
    PlannedAction,
)


def test_package_exposes_initial_version() -> None:
    assert mcwrapper.__version__ == "0.1.0"


def test_cli_help_is_available(capsys) -> None:
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("argparse help did not exit")

    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.startswith("usage: mcwrapper")


def test_cli_defaults_to_read_only_dry_run() -> None:
    arguments = build_parser().parse_args([])
    policy = ExecutionPolicy(
        profile=arguments.profile,
        execute=arguments.execute,
    )

    assert arguments.format == "text"
    assert policy.profile == "read-only"
    assert policy.dry_run is True


def test_cli_exit_codes_are_stable() -> None:
    assert {name: member.value for name, member in ExitCode.__members__.items()} == {
        "SUCCESS": 0,
        "USAGE": 2,
        "SAFETY_REFUSAL": 3,
        "INVALID_CONFIGURATION": 4,
        "EXTERNAL_FAILURE": 5,
        "INTERNAL_ERROR": 70,
    }


def test_mutation_requires_execute_and_capable_profile() -> None:
    with pytest.raises(MutationRefusedError, match="pass --execute"):
        ExecutionPolicy(profile="production").require_mutation()

    with pytest.raises(MutationRefusedError, match="mutation-capable profile"):
        ExecutionPolicy(profile="read-only", execute=True).require_mutation()

    ExecutionPolicy(profile="development", execute=True).require_mutation()
    ExecutionPolicy(profile="production", execute=True).require_mutation()


def test_execute_with_default_profile_is_rejected_as_json(capsys) -> None:
    status = main(["--format", "json", "--execute"])

    output = capsys.readouterr()
    assert status == ExitCode.SAFETY_REFUSAL
    assert output.out == ""
    assert json.loads(output.err) == {
        "error": {
            "code": "mutation_not_authorized",
            "message": (
                "mutation refused: --execute also requires an explicit "
                "mutation-capable profile"
            ),
        }
    }


def test_action_plan_has_stable_versioned_json_shape() -> None:
    plan = ActionPlan(
        command="job plan",
        profile="read-only",
        dry_run=True,
        actions=[
            PlannedAction(
                kind="write_file",
                target="job.conf",
                description="Render the payload configuration",
                mutating=True,
                parameters={"mode": "create"},
            )
        ],
    )

    assert plan.to_dict() == {
        "schema_version": ACTION_PLAN_SCHEMA_VERSION,
        "command": "job plan",
        "profile": "read-only",
        "dry_run": True,
        "actions": [
            {
                "kind": "write_file",
                "target": "job.conf",
                "description": "Render the payload configuration",
                "mutating": True,
                "parameters": {"mode": "create"},
            }
        ],
    }


def test_module_entry_point_help_is_available(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["mcwrapper", "--help"])

    with pytest.raises(SystemExit, match="0"):
        runpy.run_module("mcwrapper", run_name="__main__")

    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.startswith("usage: mcwrapper")


def test_module_entry_point_propagates_safety_exit(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["mcwrapper", "--execute"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("mcwrapper", run_name="__main__")

    assert exc_info.value.code == ExitCode.SAFETY_REFUSAL
    output = capsys.readouterr()
    assert output.out == ""
    assert "mutation refused" in output.err
