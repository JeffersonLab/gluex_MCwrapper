from pathlib import Path

from tests.legacy_subprocess import FakeCommandResult, LegacyRun, run_legacy


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_rcdb_wrapper_is_characterized_deterministically():
    run = LegacyRun(
        entry_point=REPOSITORY_ROOT / "Utilities" / "rcdb_wrapper.py",
        argv=("@is_production", "12000", "12001"),
        environment={"RCDB_CONNECTION": "sqlite:///fixture"},
        rcdb_results=(
            {
                "query": "@is_production",
                "minimum_run": 12000,
                "maximum_run": 12001,
                "fields": ["event_count", "polarimeter_converter"],
                "insert_run_number": True,
                "rows": [[12000, 250000, "diamond"]],
            },
        ),
    )

    first = run_legacy(run)
    second = run_legacy(run)

    assert first == second
    assert first.exit_status == 0
    assert first.stdout == '[[12000, 250000, "diamond"]]\n'
    assert first.stderr == ""
    assert first.commands == []
    assert first.sql == []
    assert first.messages == []
    assert first.files == {}
    assert [(effect["boundary"], effect["operation"]) for effect in first.effects] == [
        ("rcdb", "connect"),
        ("rcdb", "select_runs"),
        ("rcdb", "get_values"),
    ]


def test_harness_captures_files_sql_commands_and_messages():
    result = run_legacy(
        LegacyRun(
            entry_point=REPOSITORY_ROOT / "tests" / "fixtures" / "harness_probe.py",
            commands={
                "fixture-command": FakeCommandResult(stdout="command output\n")
            },
            mysql_results=(
                {
                    "query": "UPDATE fixture SET characterized=%s",
                    "params": [True],
                    "rows": [],
                },
            ),
        )
    )

    assert result.exit_status == 0
    assert result.stdout == "probe complete\n"
    assert result.files == {"artifact.txt": "command output\n"}
    assert result.commands == [{"argv": ["fixture-command", "argument"]}]
    assert [event["operation"] for event in result.sql] == [
        "connect",
        "cursor",
        "execute",
        "commit",
        "cursor_close",
        "connection_close",
    ]
    assert [event["operation"] for event in result.messages] == [
        "connect",
        "sendmail",
        "quit",
    ]
