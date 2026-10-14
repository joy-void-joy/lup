"""What the host reads of each runtime's hooks, and how it answers them; lup's own id for each conversation.

`docs/host-tools.md`, *Who's calling* and *How an agent is told*. Every hook a
launch's room sends reaches the host service, which hears it through the
`Courier` (`heard`): its event, the runtime's own ids for the session and the
conversation in it, its call and tool, and whether the launch's judge reads it.
A hook the judge doesn't read the service answers itself, without starting the
judge's process. Every answer, the judge's or the service's own, goes out through
the `Courier` again (`told`): with what the conversation is told added, and a call
to lup's tools rewritten to carry its `caller`, lup's id for the conversation.
Each runtime's adapter fills both, since only it knows its runtime's spelling;
`cli.py` builds the `Courier` from them, as it builds the `Answerer`.

lup's own id for each conversation (`Conversations`) is minted the first time a
hook names it (a session's start, a subagent's start, its first call), and kept
with the runtime's ids it stands for, so nothing past the adapter reads a
runtime's ids. A launch's ids live as long as the service serves it: a service
started again mints its own, which its hooks stamp from then on, while every MCP
connection the service before held closed with it.
"""

import secrets
from abc import ABC, abstractmethod

from lup.sessions.terminal import Event
from lup.types import Model, MutableModel


class Heard(Model):
    """One hook, as the host reads it."""

    event: Event
    session: str
    """The runtime's id for the session."""
    agent: str | None = None
    """The runtime's id for the subagent whose conversation it is; none for the
    session's own."""
    call: str | None = None
    """The call's id, at a call's start or finish."""
    tool: str | None = None
    """The tool called, by the runtime's name for it."""
    judged: bool
    """Whether the launch's judge reads it; one it doesn't is answered without
    starting the judge."""


class Telling(Model):
    """What the service adds to a hook's answer."""

    caller: str
    """lup's id for the conversation the hook is of, which a call to lup's tools
    is rewritten to carry."""
    items: list[str] = []
    """What the conversation is told at this hook, each whole, oldest first: as
    context beside the call or the session's start, or as the reason its turn's
    end is held. When to tell what is the inbox's; none adds nothing."""


class Courier(ABC):
    """What the host service reads of each runtime's hooks, and how it adds to their answers."""

    @abstractmethod
    def heard(self, runtime: str, payload: str) -> Heard:
        """Read one of `runtime`'s hooks.

        Raise `ValueError` where the payload doesn't read as one of its hooks.
        """

    @abstractmethod
    def told(self, runtime: str, payload: str, answer: str, telling: Telling) -> str:
        """Return what one of `runtime`'s hooks prints: `answer`, the judge's or none, with `telling` added.

        An answer the service gives itself is what the runtime takes as no
        decision, plus what `telling` adds; it never blocks a call. Raise
        `ValueError` where the payload, or the answer, doesn't read as the
        runtime's.
        """


class Conversation(Model):
    """A conversation of a launch's session: lup's id for it, and the runtime's ids it stands for."""

    id: str
    session: str
    """The runtime's id for the session."""
    agent: str | None = None
    """The runtime's id for the subagent; none for the session's own conversation."""


class Conversations(MutableModel):
    """lup's id for each conversation a launch's hooks have named, minted the first time each is named."""

    known: list[Conversation] = []
    session: str | None = None
    """The session the latest hook named: its own conversation is the launch's
    main one."""

    def named(self, session: str, agent: str | None) -> Conversation:
        """Return the conversation `session` and `agent` name, minting its id the first time."""
        self.session = session
        found = [
            each
            for each in self.known
            if each.session == session and each.agent == agent
        ]
        if found:
            return found[0]
        minted = Conversation(id=secrets.token_hex(8), session=session, agent=agent)
        self.known.append(minted)
        return minted

    def calling(self, caller: str) -> Conversation | None:
        """Return the conversation whose id is `caller`; none where no hook minted it."""
        found = [each for each in self.known if each.id == caller]
        return found[0] if found else None

    def main(self) -> Conversation | None:
        """Return the launch's main conversation, its latest session's own; none before any hook named one."""
        if self.session is None:
            return None
        return self.named(self.session, None)
