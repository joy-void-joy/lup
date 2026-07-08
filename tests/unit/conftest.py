"""Shared fixtures and fakes for unit tests."""

from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from lup.workspace import paths
from lup.adapters.clients.Client import (
    Client,
    Session,
    query_via_session,
    replay_stream,
)
from lup.adapters.options import LupAgentOptions
from lup.telemetry.trace import TraceLogger
from lup.types import LupEvent, LupResponse, LupTextBlock

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


class RecordingClient(Client):
    """A fake client carrying the options it was built from."""

    def __init__(self, opts: LupAgentOptions, ran: list[LupAgentOptions]) -> None:
        self.opts = opts
        self.ran = ran

    @asynccontextmanager
    async def session(
        self, *, resume: str | None = None
    ) -> AsyncGenerator[Session, None]:
        yield RecordingSession(self.opts, self.ran, resumed=resume)

    async def query(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        return await query_via_session(
            self, prompt, trace_logger=trace_logger, prefix=prefix
        )

    def stream(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        return replay_stream(self, prompt, trace_logger=trace_logger, prefix=prefix)


class RecordingEngine:
    """A fake engine factory passed as ``engine=``: records built and ran options.

    A plain :data:`~lup.adapters.wiring.ClientFactory` callable —
    construction alone is not execution, so options land in ``ran`` only
    when a session actually sends a turn.
    """

    def __init__(self) -> None:
        self.built: list[LupAgentOptions] = []
        self.ran: list[LupAgentOptions] = []

    def __call__(self, opts: LupAgentOptions) -> Client:
        self.built.append(opts)
        return RecordingClient(opts, self.ran)


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
