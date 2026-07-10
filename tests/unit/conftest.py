# lup: ignore[empty-collection, frozenset-shape]
# Test fixtures and assertions construct these shapes deliberately.
"""Shared fixtures and fakes for unit tests."""

from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from lup.workspace import paths
from lup.adapters.background.agent import BackgroundAgent
from lup.adapters.background.params import BackgroundAgentParams
from lup.adapters.clients.Client import Client
from lup.adapters.clients.composed import ComposedClient
from lup.adapters.clients.sessions.Session import Session
from lup.adapters.clients.sessions.Sessions import Sessions
from lup.adapters.engines.Engine import Engine
from lup.adapters.errors import UnsupportedOperationError
from lup.adapters.options import LupAgentOptions
from lup.adapters.profiles.Profile import Profile
from lup.telemetry.trace import TraceLogger
from lup.types import LupResponse, LupTextBlock

LUP_PROJECT_VERSION = "1.2.3"


class RecordingSession(Session):
    """One canned turn per send; reports the options that produced it."""

    def __init__(
        self, opts: LupAgentOptions, ran: list[LupAgentOptions], *, resumed: str | None
    ) -> None:
        self.opts = opts
        self.ran = ran
        self.id = resumed

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        self.ran.append(self.opts)
        return LupResponse(blocks=[LupTextBlock(text="ok")])

    async def interrupt(self) -> None:
        raise NotImplementedError("RecordingSession has no interrupt")


class RecordingSessions(Sessions):
    """A fake sessions component carrying the options it was built from."""

    def __init__(self, opts: LupAgentOptions, ran: list[LupAgentOptions]) -> None:
        self.opts = opts
        self.ran = ran

    @asynccontextmanager
    async def open(self, *, resume: str | None = None) -> AsyncGenerator[Session, None]:
        yield RecordingSession(self.opts, self.ran, resumed=resume)


class RecordingEngine(Engine):
    """A fake engine passed as ``engine=``: records built and ran options.

    Construction alone is not execution, so options land in ``ran`` only
    when a session actually sends a turn. The non-client capabilities
    refuse explicitly, as a real capability-less engine would.
    """

    id = "recording"

    def __init__(self) -> None:
        self.built: list[LupAgentOptions] = []
        self.ran: list[LupAgentOptions] = []

    def client(self, options: LupAgentOptions) -> Client:
        self.built.append(options)
        return ComposedClient(RecordingSessions(options, self.ran))

    def background(self, params: BackgroundAgentParams) -> BackgroundAgent:
        raise UnsupportedOperationError("the recording engine has no backgrounds")

    def profiles(self) -> Profile:
        raise UnsupportedOperationError("the recording engine has no profiles")

    def builtin_tools(self) -> frozenset[str]:
        raise UnsupportedOperationError("the recording engine has no builtin table")


@pytest.fixture
def tmp_lup_project(tmp_path: Path) -> Iterator[Path]:
    """A throwaway project root wired into lup.workspace.paths, restored afterwards."""
    (tmp_path / "pyproject.toml").write_text(
        f'[tool.lup]\nagent_version = "{LUP_PROJECT_VERSION}"\n', encoding="utf-8"
    )
    old_root = paths.project_root()
    paths.configure(root=tmp_path)
    yield tmp_path
    paths.configure(root=old_root)
