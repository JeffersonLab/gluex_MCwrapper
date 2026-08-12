"""Child-process bootstrap used by the legacy characterization harness."""

import json
import os
from pathlib import Path
import runpy
import smtplib
import socket
import subprocess
import sys
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from tests.fakes.effects import EffectRecorder
from tests.fakes.effects import UnexpectedEffectError
from tests.fakes.legacy_modules import install_legacy_module_stubs


def _sql_results(
    rows: Iterable[Mapping[str, Any]],
) -> Dict[Tuple[str, Optional[Tuple[Any, ...]]], Sequence[Any]]:
    return {
        (
            row["query"],
            None if row.get("params") is None else tuple(row["params"]),
        ): row.get("rows", [])
        for row in rows
    }


def _rcdb_results(
    rows: Iterable[Mapping[str, Any]],
) -> Dict[Tuple[str, Any, Any, Tuple[str, ...], bool], Sequence[Any]]:
    return {
        (
            row["query"],
            row["minimum_run"],
            row["maximum_run"],
            tuple(row["fields"]),
            bool(row.get("insert_run_number", False)),
        ): row.get("rows", [])
        for row in rows
    }


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return repr(value)


def _install_safety_guards(
    recorder: EffectRecorder, allowed_commands: Sequence[str]
) -> None:
    """Deny network/shell escape while allowing configured fake-PATH commands."""
    allowed = set(allowed_commands)
    original_popen = subprocess.Popen

    def guarded_popen(argv: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("shell"):
            raise UnexpectedEffectError(
                "shell subprocess denied by legacy harness; use an isolated shell fixture"
            )
        if isinstance(argv, (str, bytes)) or not argv:
            raise UnexpectedEffectError(
                "unconfigured subprocess command: {!r}".format(argv)
            )
        executable = os.fspath(argv[0])
        if os.path.basename(executable) not in allowed or os.path.dirname(executable):
            raise UnexpectedEffectError("unconfigured subprocess command: {!r}".format(argv))
        return original_popen(argv, *args, **kwargs)

    def deny_network(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise UnexpectedEffectError("network access denied by legacy harness")

    def deny_system(command: str) -> None:
        raise UnexpectedEffectError(
            "os.system denied by legacy harness: {!r}".format(command)
        )

    class RecordingSMTP:
        def __init__(
            self, host: str = "", port: int = 0, *args: Any, **kwargs: Any
        ) -> None:
            recorder.record("mail", "connect", host, port, *args, **kwargs)

        def send_message(self, message: Any, *args: Any, **kwargs: Any) -> None:
            recorder.record("mail", "send_message", str(message), *args, **kwargs)

        def sendmail(
            self,
            sender: str,
            recipients: Sequence[str],
            message: str,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            recorder.record(
                "mail", "sendmail", sender, tuple(recipients), message, *args, **kwargs
            )

        def quit(self) -> None:
            recorder.record("mail", "quit")

    subprocess.Popen = guarded_popen
    os.system = deny_system
    socket.create_connection = deny_network
    socket.socket = deny_network
    smtplib.SMTP = RecordingSMTP


def main() -> None:
    config_path = Path(os.environ["MCWRAPPER_HARNESS_CONFIG"])
    effects_path = Path(os.environ["MCWRAPPER_HARNESS_EFFECTS"])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    recorder = EffectRecorder()

    install_legacy_module_stubs(
        recorder,
        mysql_results=_sql_results(config.get("mysql_results", [])),
        rcdb_results=_rcdb_results(config.get("rcdb_results", [])),
        hddm_inputs={
            (row["flavor"], row["path"]): row.get("entries", [])
            for row in config.get("hddm_inputs", [])
        },
    )
    _install_safety_guards(recorder, config.get("allowed_commands", []))

    sys.argv = [config["entry_point"]] + list(config.get("argv", []))
    try:
        runpy.run_path(config["entry_point"], run_name="__main__")
    finally:
        effects = [
            {
                "boundary": call.boundary,
                "operation": call.operation,
                "args": _json_value(call.args),
                "kwargs": _json_value(call.kwargs),
            }
            for call in recorder.calls
        ]
        effects_path.write_text(json.dumps(effects, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
