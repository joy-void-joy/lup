"""Each runtime's hooks in lup's own words: the only code that names a runtime.

Each runtime's module builds its `Adapter`, what lup needs of it: how its hooks
are answered, and what a launch of it runs. The command line lists them.
"""

from collections.abc import Callable
from datetime import timedelta

from lup.sessions.declaration import Declaration
from lup.sessions.terminal import Hook
from lup.types import Model
from lup_dev.launch.clis import Channel
from lup_dev.policy.checkpoint import Bench
from lup_dev.policy.runtime import Runtime


class Adapter(Model, arbitrary_types_allowed=True):
    """A runtime lup knows: how its hooks are answered, and what a launch of it needs."""

    runtime: Runtime
    hook: Callable[[str, Bench], str]
    """Answers one of its hooks: a payload in, what the hook prints out."""
    unanswered: Callable[[str, str], str]
    """Answers a hook lup's judge couldn't: the payload and why in, what the hook
    prints out."""
    hooks: Callable[[list[str], timedelta], list[Hook]]
    """The hooks a launched session runs a command at, each waiting up to a
    timeout: the events the judge reads."""
    channel: Channel
    """Its release channel, which a launch fetches the latest CLI from."""
    agent: Callable[[], Declaration]
    """The declaration a launched session runs."""
