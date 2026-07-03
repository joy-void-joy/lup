"""Shared fixtures and fakes for unit tests."""

from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from lup import paths
from lup.adapters.common import Client, Session
from lup.adapters.engine import Engine
from lup.options import LupAgentOptions
from lup.trace import TraceLogger
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


class RecordingEngine(Engine):
    """A fake engine passed as ``engine=``: records built and ran options.

    Construction alone is not execution — options land in ``ran`` only
    when a session actually sends a turn.
    """

    id = "recording"

    def __init__(self) -> None:
        self.built: list[LupAgentOptions] = []
        self.ran: list[LupAgentOptions] = []

    def client(self, opts: LupAgentOptions) -> Client:
        self.built.append(opts)
        return RecordingClient(opts, self.ran)


@pytest.fixture
def tmp_lup_project(tmp_path: Path) -> Iterator[Path]:
    """A throwaway project root wired into lup.paths, restored afterwards."""
    (tmp_path / "pyproject.toml").write_text(
        f'[tool.lup]\nagent_version = "{LUP_PROJECT_VERSION}"\n', encoding="utf-8"
    )
    old_root = paths.project_root()
    paths.configure(root=tmp_path)
    yield tmp_path
    paths.configure(root=old_root)
