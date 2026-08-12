"""Deterministic subprocess harness for characterizing legacy entry points."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence


_isolated_popen = subprocess.Popen
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CHILD_BOOTSTRAP = Path(__file__).with_name("legacy_subprocess_child.py")


@dataclass(frozen=True)
class FakeCommandResult:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class LegacyRunResult:
    stdout: str
    stderr: str
    exit_status: int
    files: Mapping[str, str]
    sql: Sequence[Mapping[str, Any]]
    commands: Sequence[Mapping[str, Any]]
    messages: Sequence[Mapping[str, Any]]
    effects: Sequence[Mapping[str, Any]]


@dataclass(frozen=True)
class LegacyRun:
    entry_point: Path
    argv: Sequence[str] = ()
    environment: Mapping[str, str] = field(default_factory=dict)
    files: Mapping[str, str] = field(default_factory=dict)
    commands: Mapping[str, FakeCommandResult] = field(default_factory=dict)
    intercepted_commands: Mapping[str, FakeCommandResult] = field(default_factory=dict)
    mysql_results: Sequence[Mapping[str, Any]] = ()
    rcdb_results: Sequence[Mapping[str, Any]] = ()
    hddm_inputs: Sequence[Mapping[str, Any]] = ()
    username: Optional[str] = None
    hostname: Optional[str] = None


@dataclass(frozen=True)
class LegacyShellRun:
    """A legacy shell script copied into explicitly mapped temporary roots."""

    entry_point: Path
    path_mappings: Mapping[str, str]
    environment: Mapping[str, str] = field(default_factory=dict)
    files: Mapping[str, str] = field(default_factory=dict)
    commands: Mapping[str, FakeCommandResult] = field(default_factory=dict)


def _write_command_shim(path: Path, result: FakeCommandResult) -> None:
    source = """#!{python}
import json
import os
from pathlib import Path
import sys

