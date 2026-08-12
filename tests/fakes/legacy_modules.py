"""In-process stand-ins for legacy database and scientific modules.

The legacy scripts import these dependencies by their production names.  Tests call
``install_legacy_module_stubs`` before importing a script so no real client library
can connect to an external service.
"""

import sys
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from tests.fakes.effects import EffectRecorder, UnexpectedEffectError


SqlResultKey = Tuple[str, Optional[Tuple[Any, ...]]]
RcdbResultKey = Tuple[str, Any, Any, Tuple[str, ...], bool]
CcdbResultKey = Tuple[str, Any, Any, Any]


class FakeCursor:
    def __init__(
        self,
        recorder: EffectRecorder,
        results: Mapping[SqlResultKey, Sequence[Any]],
        connection_id: int,
    ) -> None:
        self._recorder = recorder
        self._results = results
        self._connection_id = connection_id
        self._current_rows: Optional[Tuple[Any, ...]] = None
        self._offset = 0
        self.closed = False
        self.rowcount = -1
        self.lastrowid = None

    def execute(self, query: str, params: Optional[Sequence[Any]] = None) -> int:
        self._ensure_open()
        normalized_params = None if params is None else tuple(params)
        self._recorder.record(
            "mysql", "execute", self._connection_id, query, normalized_params
        )
        key = (query, normalized_params)
        try:
            self._current_rows = tuple(self._results[key])
        except KeyError as error:
            raise UnexpectedEffectError(
                "unconfigured SQL query: {!r} params={!r}".format(
                    query, normalized_params
                )
            ) from error
        self._offset = 0
        self.rowcount = len(self._current_rows)
        return self.rowcount

    def fetchone(self) -> Any:
        self._ensure_result()
        self._recorder.record("mysql", "fetchone", self._connection_id)
        assert self._current_rows is not None
        if self._offset >= len(self._current_rows):
            return None
        row = self._current_rows[self._offset]
        self._offset += 1
        return row

    def fetchall(self) -> Tuple[Any, ...]:
        self._ensure_result()
        self._recorder.record("mysql", "fetchall", self._connection_id)
        assert self._current_rows is not None
        rows = self._current_rows[self._offset :]
        self._offset = len(self._current_rows)
        return rows

    def close(self) -> None:
        if not self.closed:
            self._recorder.record("mysql", "cursor_close", self._connection_id)
            self.closed = True

    def _ensure_open(self) -> None:
        if self.closed:
            raise UnexpectedEffectError("SQL operation on closed cursor")

    def _ensure_result(self) -> None:
        self._ensure_open()
        if self._current_rows is None:
            raise UnexpectedEffectError("SQL fetch before execute")


class FakeConnection:
    def __init__(
        self,
        recorder: EffectRecorder,
        results: Mapping[SqlResultKey, Sequence[Any]],
        connection_id: int,
    ) -> None:
        self._recorder = recorder
        self._results = results
        self.connection_id = connection_id
        self.closed = False

    def cursor(self, cursor_type: Any = None) -> FakeCursor:
        self._ensure_open()
        self._recorder.record(
            "mysql", "cursor", self.connection_id, cursor_type
        )
        return FakeCursor(self._recorder, self._results, self.connection_id)

    def commit(self) -> None:
        self._ensure_open()
        self._recorder.record("mysql", "commit", self.connection_id)

    def rollback(self) -> None:
        self._ensure_open()
        self._recorder.record("mysql", "rollback", self.connection_id)

    def close(self) -> None:
        if not self.closed:
            self._recorder.record("mysql", "connection_close", self.connection_id)
            self.closed = True

    def __enter__(self) -> "FakeConnection":
        self._ensure_open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()

    def _ensure_open(self) -> None:
        if self.closed:
            raise UnexpectedEffectError("SQL operation on closed connection")


class FakeRCDBSelection:
    def __init__(
        self,
        recorder: EffectRecorder,
        results: Mapping[RcdbResultKey, Sequence[Any]],
        query: str,
        minimum_run: Any,
        maximum_run: Any,
    ) -> None:
        self._recorder = recorder
        self._results = results
        self._query = query
        self._minimum_run = minimum_run
        self._maximum_run = maximum_run

    def get_values(
        self, fields: Sequence[str], insert_run_number: bool = False
    ) -> Tuple[Any, ...]:
        field_tuple = tuple(fields)
        self._recorder.record(
            "rcdb", "get_values", field_tuple, insert_run_number
        )
        key = (
            self._query,
            self._minimum_run,
            self._maximum_run,
            field_tuple,
            insert_run_number,
        )
        try:
            return tuple(self._results[key])
        except KeyError as error:
            raise UnexpectedEffectError(
                "unconfigured RCDB values request: {!r}".format(key)
            ) from error


