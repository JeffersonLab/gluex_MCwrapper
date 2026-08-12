from pathlib import Path

import pytest

from tests.legacy_subprocess import FakeCommandResult, LegacyRun, run_legacy


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    (
        "script_name",
        "process_count",
        "expected_connects",
        "expected_closes",
        "stdout_lines",
        "syntax_warning",
    ),
    [
        ("MCDispatcher.py", 2, 1, 1, ["num running 2"], False),
        ("MCSubmitter.py", 3, 1, 1, ["b'3\\n'"], False),
        ("MCObserver.py", 2, 1, 1, ["2"], False),
        ("MCOverlord.py", 2, 2, 1, ["2"], True),
        (
            "MCDrone.py",
            2,
            1,
            0,
            ["2", "number of running processes 2"],
            False,
        ),
    ],
)
def test_cron_controller_duplicate_process_smoke_characterization(
    script_name,
    process_count,
    expected_connects,
    expected_closes,
    stdout_lines,
    syntax_warning,
):
    process_probe = (
        "echo `ps all -u mcwrap | grep {} | grep -v grep | wc -l`".format(
            script_name
        )
    )
    result = run_legacy(
        LegacyRun(
            entry_point=REPOSITORY_ROOT / "Utilities" / script_name,
            username="mcwrap",
            hostname="fixture-host.jlab.org",
            intercepted_commands={
                process_probe: FakeCommandResult(stdout="{}\n".format(process_count))
            },
        )
    )

    assert result.exit_status == 0
    if syntax_warning:
        if result.stderr:
            assert 'SyntaxWarning: "\\(" is an invalid escape sequence' in result.stderr
            assert 'SyntaxWarning: "\\)" is an invalid escape sequence' in result.stderr
    else:
        assert result.stderr == ""
    assert result.stdout.rstrip().splitlines() == stdout_lines
    assert [effect["operation"] for effect in result.commands] == []

    process_effects = [
        effect for effect in result.effects if effect["boundary"] == "process"
    ]
    assert process_effects == [
        {
            "boundary": "process",
            "operation": "run",
            "args": [[process_probe]],
            "kwargs": {"shell": True},
        }
    ]

    assert sum(
        effect["operation"] == "connect" for effect in result.sql
    ) == expected_connects
    assert sum(
        effect["operation"] == "connection_close" for effect in result.sql
    ) == expected_closes
    assert not result.messages
    assert result.files == {}
