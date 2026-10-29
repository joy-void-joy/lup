"""What the host reads of each runtime's hooks, and how it answers them; lup's own id for each conversation.

`docs/host.md`, *Who's calling*, and `docs/inbox.md`, *How an agent is told*.
Every hook a launch's room sends reaches the host service, which hears
it through the `Courier` (`heard`): its event, the runtime's own ids for the
session and the conversation in it, its call and tool, and whether the launch's
judge reads it.
A hook the judge doesn't read the service answers itself, without asking the
launch's judge. Every answer, the judge's or the service's own, goes out through
the `Courier` again (`told`): with what the conversation is told added, and a call
to lup's tools rewritten to carry its `caller`, lup's id for the conversation.
Each runtime's adapter fills both, since only it knows its runtime's spelling;
`cli.py` builds the `Courier` from them, as it builds the `Answerer`. The
`Waker` spells how an idle session is woken, where its runtime has a way: what
lup's tool server pushes on the session's own connection (`pushed`), with the
capabilities it declares for the runtime to take it (`capabilities`), and the
line written to its messaging socket (`woken`).

What a conversation is told at each hook is the `Post`'s: the inbox's, which
`cli.py` hands the service too. It hears every hook, and returns what waits for
the conversation, counted told once the answer is written, and put back where it
couldn't be (`returned`).

lup's own id for each conversation (`Conversations`) is minted the first time a
hook names it (a session's start, a subagent's start, its first call), and kept
with the runtime's ids it stands for, so lup's tools and calls name a
conversation by lup's id, never a runtime's. A launch's ids are kept with it,
so a service started again reads them back and its hooks stamp the same ones,
while every MCP connection the service before held closed with it.
"""

import secrets
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Annotated

from lup.events import ByKind, SessionEvent
from lup.types import JsonObject, Model, MutableModel
from lup_dev.host.protocol import Activity

if TYPE_CHECKING:
    from lup.tools.serving import Notice
    from lup_dev.host.protocol import Register


class Failure(Model):
    """A turn's end on an error from the model's API, as its runtime reports it."""

    kind: str
    """The error's kind, in its runtime's word for it (`rate_limit`), which
    says whether trying again makes sense."""
    said: str | None = None
    """The runtime's text for it, as it shows it in the conversation; none where
    it gives none."""


class Heard(Model):
    """One hook, as the host reads it."""

    event: Annotated[SessionEvent, ByKind]
    """The event it's read as, which says the call and the tool at a call's
    start or finish (`lup.events`)."""
    session: str
    """The runtime's id for the session."""
    agent: str | None = None
    """The runtime's id for the subagent whose conversation it is; none for the
    session's own."""
    served: bool = False
    """At a call's start or finish, whether the call is to one of lup's tools,
    served on the launch's `mcp.sock`: its own result tells the conversation
    what waits, so its start doesn't, where what's told beside it would reach
    the model only once a held call returns; and a subagent's first one
    finishing says it has lup's tools (`invitation`)."""
    judged: bool
    """Whether the launch's judge reads it; one it doesn't is answered without
    starting the judge."""
    after_block: bool = False
    """At a turn's end, whether the turn went on because its end was held just
    before: an end that follows a hold is let through, whatever's still there
    (`docs/inbox.md`, *No turn that won't end*)."""
    fits: int
    """The most this hook's answer tells the model whole, in bytes of UTF-8: past
    it, the runtime keeps the text in a file the model isn't asked to read."""
    title: str | None = None
    """At a session's start or a prompt, the runtime's own title for the
    session, where it has one and says so: one the operator gave it there (a
    rename in the runtime), or one lup gave it; none otherwise."""
    fresh: bool = False
    """At a session's own start, whether its conversation starts empty: started
    anew or cleared, not resumed, compacted or forked, as both runtimes' start
    says (`docs/field-notes.md`, *A conversation resumed in a later launch*).
    A new main session is told where its repository stands then, and only
    then."""
    takes_title: bool = False
    """Whether the runtime takes a title for the session from this hook's
    answer (`Telling.title`): at the session's own start or prompt, where its
    runtime has a way. Where it doesn't, lup's name stays lup's, and the
    runtime's title its own."""
    said: str | None = None
    """At a turn's end, the agent's last message before it, as the runtime hands
    it to the hook; none for any other hook, or where it has none."""
    stopped: bool = False
    """At a subagent's end, whether it was stopped before it ended its turn,
    rather than ending it: told to its parent, and nothing it's told then holds
    it, since nothing would read it."""
    failed: Failure | None = None
    """At a turn's end, the session's or a subagent's, the error from the
    model's API it ended on; none where it ended otherwise. A subagent's kind
    is told to its parent, and a session's failure is put before the operator
    (`Post.failed`); nothing either is told then holds it, since its runtime
    reads no answer."""
    prompt: str | None = None
    """At a turn's start, the prompt it starts on, the operator's or one lup's
    tool server pushed; none for any other hook."""


