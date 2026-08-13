from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import db_fixture_inventory


def _defaults_file(tmp_path: Path) -> Path:
    path = tmp_path / "mysql.cnf"
    path.write_text("[client]\nuser=fixture\npassword=highly-secret\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def test_inventory_uses_selects_only_and_counts_candidate_states(monkeypatch, tmp_path):
    defaults = _defaults_file(tmp_path)
    queries = []
    responses = iter(
        [
            "Project\t8\nAttempts\t21\n",
            "Attempts\tProject_ID\tProject\tID\n",
            (
                "Attempts\tID\tint\tNO\n"
                "Attempts\tStatus\tvarchar\tYES\n"
                "Attempts\tCompleted_Time\tdatetime\tYES\n"
                "Project\tID\tint\tNO\n"
                "Project\tTested\tint\tNO\n"
                "Project\tIs_Dispatched\tdouble\tNO\n"
                "Project\tEmail\tvarchar\tYES\n"
            ),
            "<NULL>\t1\n4\t20\n",
            "0\t2\n1\t6\n",
            "0\t3\n1\t5\n",
        ]
    )
    monkeypatch.setattr(db_fixture_inventory.shutil, "which", lambda name: "/usr/bin/mysql")

    def fake_run(argv, **kwargs):
        query = argv[-1]
        queries.append(query)
        return SimpleNamespace(returncode=0, stdout=next(responses), stderr="")

    monkeypatch.setattr(db_fixture_inventory.subprocess, "run", fake_run)
    payload = db_fixture_inventory.build_inventory(defaults, "mcwrapper")

    assert payload["state_counts"] == {
        "Attempts.Status": {"<NULL>": 1, "4": 20},
        "Project.Is_Dispatched": {"0": 3, "1": 5},
        "Project.Tested": {"0": 2, "1": 6},
    }
    assert "Attempts.Completed_Time" not in payload["state_counts"]
    assert payload["relationships"] == [
        {
            "table": "Attempts",
            "column": "Project_ID",
            "referenced_table": "Project",
            "referenced_column": "ID",
        }
    ]
    assert all(query.lstrip().upper().startswith("SELECT") for query in queries)
    assert not any(
        token in " ".join(queries).upper()
        for token in ("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "DROP ")
    )
    assert "highly-secret" not in db_fixture_inventory.render_json(payload)


def test_query_failure_does_not_expose_client_stderr(monkeypatch, tmp_path):
    defaults = _defaults_file(tmp_path)
    monkeypatch.setattr(db_fixture_inventory.shutil, "which", lambda name: "/usr/bin/mysql")
    monkeypatch.setattr(
        db_fixture_inventory.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="Access denied for password highly-secret",
        ),
    )

    with pytest.raises(RuntimeError) as caught:
        db_fixture_inventory.mysql_query(defaults, "mcwrapper", "SELECT 1")

    assert "highly-secret" not in str(caught.value)


@pytest.mark.parametrize("identifier", ["db-name", "name; DROP TABLE Project", "`db`"]) 
def test_database_identifier_is_rejected_before_execution(identifier):
    with pytest.raises(ValueError, match="unsupported"):
        db_fixture_inventory.validate_identifier(identifier, "database name")
