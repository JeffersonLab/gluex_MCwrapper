import runpy
import sys

import mcwrapper
import pytest
from mcwrapper.cli import main


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


def test_module_entry_point_help_is_available(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["mcwrapper", "--help"])

    with pytest.raises(SystemExit, match="0"):
        runpy.run_module("mcwrapper", run_name="__main__")

    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.startswith("usage: mcwrapper")
