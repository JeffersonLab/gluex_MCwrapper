from collections import deque
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


class UnexpectedEffectError(RuntimeError):
    """Raised when code attempts an external effect the test did not configure."""


@dataclass(frozen=True)
class RecordedEffect:
    boundary: str
    operation: str
    args: Tuple[Any, ...]
    kwargs: Mapping[str, Any]


class EffectRecorder:
    def __init__(self) -> None:
        self.calls: List[RecordedEffect] = []

    def record(
        self,
        boundary: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.calls.append(RecordedEffect(boundary, operation, args, dict(kwargs)))


@dataclass(frozen=True)
class ProcessResult:
    returncode: int = 0
    stdout: bytes = b""
    stderr: bytes = b""


class FakeSubprocess:
    def __init__(
        self,
        recorder: EffectRecorder,
        results: Mapping[Tuple[str, Tuple[str, ...]], ProcessResult],
    ) -> None:
        self._recorder = recorder
        self._results = dict(results)

    def run(self, argv: Sequence[str], **kwargs: Any) -> ProcessResult:
        command = tuple(argv)
        self._recorder.record("subprocess", "run", command, **kwargs)
        try:
            return self._results[("run", command)]
        except KeyError as error:
            raise UnexpectedEffectError(
                "unconfigured subprocess.run: {!r}".format(command)
            ) from error


class FakeFilesystem:
    def __init__(
        self,
        recorder: EffectRecorder,
        files: Optional[Mapping[PurePath, str]] = None,
        writable_paths: Iterable[PurePath] = (),
        removable_paths: Iterable[PurePath] = (),
    ) -> None:
        self._recorder = recorder
        self.files: Dict[PurePath, str] = dict(files or {})
        self._writable_paths: Set[PurePath] = set(writable_paths)
        self._removable_paths: Set[PurePath] = set(removable_paths)

    def read_text(self, path: PurePath) -> str:
        self._recorder.record("filesystem", "read_text", path)
        try:
            return self.files[path]
        except KeyError as error:
            raise UnexpectedEffectError(
                "unconfigured filesystem read: {}".format(path)
            ) from error

    def write_text(self, path: PurePath, content: str) -> None:
        self._recorder.record("filesystem", "write_text", path, content)
        if path not in self._writable_paths:
            raise UnexpectedEffectError(
                "unconfigured filesystem write: {}".format(path)
            )
        self.files[path] = content

    def unlink(self, path: PurePath) -> None:
        self._recorder.record("filesystem", "unlink", path)
        if path not in self._removable_paths:
            raise UnexpectedEffectError(
                "unconfigured filesystem removal: {}".format(path)
            )
        self.files.pop(path, None)


class FakeMail:
    def __init__(
        self,
        recorder: EffectRecorder,
        allowed_deliveries: Iterable[Tuple[str, Tuple[str, ...]]],
    ) -> None:
        self._recorder = recorder
        self._allowed_deliveries = set(allowed_deliveries)

    def send(self, sender: str, recipients: Sequence[str], message: str) -> None:
        recipient_tuple = tuple(recipients)
        self._recorder.record("mail", "send", sender, recipient_tuple, message)
        if (sender, recipient_tuple) not in self._allowed_deliveries:
            raise UnexpectedEffectError(
                "unconfigured mail delivery from {!r} to {!r}".format(
                    sender, recipient_tuple
                )
            )


class FakeClock:
    def __init__(self, recorder: EffectRecorder, times: Iterable[Any] = ()) -> None:
        self._recorder = recorder
        self._times: Deque[Any] = deque(times)

    def now(self) -> Any:
        self._recorder.record("clock", "now")
        if not self._times:
            raise UnexpectedEffectError("unconfigured clock read")
        return self._times.popleft()


class FakeHostname:
    def __init__(self, recorder: EffectRecorder, value: Optional[str] = None) -> None:
        self._recorder = recorder
        self._value = value

    def get(self) -> str:
        self._recorder.record("hostname", "get")
        if self._value is None:
            raise UnexpectedEffectError("unconfigured hostname read")
        return self._value


class FakeUsername:
    def __init__(self, recorder: EffectRecorder, value: Optional[str] = None) -> None:
        self._recorder = recorder
        self._value = value

    def get(self) -> str:
        self._recorder.record("username", "get")
        if self._value is None:
            raise UnexpectedEffectError("unconfigured username read")
        return self._value


class FakeEnvironment:
    def __init__(
        self,
        recorder: EffectRecorder,
        values: Optional[Mapping[str, str]] = None,
        readable: Iterable[str] = (),
        writable: Iterable[str] = (),
    ) -> None:
        self._recorder = recorder
        self.values: Dict[str, str] = dict(values or {})
        self._readable = set(readable)
        self._writable = set(writable)

    def get(self, name: str) -> Optional[str]:
        self._recorder.record("environment", "get", name)
        if name not in self._readable:
            raise UnexpectedEffectError(
                "unconfigured environment read: {!r}".format(name)
            )
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self._recorder.record("environment", "set", name, value)
        if name not in self._writable:
            raise UnexpectedEffectError(
                "unconfigured environment write: {!r}".format(name)
            )
        self.values[name] = value


class FakeNetwork:
    def __init__(
        self,
        recorder: EffectRecorder,
        responses: Mapping[Tuple[str, str], Any],
    ) -> None:
        self._recorder = recorder
        self._responses = dict(responses)

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        key = (method.upper(), url)
        self._recorder.record("network", "request", *key, **kwargs)
        try:
            return self._responses[key]
        except KeyError as error:
            raise UnexpectedEffectError(
                "unconfigured network request: {} {}".format(*key)
            ) from error


class FakeScheduler:
    def __init__(
        self,
        recorder: EffectRecorder,
        results: Mapping[Tuple[str, ...], ProcessResult],
    ) -> None:
        self._recorder = recorder
        self._results = dict(results)

    def execute(self, argv: Sequence[str]) -> ProcessResult:
        command = tuple(argv)
        self._recorder.record("scheduler", "execute", command)
        try:
            return self._results[command]
        except KeyError as error:
            raise UnexpectedEffectError(
                "unconfigured scheduler command: {!r}".format(command)
            ) from error


def reject_external_effect(*args: Any, **kwargs: Any) -> None:
    del args, kwargs
    raise UnexpectedEffectError("external process, scheduler, or network access denied")