record = {{"argv": [Path(sys.argv[0]).name] + sys.argv[1:]}}
with Path(os.environ["MCWRAPPER_HARNESS_COMMANDS"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record, sort_keys=True) + "\\n")
sys.stdout.write({stdout!r})
sys.stderr.write({stderr!r})
raise SystemExit({returncode})
""".format(
        python=sys.executable,
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
    )
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _read_json_lines(path: Path) -> List[Mapping[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _normalize(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        for original, replacement in replacements.items():
            value = value.replace(original, replacement)
        return value.replace("\r\n", "\n")
    if isinstance(value, list):
        return [_normalize(item, replacements) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize(item, replacements) for item in value)
    if isinstance(value, dict):
        return {
            key: _normalize(item, replacements) for key, item in value.items()
        }
    return value


def _snapshot_files(work_dir: Path) -> Dict[str, str]:
    snapshot = {}
    for path in sorted(item for item in work_dir.rglob("*") if item.is_file()):
        relative_path = path.relative_to(work_dir).as_posix()
        try:
            snapshot[relative_path] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            snapshot[relative_path] = "<BINARY:{} bytes>".format(path.stat().st_size)
    return snapshot


def run_legacy(run: LegacyRun) -> LegacyRunResult:
    """Run one legacy script in an isolated directory with fail-closed stubs."""
    entry_point = run.entry_point.resolve()
    if not entry_point.is_relative_to(_REPOSITORY_ROOT):
        raise ValueError("entry point must be inside the repository")

    with tempfile.TemporaryDirectory(prefix="mcwrapper-legacy-") as temporary:
        root = Path(temporary)
        work_dir = root / "work"
        control_dir = root / "control"
        fake_bin = control_dir / "bin"
        work_dir.mkdir()
        fake_bin.mkdir(parents=True)

        for relative_name, content in run.files.items():
            relative_path = Path(relative_name)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError("fixture file paths must remain inside the working directory")
            destination = work_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")

        for name, result in run.commands.items():
            if Path(name).name != name:
                raise ValueError("fake command names must be basenames")
            _write_command_shim(fake_bin / name, result)

        config_path = control_dir / "config.json"
        effects_path = control_dir / "effects.json"
        commands_path = control_dir / "commands.jsonl"
        config = {
            "entry_point": str(entry_point),
            "argv": list(run.argv),
            "mysql_results": list(run.mysql_results),
            "rcdb_results": list(run.rcdb_results),
            "hddm_inputs": list(run.hddm_inputs),
            "username": run.username,
            "hostname": run.hostname,
            "allowed_commands": sorted(run.commands),
            "intercepted_commands": {
                name: {
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
                for name, result in run.intercepted_commands.items()
            },
        }
        config_path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")

        environment = {
            "HOME": str(work_dir / "home"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": str(fake_bin),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(_REPOSITORY_ROOT),
            "TMPDIR": str(work_dir / "tmp"),
            "MCWRAPPER_HARNESS_CONFIG": str(config_path),
            "MCWRAPPER_HARNESS_EFFECTS": str(effects_path),
            "MCWRAPPER_HARNESS_COMMANDS": str(commands_path),
        }
        reserved_environment = set(environment).intersection(run.environment)
        if reserved_environment:
            raise ValueError(
                "cannot override controlled environment variables: {}".format(
                    ", ".join(sorted(reserved_environment))
                )
            )
        environment.update(run.environment)
        (work_dir / "home").mkdir()
        (work_dir / "tmp").mkdir()

        process = _isolated_popen(
            [sys.executable, "-B", str(_CHILD_BOOTSTRAP)],
            cwd=str(work_dir),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate()
        effects = (
            json.loads(effects_path.read_text(encoding="utf-8"))
            if effects_path.exists()
            else []
        )
        commands = _read_json_lines(commands_path)
        replacements = {
            str(work_dir): "<WORKDIR>",
            str(control_dir): "<CONTROL>",
            str(_REPOSITORY_ROOT): "<REPOSITORY>",
        }
        normalized_effects = _normalize(effects, replacements)

        return LegacyRunResult(
            stdout=_normalize(stdout, replacements),
            stderr=_normalize(stderr, replacements),
            exit_status=process.returncode,
            files=_normalize(_snapshot_files(work_dir), replacements),
            sql=[
                effect
                for effect in normalized_effects
                if effect["boundary"] == "mysql"
            ],
            commands=_normalize(commands, replacements),
            messages=[
                effect
                for effect in normalized_effects
                if effect["boundary"] == "mail"
            ],
            effects=normalized_effects,
        )


def run_legacy_shell(run: LegacyShellRun) -> LegacyRunResult:
    """Run an instrumented shell copy whose declared roots stay temporary."""
    entry_point = run.entry_point.resolve()
    if not entry_point.is_relative_to(_REPOSITORY_ROOT):
        raise ValueError("entry point must be inside the repository")

    with tempfile.TemporaryDirectory(prefix="mcwrapper-legacy-shell-") as temporary:
        root = Path(temporary)
        work_dir = root / "work"
        control_dir = root / "control"
        fake_bin = control_dir / "bin"
        work_dir.mkdir()
        fake_bin.mkdir(parents=True)

        for relative_name, content in run.files.items():
            relative_path = Path(relative_name)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError("fixture file paths must remain inside the working directory")
            destination = work_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")

        source = entry_point.read_text(encoding="utf-8")
        for production_root, fixture_root in run.path_mappings.items():
            relative_root = Path(fixture_root)
            if not production_root.startswith("/"):
                raise ValueError("mapped production roots must be absolute")
            if relative_root.is_absolute() or ".." in relative_root.parts:
                raise ValueError("mapped fixture roots must remain inside the working directory")
            if production_root not in source:
                raise ValueError("mapped production root not present in shell script")
            mapped_root = work_dir / relative_root
            mapped_root.mkdir(parents=True, exist_ok=True)
            source = source.replace(production_root, str(mapped_root))

        instrumented_script = control_dir / entry_point.name
        instrumented_script.write_text(source, encoding="utf-8")

        commands_path = control_dir / "commands.jsonl"
        for name, result in run.commands.items():
            if Path(name).name != name:
                raise ValueError("fake command names must be basenames")
            _write_command_shim(fake_bin / name, result)

        environment = {
            "HOME": str(work_dir / "home"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": str(fake_bin),
            "TMPDIR": str(work_dir / "tmp"),
            "MCWRAPPER_HARNESS_COMMANDS": str(commands_path),
        }
        reserved_environment = set(environment).intersection(run.environment)
        if reserved_environment:
            raise ValueError(
                "cannot override controlled environment variables: {}".format(
                    ", ".join(sorted(reserved_environment))
                )
            )
        environment.update(run.environment)
        (work_dir / "home").mkdir(exist_ok=True)
        (work_dir / "tmp").mkdir(exist_ok=True)

        process = _isolated_popen(
            ["/bin/bash", "-f", str(instrumented_script)],
            cwd=str(work_dir),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate()
        replacements = {
            str(work_dir): "<WORKDIR>",
            str(control_dir): "<CONTROL>",
            str(_REPOSITORY_ROOT): "<REPOSITORY>",
        }

        return LegacyRunResult(
            stdout=_normalize(stdout, replacements),
            stderr=_normalize(stderr, replacements),
            exit_status=process.returncode,
            files=_normalize(_snapshot_files(work_dir), replacements),
            sql=[],
            commands=_normalize(_read_json_lines(commands_path), replacements),
            messages=[],
            effects=[],
        )
