"""Shared process doubles for the tests that drive a git boundary.

Every resolver test that needed a launcher wrote the same class: dispatch on
the two words a git invocation starts with, answer that probe, remember the
call. What differed between them was only *which* probes they answered, so
each copy restated the dispatch to vary the answers — and a change to the
orchestrator's probes had to be found in nine places.

:class:`ScriptedLauncher` takes the answers as data and keeps the dispatch
once. A test declares the probes it cares about and inherits recording; a
probe it does not declare succeeds silently, which is what the hand-rolled
doubles all did with their trailing `return ExitStatus(code=0)`.
"""

from lup.harness.process import ExitStatus, LaunchRequest, ProcessLauncher

PROBE_WORDS = 2
"""How many words after the executable name identify a git probe."""


def probe_of(request: LaunchRequest) -> str:
    """The subcommand words a launch request is answering, as a script key."""
    return " ".join(request.arguments[1 : 1 + PROBE_WORDS])


def out(stdout: str = "", code: int = 0, stderr: str = "") -> ExitStatus:
    """One scripted answer, spelled the way a test reads it."""
    return ExitStatus(code=code, stdout=stdout, stderr=stderr)


class ScriptedLauncher(ProcessLauncher):
    """Answer declared git probes in order, recording every launch.

    Keys are the two words following the executable — ``"rev-parse HEAD"``,
    ``"diff --name-only"``. A list of answers is consumed one per call and its
    last entry repeats, which is how a probe that must report differently
    before and after an operation is expressed without a counter.
    """

    def __init__(
        self,
        script: dict[str, ExitStatus | list[ExitStatus]] | None = None,
        default: ExitStatus | None = None,
    ) -> None:
        self.script = dict(script or {})
        self.default = default if default is not None else out()
        self.requests: list[LaunchRequest] = []
        self.answered: dict[str, int] = {}

    @property
    def arguments(self) -> list[list[str]]:
        """Every launch's argument list, in call order."""
        return [request.arguments for request in self.requests]

    def probes(self, probe: str) -> int:
        """How many times one declared probe has been asked."""
        return self.answered[probe] if probe in self.answered else 0

    def launch(self, request: LaunchRequest) -> ExitStatus:
        self.requests.append(request)
        probe = probe_of(request)
        if probe not in self.script:
            return self.default
        asked = self.probes(probe)
        self.answered[probe] = asked + 1
        answers = self.script[probe]
        if not isinstance(answers, list):
            return answers
        return answers[min(asked, len(answers) - 1)]


class FailingLauncher(ProcessLauncher):
    """Fail every launch, echoing the arguments that were refused."""

    def __init__(self, code: int = 1) -> None:
        self.code = code
        self.requests: list[LaunchRequest] = []

    def launch(self, request: LaunchRequest) -> ExitStatus:
        self.requests.append(request)
        return ExitStatus(code=self.code, stderr=f"failed: {request.arguments}")
