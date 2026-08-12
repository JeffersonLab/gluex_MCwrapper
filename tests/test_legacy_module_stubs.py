import json
import subprocess
import sys
import textwrap

import pytest

from tests.fakes.effects import EffectRecorder, UnexpectedEffectError
from tests.fakes.legacy_modules import install_legacy_module_stubs


_isolated_popen = subprocess.Popen


def test_mysql_stub_records_results_transactions_and_connection_lifetime():
    recorder = EffectRecorder()
    modules = install_legacy_module_stubs(
        recorder,
        mysql_results={
            ("SELECT value FROM fixture WHERE id=%s", (7,)): [
                {"value": "configured"}
            ]
        },
    )

    connection = modules["MySQLdb"].connect(host="fixture-db", db="test")
    cursor = connection.cursor(modules["MySQLdb"].cursors.DictCursor)
    assert cursor.execute("SELECT value FROM fixture WHERE id=%s", [7]) == 1
    assert cursor.fetchone() == {"value": "configured"}
    assert cursor.fetchone() is None
    connection.commit()
    connection.rollback()
    cursor.close()
    connection.close()

    assert [call.operation for call in recorder.calls] == [
        "connect",
        "cursor",
        "execute",
        "fetchone",
        "fetchone",
        "commit",
        "rollback",
        "cursor_close",
        "connection_close",
    ]
    with pytest.raises(UnexpectedEffectError, match="closed connection"):
        connection.commit()


def test_scientific_stubs_return_only_configured_results_and_record_access():
    recorder = EffectRecorder()
    rcdb_key = ("@approved", 100, 101, ("event_count",), True)
    ccdb_key = ("/test/table", 100, "default", "now")
    modules = install_legacy_module_stubs(
        recorder,
        rcdb_results={rcdb_key: [(100, 2500)]},
        ccdb_assignments={ccdb_key: [["configured"]]},
        hddm_inputs={("s", "input.hddm"): ["record-1", "record-2"]},
    )

    rcdb = modules["rcdb"].RCDBProvider("sqlite:///fixture")
    assert rcdb.select_runs("@approved", 100, 101).get_values(
        ["event_count"], True
    ) == ((100, 2500),)

    ccdb = modules["ccdb"].AlchemyProvider()
    ccdb.connect("sqlite:///fixture")
    assignment = ccdb.get_assignment("/test/table", 100, "default", "now")
    assert assignment.constant_set.data_table == [["configured"]]

    hddm = modules["hddm_s"]
    output = hddm.ostream("output.hddm")
    for entry in hddm.istream("input.hddm"):
        output.write(entry)
    assert output.entries == ["record-1", "record-2"]

    assert {call.boundary for call in recorder.calls} == {"rcdb", "ccdb", "hddm"}
    with pytest.raises(UnexpectedEffectError, match="unconfigured HDDM"):
        hddm.istream("production.hddm")


def test_representative_legacy_modules_load_and_run_in_isolated_subprocess():
    child_code = textwrap.dedent(
        """
        import json
        from tests.fakes.effects import EffectRecorder
        from tests.fakes.legacy_modules import install_legacy_module_stubs

        recorder = EffectRecorder()
        modules = install_legacy_module_stubs(
            recorder,
            mysql_results={("SELECT fixture", None): [(1,)]},
            rcdb_results={
                ("@approved", 100, 100, ("event_count",), True): [(100, 25)]
            },
            ccdb_assignments={
                ("/fixture", 100, "default", "now"): [["value"]]
            },
            hddm_inputs={("s", "one.hddm"): ["event"]},
        )

        import pwd
        pwd.getpwuid = lambda uid: ("mcwrap",)

        import Utilities.MCDrone
        import Utilities.merge_hddm as merge_hddm
        import Utilities.rcdb_wrapper
        import gluex_MC

        connection = modules["MySQLdb"].connect(database="fixture")
        cursor = connection.cursor()
        cursor.execute("SELECT fixture")
        cursor.fetchall()
        connection.commit()
        connection.rollback()
        cursor.close()
        connection.close()

        runs = modules["rcdb"].RCDBProvider("fixture").select_runs(
            "@approved", 100, 100
        ).get_values(["event_count"], True)
        provider = gluex_MC.LoadCCDB()
        provider.get_assignment("/fixture", 100, "default", "now")
        merge_hddm.merge(["one.hddm"], "merged.hddm")

        print(json.dumps({
            "runs": runs,
            "boundaries": sorted(set(call.boundary for call in recorder.calls)),
            "mysql_operations": [
                call.operation for call in recorder.calls if call.boundary == "mysql"
            ],
        }, sort_keys=True))
        """
    )

    process = _isolated_popen(
        [sys.executable, "-B", "-c", child_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = process.communicate()

    assert process.returncode == 0, stderr
    summary = json.loads(stdout.splitlines()[-1])
    assert summary["boundaries"] == ["ccdb", "hddm", "mysql", "rcdb"]
    assert summary["runs"] == [[100, 25]]
    assert {"execute", "fetchall", "commit", "rollback", "connection_close"} <= set(
        summary["mysql_operations"]
    )