class Telling(Model):
    """What the service adds to a hook's answer."""

    caller: str
    """lup's id for the conversation the hook is of, which a call to lup's tools
    is rewritten to carry."""
    items: list[str] = []
    """What the conversation is told at this hook, each whole, oldest first: as
    context beside the call or the session's start, or as the reason its turn's
    end is held. When to tell what is the inbox's; none adds nothing."""
    title: str | None = None
    """The title the runtime gives the session from now on, its launch's name,
    at a hook that takes one (`Heard.takes_title`) where the runtime's own
    differs; none leaves it."""


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


class Waker(ABC):
    """How each runtime's idle session is woken: what lup's tool server pushes to it and declares for it to be taken, and the line written to its messaging socket."""

    @abstractmethod
    def woken(self, runtime: str, session: str, text: str) -> str | None:
        """Return the line that starts a turn of `runtime`'s idle session `session` with `text`, written to its messaging socket.

        None where the runtime has no such socket, which its adapter declares.
        """

    @abstractmethod
    def pushed(self, runtime: str, text: str, token: str) -> Notice | None:
        """Return the notice lup's tool server sends to start a turn of `runtime`'s idle session with `text`, its prompt carrying `token` whole.

        None where the runtime takes nothing a server pushes, which its adapter
        declares.
        """

    @abstractmethod
    def capabilities(self, runtime: str) -> dict[str, JsonObject]:
        """Return the experimental capabilities lup's tool server declares to `runtime`, so it takes what the server pushes; none where it takes nothing."""


class Spawns(ABC):
    """How each runtime recorded its subagents' spawns, which the host service reads once a subagent's first hook is heard."""

    @abstractmethod
    def spawned(self, launch: Register, payload: str) -> Spawned | None:
        """Return how the subagent one of `launch`'s hooks fires for was spawned, as its runtime recorded it; none for the session's own conversation, or where nothing's recorded.

        `launch` is the one the service heard the hook from: a record the
        payload names is read only inside its own runtime directory, in the
        home it registered (`lup_dev.host.homes.translated`).
        """


class Posted(Model):
    """What a conversation is told at one hook: each item's text, and the numbers of the items it tells."""

    items: list[str] = []
    """Each item's text, oldest first, or the line announcing one too long to
    tell here."""
    numbers: list[int] = []
    """The items told or announced here, by number: put back as waiting where the
    hook's answer couldn't be written."""


class Post(ABC):
    """What a launch's conversations are told at their hooks: what waits for each in its inbox.

    `cli.py` hands the service the inbox's, as it hands it the courier, so the
    service imports no module's code.
    """

    @abstractmethod
    async def telling(
        self,
        launch: Register,
        conversation: Conversation,
        parent: Conversation | None,
        heard: Heard,
        room: int,
    ) -> Posted:
        """Note the hook `heard`, and return what `conversation` of `launch` is told in its answer, in `room` bytes at most.

        `parent` is the conversation that spawned it, for a subagent a
        conversation spawned; none for a session's own. The runtime's own
        agents (`Spawned.internal`) are never told anything, so it isn't asked
        of them. What's returned is counted told, unless it's put back
        (`returned`).
        """

    @abstractmethod
    def returned(self, posted: Posted) -> None:
        """Put what `posted` told back as waiting: the hook's answer couldn't carry it."""

    @abstractmethod
    async def concluded(
        self, launch: Register, conversation: Conversation, heard: Heard
    ) -> None:
        """Put a turn's end of `conversation` of `launch`, a session's own, before the operator, held or let through, as `heard` says it: its last message, or the error from the model's API it ended on; nothing where it says neither."""


class Spawned(Model):
    """How a subagent was spawned, as its runtime recorded it, read at its first hook."""

    name: str | None = None
    """The name its parent gave it, where it gave one."""
    parent: str | None = None
    """The runtime's id for the subagent that spawned it; none where the
    session's own conversation did, or where the runtime doesn't say."""
    kind: str | None = None
    """What kind of subagent it is, as its runtime calls it (`Explore`)."""
    guided: bool = False
    """Whether it reads its session's guidance, as the session's own
    conversation does: its runtime gives the guidance to every thread it
    spawns, or it was spawned with its parent's own prompt."""
    internal: bool = False
    """Whether it's one of the runtime's own agents, run for its own features
    (suggesting the operator's next prompt, answering a side question,
    summarizing a subagent's progress), which no spawn in the session's record
    links to: no subagent of the operator's, so lup shows it nowhere, no parent
    hears of its end, and its hooks are answered with nothing, judged by no
    one. Each adapter says how its runtime tells them apart."""
    handed: bool = False
    """Whether its runtime hands its last message to the conversation that
    spawned it itself, so lup's word of its end leaves the message out rather
    than tell it twice."""


