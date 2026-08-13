from datetime import datetime

import pytest

from tools.export_test_fixtures import sanitize_rows
from tools.fixture_archive import FixtureValidationError
from tools.fixture_archive import TABLE_ORDER
from tools.fixture_archive import validate_archive
from tools.fixture_archive import write_archive


SCHEMA = "\n".join(
    "CREATE TABLE `{}` (`ID` INT PRIMARY KEY);".format(table) for table in TABLE_ORDER
)


def _tables():
    return {
        "Users": [{"ID": 1, "name": "user-1"}],
        "Project": [
            {
                "ID": 1,
                "user_id": 1,
                "Email": "user-1@example.invalid",
                "OutputLocation": "/fixture/project/outputlocation/1",
            }
        ],
        "Jobs": [{"ID": 1, "Project_ID": 1}],
        "Attempts": [
            {
                "ID": 1,
                "Job_ID": 1,
                "SubmitHost": "host-1.example.invalid",
                "Status": "4",
            }
        ],
        "Generator_perfiles": [{"ID": 1, "GenName": "gen_amp", "PerFile": 1000}],
    }


def test_valid_archive_round_trips_and_checks_hashes(tmp_path):
    archive = tmp_path / "fixture.tar.gz"
    write_archive(archive, SCHEMA, _tables(), {"completed": [1]})

    manifest = validate_archive(archive)

    assert manifest["selections"] == {"completed": [1]}
    assert manifest["tables"]["Attempts"]["rows"] == 1


@pytest.mark.parametrize(
    ("table", "column", "value", "message"),
    [
        ("Project", "Email", "person@jlab.org", "JLab hostname|real email"),
        ("Project", "OutputLocation", "/work/osgpool/halld/data", "production path"),
        ("Project", "Comments", "password=do-not-ship", "credential marker"),
    ],
)
def test_verifier_rejects_contaminated_archives(
    tmp_path, table, column, value, message
):
    tables = _tables()
    tables[table][0][column] = value
    archive = tmp_path / "contaminated.tar.gz"
    write_archive(archive, SCHEMA, tables, {})

    with pytest.raises(FixtureValidationError, match=message):
        validate_archive(archive)


def test_verifier_rejects_broken_foreign_keys(tmp_path):
    tables = _tables()
    tables["Attempts"][0]["Job_ID"] = 999
    archive = tmp_path / "broken.tar.gz"
    write_archive(archive, SCHEMA, tables, {})

    with pytest.raises(FixtureValidationError, match="broken foreign key"):
        validate_archive(archive)


def test_sanitizer_remaps_identifiers_and_sensitive_fields():
    source = {
        "Users": [{"ID": 90, "name": "Real Person"}],
        "Project": [
            {
                "ID": 800,
                "user_id": 90,
                "Submitter": "real-user",
                "Email": "person@jlab.org",
                "UName": "real-user",
                "UIp": "host.jlab.org",
                "OutputLocation": "/work/osgpool/halld/private",
                "Comments": "private note",
                "Submit_Time": datetime(2026, 8, 12, 1, 2, 3),
            }
        ],
        "Jobs": [{"ID": 7000, "Project_ID": 800}],
        "Attempts": [
            {
                "ID": 60000,
                "Job_ID": 7000,
                "SubmitHost": "ifarm.jlab.org",
                "BatchJobID": "secret-batch-id",
                "Status": "failed",
            }
        ],
        "Generator_perfiles": [],
    }

    clean, _maps = sanitize_rows(source)

    assert clean["Project"][0]["ID"] == 1
    assert clean["Project"][0]["user_id"] == 1
    assert clean["Jobs"][0]["Project_ID"] == 1
    assert clean["Attempts"][0]["Job_ID"] == 1
    assert clean["Project"][0]["Email"] == "user-1@example.invalid"
    assert clean["Project"][0]["Comments"].startswith("[redacted:")
    assert clean["Project"][0]["Submit_Time"] == "2000-01-01 00:00:00"
    assert clean["Attempts"][0]["Status"] == "failed"
    assert "jlab.org" not in repr(clean)
    assert "/work/" not in repr(clean)
