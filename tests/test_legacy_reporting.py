from pathlib import Path

from tests.legacy_subprocess import FakeCommandResult
from tests.legacy_subprocess import LegacyRun
from tests.legacy_subprocess import run_legacy


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
UTILITIES = REPOSITORY_ROOT / "Utilities"


def _sql(query, rows=()):
    return {"query": query, "rows": list(rows)}


def test_project_analysis_records_queries_and_plot_output_intentions():
    attempt_count = (
        "SELECT COUNT(*) as AttemptsCount from Attempts where Job_ID in "
        "(SELECT ID from Jobs where Project_ID IN (SELECT ID FROM Project where "
        "ID=7)) GROUP BY Job_ID;"
    )
    start_count = (
        "SELECT NumStarts as Starts from Attempts where NumStarts is NOT NULL && "
        "Job_ID in (SELECT ID from Jobs where Project_ID IN (SELECT ID FROM "
        "Project where ID=7)) GROUP BY Job_ID;"
    )
    failure_count = (
        "SELECT ProgramFailed as pf,COUNT(*) as AttemptsCount from Attempts where "
        "ProgramFailed is not NULL && Job_ID in (SELECT ID from Jobs where "
        "Project_ID IN (SELECT ID FROM Project where ID>0 && ID=7)) GROUP BY "
        "ProgramFailed;"
    )
    null_failure_count = (
        "SELECT ExitCode as pf,COUNT(*) as AttemptsCount from Attempts where "
        "ProgramFailed is NULL && Job_ID in (SELECT ID from Jobs where Project_ID "
        "IN (SELECT ID FROM Project where ID>0 && ID=7)) GROUP BY ExitCode;"
    )
    result = run_legacy(
        LegacyRun(
            entry_point=UTILITIES / "MCAnalyzeProject.py",
            argv=("-P", "7", "-o", "reports/"),
            intercepted_commands={"mkdir": FakeCommandResult()},
            mysql_results=(
                _sql(attempt_count),
                _sql(start_count),
                _sql(
                    failure_count,
                    ({"pf": "fixture failure", "AttemptsCount": 1},),
                ),
                _sql(
                    null_failure_count,
                    ({"pf": 0, "AttemptsCount": 2},),
                ),
            ),
        )
    )

    assert result.exit_status == 0
    assert result.stderr == ""
    assert result.stdout.rstrip().splitlines() == [
        "Analyzing project # 7",
        "Getting the distributions of attempts for project 7",
        attempt_count,
        "Obtained 0 Entries",
        "[0]",
        "Can't compute Average as it is nan",
        "Getting the distributions of attempts for project 7",
        start_count,
        "Obtained 0 Entries",
        "[0]",
        "Getting the Failure Pie for project  0",
        failure_count,
        "Obtained 1 Entries",
        "df created",
        "({'AttemptsCount': 2, 'pf': 'Successfully completed'},)",
        "df2 created",
        "concat completed",
    ]
    assert [effect["args"][1] for effect in result.sql if effect["operation"] == "execute"] == [
        attempt_count,
        start_count,
        failure_count,
        null_failure_count,
    ]
    assert [
        (
            effect["args"][0],
            effect["kwargs"]["filename"],
            effect["kwargs"]["image_filename"],
        )
        for effect in result.effects
        if effect["boundary"] == "plot" and effect["operation"] == "write_plot"
    ] == [
        (
            "histogram",
            "reports/MCAnalyze_out/CountDistribution_7.html",
            "reports/MCAnalyze_out/CountDistribution_7",
        ),
        (
            "histogram",
            "reports/MCAnalyze_out/StartsDistribution_7.html",
            "reports/MCAnalyze_out/StartsDistribution_7",
        ),
        (
            "pie",
            "reports/MCAnalyze_out/failurePie_Proj7.html",
            "reports/MCAnalyze_out/failurePie_Proj7",
        ),
    ]
    assert [effect["args"] for effect in result.effects if effect["boundary"] == "process"] == [
        [["mkdir", "-p", "reports/MCAnalyze_out/"]]
    ]
    assert result.files == {}


def test_fixed_statistics_records_queries_and_interactive_plot_intentions():
    users_query = (
        "SELECT UName, NumEvents From Project WHERE Submit_Time>DATE('2024-01-01') "
        "AND Notified=1 ORDER BY Submit_Time;"
    )
    locations_query = (
        "SELECT RunningLocation,Start_Time,WallTime,CPUTime,RAMUsed,ExitCode FROM "
        "Attempts WHERE Start_Time>DATE('2024-01-01') ORDER BY Start_Time;"
    )
    result = run_legacy(
        LegacyRun(
            entry_point=UTILITIES / "MCStats.py",
            mysql_results=(
                _sql(users_query, ({"UName": "fixture", "NumEvents": 10},)),
                _sql(locations_query),
            ),
        )
    )

    assert result.exit_status == 0
    assert result.stderr == ""
    assert result.stdout.rstrip().splitlines() == [
        "{'fixture': (1, 10)}",
        "         NumProj  NumEvents",
        "fixture        1         10",
        "1 1.0 10",
        "JLab 0",
        "UConn 0",
        "FSU 0",
        "Glasgow 0",
        "IU 0",
        "ComputeCanada 0",
        "Other 0",
    ]
    assert [effect["args"][1] for effect in result.sql if effect["operation"] == "execute"] == [
        users_query,
        locations_query,
    ]
    assert [
        effect["operation"]
        for effect in result.effects
        if effect["boundary"] == "plot"
    ] == [
        "axes_pie",
        "axes_pie",
        "axes_pie",
        "show",
        "axes_pie",
        "title",
        "show",
        "xlabel",
        "ylabel",
        "title",
        "legend",
        "show",
    ]
    assert result.sql[-1]["operation"] == "connection_close"
    assert result.files == {}


def test_yearly_statistics_preserves_current_no_query_behavior():
    result = run_legacy(
        LegacyRun(
            entry_point=UTILITIES / "MCstats_yearly.py",
            argv=("2026",),
        )
    )

    assert result.exit_status == 0
    assert result.stderr == ""
    assert result.stdout == "begin\n"
    assert [effect["operation"] for effect in result.sql] == ["connect", "cursor"]
    assert not [effect for effect in result.sql if effect["operation"] == "execute"]
    assert not [effect for effect in result.effects if effect["boundary"] == "plot"]
    assert result.files == {}
