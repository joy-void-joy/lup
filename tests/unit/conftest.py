"""Shared fixtures and fakes for unit tests."""

from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from lup import paths
from lup.adapters.common import (
    AdapterCapabilities,
    AgentAdapter,
    Conversation,
    OneShotRequest,
)
from lup.trace import TraceLogger
from lup.types import LupResponse, LupTextBlock

LUP_PROJECT_VERSION = "1.2.3"


def weak_capabilities() -> AdapterCapabilities:
    """The Codex tier's declarations — the weakest shipped backend."""
    from lup.adapters.codex.adapter import CodexAdapter

    return CodexAdapter(model="probe", system_prompt="").capabilities


class RecordingConversation(Conversation):
    """One canned turn per send; reports the request that produced it."""

    def __init__(self, request: OneShotRequest, ran: list[OneShotRequest]) -> None:
        self.request = request
        self.ran = ran

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        self.ran.append(self.request)
        return LupResponse(blocks=[LupTextBlock(text="ok")])


class RecordingAdapter(AgentAdapter):
    """A fake adapter carrying the one-shot request it was built from."""

    def __init__(self, request: OneShotRequest, engine: "RecordingOneShot") -> None:
        self.request = request
        self.engine = engine

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self.engine.declared

    @asynccontextmanager
    async def conversation(self) -> AsyncGenerator[Conversation, None]:
        yield RecordingConversation(self.request, self.engine.ran)


class RecordingOneShot:
    """A fake engine to patch into ``registry.ONE_SHOT_BUILDERS``.

    ``backend_capabilities`` probes builders with a throwaway request, so
    construction alone is not execution — a request lands in ``ran`` only
    when its adapter's conversation actually sends a turn.
    """

    def __init__(self, capabilities: AdapterCapabilities | None = None) -> None:
        self.ran: list[OneShotRequest] = []
        self.declared = capabilities or weak_capabilities()

    def __call__(self, request: OneShotRequest) -> AgentAdapter:
        return RecordingAdapter(request, self)


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
