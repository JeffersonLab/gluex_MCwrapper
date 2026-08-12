from pathlib import PurePosixPath

import pytest

from tests.fakes.effects import (
    EffectRecorder,
    FakeClock,
    FakeEnvironment,
    FakeFilesystem,
    FakeHostname,
    FakeMail,
    FakeNetwork,
    FakeScheduler,
    FakeSubprocess,
    FakeUsername,
    ProcessResult,
    UnexpectedEffectError,
)


def test_subprocess_records_configured_calls_and_rejects_unknown_commands():
    recorder = EffectRecorder()
    result = ProcessResult(stdout=b"ready\n")
    process = FakeSubprocess(recorder, {("run", ("safe-tool",)): result})

    assert process.run(["safe-tool"], cwd="/work") == result
    with pytest.raises(UnexpectedEffectError, match="unconfigured subprocess"):
        process.run(["sbatch", "job.sh"])

    assert [call.operation for call in recorder.calls] == ["run", "run"]
    assert recorder.calls[0].kwargs == {"cwd": "/work"}


def test_filesystem_records_reads_writes_and_removals_and_rejects_unknown_paths():
    recorder = EffectRecorder()
    source = PurePosixPath("/sandbox/input.txt")
    output = PurePosixPath("/sandbox/output.txt")
    filesystem = FakeFilesystem(
        recorder,
        files={source: "input"},
        writable_paths={output},
        removable_paths={output},
    )

    assert filesystem.read_text(source) == "input"
    filesystem.write_text(output, "result")
    filesystem.unlink(output)
    with pytest.raises(UnexpectedEffectError, match="unconfigured filesystem write"):
        filesystem.write_text(PurePosixPath("/production/output.txt"), "unsafe")

    assert [call.operation for call in recorder.calls] == [
        "read_text",
        "write_text",
        "unlink",
        "write_text",
    ]


def test_mail_records_delivery_and_rejects_unknown_recipients():
    recorder = EffectRecorder()
    mail = FakeMail(recorder, {("sender@example.test", ("allowed@example.test",))})

    mail.send("sender@example.test", ["allowed@example.test"], "complete")
    with pytest.raises(UnexpectedEffectError, match="unconfigured mail"):
        mail.send("sender@example.test", ["unexpected@example.test"], "complete")

    assert [call.operation for call in recorder.calls] == ["send", "send"]


def test_clock_records_reads_and_rejects_reads_after_configured_values_are_used():
    recorder = EffectRecorder()
    clock = FakeClock(recorder, [123.5])

    assert clock.now() == 123.5
    with pytest.raises(UnexpectedEffectError, match="unconfigured clock"):
        clock.now()

    assert [call.operation for call in recorder.calls] == ["now", "now"]


@pytest.mark.parametrize(
    ("fake_type", "boundary", "configured_value"),
    [
        (FakeHostname, "hostname", "test-host"),
        (FakeUsername, "username", "test-user"),
    ],
)
def test_identity_fakes_record_reads_and_require_configuration(
    fake_type, boundary, configured_value
):
    recorder = EffectRecorder()

    assert fake_type(recorder, configured_value).get() == configured_value
    with pytest.raises(UnexpectedEffectError, match="unconfigured {}".format(boundary)):
        fake_type(recorder).get()

    assert [call.boundary for call in recorder.calls] == [boundary, boundary]


def test_environment_records_access_and_rejects_unknown_names():
    recorder = EffectRecorder()
    environment = FakeEnvironment(
        recorder,
        values={"PROFILE": "test"},
        readable={"PROFILE"},
        writable={"TOKEN_PATH"},
    )

    assert environment.get("PROFILE") == "test"
    environment.set("TOKEN_PATH", "/sandbox/token")
    with pytest.raises(UnexpectedEffectError, match="unconfigured environment read"):
        environment.get("SECRET")

    assert [call.operation for call in recorder.calls] == ["get", "set", "get"]


def test_network_records_requests_and_rejects_unknown_endpoints():
    recorder = EffectRecorder()
    network = FakeNetwork(recorder, {("GET", "https://example.test/status"): "ok"})

    assert network.request("get", "https://example.test/status") == "ok"
    with pytest.raises(UnexpectedEffectError, match="unconfigured network"):
        network.request("GET", "https://production.example/status")

    assert [call.operation for call in recorder.calls] == ["request", "request"]


def test_scheduler_records_commands_and_rejects_unknown_submissions():
    recorder = EffectRecorder()
    result = ProcessResult(stdout=b"dry-run")
    scheduler = FakeScheduler(recorder, {("condor_q",): result})

    assert scheduler.execute(["condor_q"]) == result
    with pytest.raises(UnexpectedEffectError, match="unconfigured scheduler"):
        scheduler.execute(["condor_submit", "job.sub"])

    assert [call.operation for call in recorder.calls] == ["execute", "execute"]


def test_real_process_and_network_apis_are_denied_by_default():
    import socket
    import subprocess

    with pytest.raises(UnexpectedEffectError, match="access denied"):
        subprocess.run(["condor_submit", "job.sub"])
    with pytest.raises(UnexpectedEffectError, match="access denied"):
        socket.create_connection(("example.test", 443))
