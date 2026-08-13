import os

import pytest

from tools.fixture_archive import TABLE_ORDER
from tools.fixture_archive import write_archive
from tools.mariadb_fixture_test import run_mariadb_archive
from tools.mariadb_fixture_test import sql_literal


pytestmark = pytest.mark.integration


SCHEMA = """
CREATE TABLE `Users` (`ID` INT PRIMARY KEY, `name` VARCHAR(64));
CREATE TABLE `Project` (
  `ID` INT PRIMARY KEY, `user_id` INT, `Email` VARCHAR(128),
  `OutputLocation` VARCHAR(255),
  CONSTRAINT `project_user` FOREIGN KEY (`user_id`) REFERENCES `Users` (`ID`)
);
CREATE TABLE `Jobs` (
  `ID` INT PRIMARY KEY, `Project_ID` INT,
  CONSTRAINT `job_project` FOREIGN KEY (`Project_ID`) REFERENCES `Project` (`ID`)
);
CREATE TABLE `Attempts` (
  `ID` INT PRIMARY KEY, `Job_ID` INT, `SubmitHost` VARCHAR(128), `Status` VARCHAR(32),
  CONSTRAINT `attempt_job` FOREIGN KEY (`Job_ID`) REFERENCES `Jobs` (`ID`)
);
CREATE TABLE `Generator_perfiles` (`ID` INT PRIMARY KEY, `GenName` VARCHAR(64), `PerFile` INT);
""".strip() + "\n"


def _archive(path):
    tables = {
        "Users": [{"ID": 1, "name": "user-1"}],
        "Project": [{"ID": 1, "user_id": 1, "Email": "user-1@example.invalid", "OutputLocation": "/fixture/project/output/1"}],
        "Jobs": [{"ID": 1, "Project_ID": 1}],
        "Attempts": [{"ID": 1, "Job_ID": 1, "SubmitHost": "host-1.example.invalid", "Status": "4"}],
        "Generator_perfiles": [{"ID": 1, "GenName": "gen_amp", "PerFile": 1000}],
    }
    write_archive(path, SCHEMA, tables, {"completed": [1]})


def test_sql_literal_never_interpolates_text_directly():
    literal = sql_literal("Robert'); DROP TABLE Users;--")
    assert literal.startswith("CONVERT(0x")
    assert "DROP TABLE" not in literal


@pytest.mark.skipif(
    os.environ.get("MCWRAPPER_RUN_MARIADB_TESTS") != "1",
    reason="set MCWRAPPER_RUN_MARIADB_TESTS=1 to use disposable Docker MariaDB",
)
def test_fixture_loads_into_disposable_mariadb(tmp_path):
    archive = tmp_path / "fixture.tar.gz"
    _archive(archive)

    counts = run_mariadb_archive(archive)

    assert counts == {table: 1 for table in TABLE_ORDER}