class Conversation(Model):
    """A conversation of a launch's session: lup's id for it, the runtime's ids it stands for, and for a subagent its name, its parent and its kind."""

    id: str
    session: str
    """The runtime's id for the session."""
    agent: str | None = None
    """The runtime's id for the subagent; none for the session's own conversation."""
    name: str | None = None
    """A subagent's name, as its parent gave it at its spawn or it renamed
    itself since; none while it has none, and for the session's own
    conversation, which is named as its launch."""
    parent: str | None = None
    """lup's id for the conversation that spawned a subagent; none for the
    session's own, and where it isn't known."""
    kind: str | None = None
    """What kind of subagent it is (`Explore`)."""
    internal: bool = False
    """Whether it's one of the runtime's own agents, which no conversation
    spawned (`Spawned.internal`): kept so its later hooks find it linked, and
    left out of what the operator is shown (`Launches.talkers`)."""
    handed: bool = False
    """Whether its runtime hands its last message to its parent itself
    (`Spawned.handed`)."""
    linked: bool = False
    """Whether what its runtime recorded of its spawn was read."""
    introduced: bool = False
    """Whether a subagent knows the tools lup serves it: told them once, or
    reading the guidance that lists them to its session (`Spawned.guided`)."""
    invited: bool = False
    """Whether a subagent was invited to say how the work is for it, which lup
    does once, beside its first finished call to lup's tools (`invitation`)."""
    holding: bool = False
    """Whether the operator holds each flagged write of it: their switch, "hold
    each flagged write", which the judge asks (`ShowHolding`)."""

    def own(self, launch: str) -> str:
        """Say its own part of its path: its launch's name, `launch`, for the session's own; a subagent's name; an unnamed one by its kind and its runtime's id."""
        if self.agent is None:
            return launch
        return self.name or f"{self.kind or 'subagent'}·{self.agent}"


class Conversations(MutableModel):
    """lup's id for each conversation a launch's hooks have named, minted the first time each is named."""

    known: list[Conversation] = []
    session: str | None = None
    """The session the latest hook named: its own conversation is the launch's
    main one."""
    activities: dict[str, Activity] = {}
    """By lup's id for each conversation, what its latest hook said it's doing,
    and since when: kept with the rest, so a service started again knows it."""

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

    def kept(self, conversation: Conversation) -> Conversation:
        """Keep `conversation` in place of the one with its id, and return it."""
        self.known = [
            conversation if each.id == conversation.id else each for each in self.known
        ]
        return conversation

    def linked(
        self, conversation: Conversation, spawned: Spawned | None
    ) -> Conversation:
        """Link a subagent to its spawn as its runtime recorded it, and return it: its name, its parent, its kind, whether it's the runtime's own, whether its runtime hands its last message to its parent, and whether the guidance tells it lup's tools.

        Its parent is the subagent the runtime names, else the session's own
        conversation.
        """
        above = None if spawned is None else spawned.parent
        parent = self.named(conversation.session, above)
        guided = spawned is not None and spawned.guided
        return self.kept(
            conversation.model_copy(
                update={
                    "name": None if spawned is None else spawned.name,
                    "parent": parent.id,
                    "kind": None if spawned is None else spawned.kind,
                    "internal": spawned is not None and spawned.internal,
                    "handed": spawned is not None and spawned.handed,
                    "linked": True,
                    "introduced": conversation.introduced or guided,
                }
            )
        )

    def spawner(self, conversation: Conversation) -> Conversation | None:
        """Return the conversation that spawned `conversation`, a subagent a conversation spawned, which hears of its end; none for a session's own, the runtime's own agents, and one whose parent no hook named."""
        if conversation.parent is None or conversation.internal:
            return None
        return self.calling(conversation.parent)

    def path(self, conversation: Conversation, launch: str) -> str:
        """Say a conversation as people call it: its launch's name, then each subagent's name down to it, an unnamed one by its kind and its runtime's id."""
        if conversation.agent is None:
            return launch
        parent = (
            None if conversation.parent is None else self.calling(conversation.parent)
        )
        above = launch if parent is None else self.path(parent, launch)
        return f"{above}/{conversation.own(launch)}"

    def holder(self, name: str, asking: str) -> Conversation | None:
        """Return the subagent other than `asking` named `name` in this launch, or none."""
        return next(
            (
                each
                for each in self.known
                if each.agent is not None and each.name == name and each.id != asking
            ),
            None,
        )

    def main(self) -> Conversation | None:
        """Return the launch's main conversation, its latest session's own; none before any hook named one."""
        if self.session is None:
            return None
        return self.named(self.session, None)
