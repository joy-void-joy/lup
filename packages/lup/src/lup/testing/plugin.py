"""The pytest plugin every project installing `lup[testing]` runs: the guard, and `fake_agents`.

**The guard** is on for the whole test session:
- an ask that reaches a real adapter raises `RealCallInTestError`, naming the
  fixture to use instead;
- network connections are refused except to loopback and Unix sockets, through
  `pytest-socket`, whose per-test `enable_socket` marker lifts it;
- without `lup[testing]` installed, the session stops and names the extra,
  rather than running unguarded.

**`fake_agents`** gives a test the fake, in place of every declaration's adapter,
for that test alone.
"""

from typing import TYPE_CHECKING, override

import pytest

from lup.errors import LupError
from lup.sessions.contract import Adapter, RawTurn, Seam, TurnRequest, guarded, seam
from lup.testing.fake import FakeAgents
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lup.sessions.declaration import Declaration


class RealCallInTestError(LupError):
    """A test asked a real agent, where it should have scripted the fake."""


class Refused(Model, Adapter):
    """Refuses every turn: what a test without the fake runs on."""

    runtime: str

    @override
    async def run(self, request: TurnRequest) -> RawTurn:
        """Raise, naming the fixture that answers in place of the runtime."""
        message = (
            f"a test asked a real {self.runtime} agent; ask for the `fake_agents` "
            "fixture and script the answer with `fake_agents.answer(...)`"
        )
        raise RealCallInTestError(message)


class Refusing(Model, Seam):
    """The seam outside `fake_agents`: every declaration's turns are refused."""

    @override
    def adapter(self, declaration: Declaration) -> Adapter:
        """Return an adapter that refuses `declaration`'s turns."""
        return Refused(runtime=declaration.runtime)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Turn the guard on before `pytest-socket` reads its options, or stop without it."""
    if not config.pluginmanager.hasplugin("socket"):
        message = (
            "lup's test guard needs the `lup[testing]` extra, which isn't installed: "
            "install `lup[testing]` so tests can't reach a real agent or the network"
        )
        raise pytest.UsageError(message)
    config.option.disable_socket = True
    config.option.allow_unix_socket = True
    config.option.allow_hosts = config.option.allow_hosts or "127.0.0.1,::1"
    seam.set(Refusing())
    guarded.set(True)


@pytest.fixture
def fake_agents() -> Iterator[FakeAgents]:
    """Give the test the fake, which answers every ask from the test's script."""
    agents = FakeAgents()
    token = seam.set(agents)
    yield agents
    seam.reset(token)
