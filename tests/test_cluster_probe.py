import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import cluster_probe


def test_probe_reports_environment_names_without_values(monkeypatch):
    monkeypatch.setattr(cluster_probe, "package_versions", lambda names: {"pkg": "1"})
    monkeypatch.setattr(
        cluster_probe, "executable_capabilities", lambda names: {"sbatch": True}
    )
    monkeypatch.setattr(cluster_probe, "path_capabilities", lambda paths: {})
    monkeypatch.setattr(cluster_probe.shutil, "which", lambda name: None)

    secret = "mysql://user:password@example.invalid/database"
    payload = cluster_probe.collect_probe(
        environment={"RCDB_CONNECTION": secret, "UNRELATED_SECRET": "token"}
    )
    rendered = cluster_probe.render_json(payload)

    assert payload["environment_names"] == ["RCDB_CONNECTION"]
    assert secret not in rendered
    assert "UNRELATED_SECRET" not in rendered
    assert "token" not in rendered


def test_render_json_is_stable_and_sorted():
    payload = {"z": [2, 1], "a": {"d": 4, "b": 2}}
    first = cluster_probe.render_json(payload)
    second = cluster_probe.render_json(payload)

    assert first == second
    assert json.loads(first) == payload
    assert first.index('"a"') < first.index('"z"')
    assert first.endswith("\n")


def test_sql_mode_uses_only_a_read_only_select(monkeypatch, tmp_path):
    defaults = tmp_path / "mysql.cnf"
    defaults.write_text("[client]\npassword=top-secret\n", encoding="utf-8")
    defaults.chmod(0o600)
    calls = []

    monkeypatch.setattr(cluster_probe.shutil, "which", lambda name: "/usr/bin/mysql")

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="STRICT_TRANS_TABLES\n", stderr="")

    monkeypatch.setattr(cluster_probe.subprocess, "run", fake_run)

    assert cluster_probe.sql_mode(defaults) == "STRICT_TRANS_TABLES"
    assert calls[0][0][-2:] == ["--execute", "SELECT @@SESSION.sql_mode"]
    assert "top-secret" not in " ".join(calls[0][0])
    assert calls[0][1]["check"] is False


def test_defaults_file_must_be_mode_0600(tmp_path):
    defaults = tmp_path / "mysql.cnf"
    defaults.write_text("[client]\n", encoding="utf-8")
    defaults.chmod(0o644)

    with pytest.raises(ValueError, match="0600"):
        cluster_probe.validate_defaults_file(defaults)
