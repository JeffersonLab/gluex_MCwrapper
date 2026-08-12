import socket
import subprocess

import pytest

from tests.fakes.effects import reject_external_effect


@pytest.fixture(autouse=True)
def deny_unconfigured_process_and_network_access(monkeypatch):
    for operation in ("call", "check_call", "check_output", "Popen", "run"):
        monkeypatch.setattr(subprocess, operation, reject_external_effect)

    monkeypatch.setattr(socket, "create_connection", reject_external_effect)
    monkeypatch.setattr(socket, "socket", reject_external_effect)