class FakeRCDBProvider:
    def __init__(
        self,
        recorder: EffectRecorder,
        results: Mapping[RcdbResultKey, Sequence[Any]],
        connection_string: Optional[str],
    ) -> None:
        self._recorder = recorder
        self._results = results
        self._recorder.record("rcdb", "connect", connection_string)

    def select_runs(
        self, query: str, minimum_run: Any, maximum_run: Any
    ) -> FakeRCDBSelection:
        self._recorder.record(
            "rcdb", "select_runs", query, minimum_run, maximum_run
        )
        return FakeRCDBSelection(
            self._recorder, self._results, query, minimum_run, maximum_run
        )


class FakeCCDBProvider:
    def __init__(
        self,
        recorder: EffectRecorder,
        assignments: Mapping[CcdbResultKey, Sequence[Any]],
    ) -> None:
        self._recorder = recorder
        self._assignments = assignments
        self.authentication = SimpleNamespace(current_user_name=None)

    def connect(self, connection_string: str) -> None:
        self._recorder.record("ccdb", "connect", connection_string)

    def get_assignment(
        self, path: str, run: Any, variation: Any = None, calibration_time: Any = None
    ) -> Any:
        key = (path, run, variation, calibration_time)
        self._recorder.record("ccdb", "get_assignment", *key)
        try:
            table = self._assignments[key]
        except KeyError as error:
            raise UnexpectedEffectError(
                "unconfigured CCDB assignment: {!r}".format(key)
            ) from error
        return SimpleNamespace(
            constant_set=SimpleNamespace(data_table=table)
        )


class FakeHDDMOutput:
    def __init__(self, recorder: EffectRecorder, flavor: str, path: str) -> None:
        self._recorder = recorder
        self._flavor = flavor
        self.path = path
        self.compression = None
        self.entries = []

    def write(self, entry: Any) -> None:
        self._recorder.record("hddm", "write", self._flavor, self.path, entry)
        self.entries.append(entry)


def install_legacy_module_stubs(
    recorder: EffectRecorder,
    mysql_results: Optional[Mapping[SqlResultKey, Sequence[Any]]] = None,
    rcdb_results: Optional[Mapping[RcdbResultKey, Sequence[Any]]] = None,
    ccdb_assignments: Optional[Mapping[CcdbResultKey, Sequence[Any]]] = None,
    hddm_inputs: Optional[Mapping[Tuple[str, str], Iterable[Any]]] = None,
) -> Dict[str, ModuleType]:
    """Install configured stand-ins under the import names used by legacy code."""
    sql_results = dict(mysql_results or {})
    run_results = dict(rcdb_results or {})
    assignments = dict(ccdb_assignments or {})
    input_entries = {
        key: tuple(value) for key, value in (hddm_inputs or {}).items()
    }

    mysql = ModuleType("MySQLdb")
    mysql_cursors = ModuleType("MySQLdb.cursors")

    class DictCursor:
        pass

    mysql_cursors.DictCursor = DictCursor
    mysql.cursors = mysql_cursors
    connection_count = [0]

    def mysql_connect(*args: Any, **kwargs: Any) -> FakeConnection:
        connection_count[0] += 1
        connection_id = connection_count[0]
        recorder.record("mysql", "connect", connection_id, *args, **kwargs)
        return FakeConnection(recorder, sql_results, connection_id)

    mysql.connect = mysql_connect

    rcdb = ModuleType("rcdb")

    def rcdb_provider(connection_string: Optional[str] = None) -> FakeRCDBProvider:
        return FakeRCDBProvider(recorder, run_results, connection_string)

    rcdb.RCDBProvider = rcdb_provider

    ccdb = ModuleType("ccdb")
    ccdb.__path__ = []
    ccdb_path_utils = ModuleType("ccdb.path_utils")
    ccdb.path_utils = ccdb_path_utils
    ccdb.AlchemyProvider = lambda: FakeCCDBProvider(recorder, assignments)
    for class_name in ("Directory", "TypeTable", "Assignment", "ConstantSet"):
        setattr(ccdb, class_name, type(class_name, (), {}))

    modules = {
        "MySQLdb": mysql,
        "MySQLdb.cursors": mysql_cursors,
        "rcdb": rcdb,
        "ccdb": ccdb,
        "ccdb.path_utils": ccdb_path_utils,
    }

    for flavor in ("s", "r"):
        module_name = "hddm_{}".format(flavor)
        hddm = ModuleType(module_name)
        hddm.k_z_compression = "zlib"

        def istream(path: str, current_flavor: str = flavor) -> Tuple[Any, ...]:
            recorder.record("hddm", "istream", current_flavor, path)
            key = (current_flavor, path)
            try:
                return input_entries[key]
            except KeyError as error:
                raise UnexpectedEffectError(
                    "unconfigured HDDM input: {!r}".format(key)
                ) from error

        def ostream(path: str, current_flavor: str = flavor) -> FakeHDDMOutput:
            recorder.record("hddm", "ostream", current_flavor, path)
            return FakeHDDMOutput(recorder, current_flavor, path)

        hddm.istream = istream
        hddm.ostream = ostream
        modules[module_name] = hddm

    sys.modules.update(modules)
    return modules
