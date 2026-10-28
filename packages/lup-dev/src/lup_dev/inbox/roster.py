"""How lup names a conversation to the operator and to other agents: by the name it chose or was given, its runtime's ids beside it only where another shares the name, or alone where it has none.

`docs/launch.md`, *Names*. A conversation's name is its path, as lup's commands
call it (`dev/explore-auth`): its session's name, its launch's as lup last kept
it for the session (`SessionNames`, `host/names.py`), then each subagent's own
name down to it, as its whereabouts last heard it (`Whereabouts.name`), or, from
before they kept one, as its end was told to its parent (`Ended.name`); a
subagent with none by its runtime's id. That's how a tag says whom an item is
from, how `inbox` lists it, and how the dashboard and `lup-dev inbox` show it to
the operator, so an agent is talked to and of by the name they took.

Names repeat over time, a branch's above all, and a session cleared in its
launch keeps the launch's name, so where another conversation of the same
repository has the same path, its runtime's ids go beside the name; and a
conversation whose session's name lup never kept is named by those ids alone
(`ids`). The ids never change as a conversation is renamed, so they're what
reads one where its name doesn't (`handle`).
"""

from itertools import groupby
from pathlib import Path
from typing import TYPE_CHECKING

from lup.types import MutableModel
from lup_dev.inbox.store import Conversation, Ended, Item, Operator, Whereabouts

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lup_dev.inbox.store import Party


def ids(conversation: Conversation) -> str:
    """Name a conversation by its runtime's ids, which never change as it's renamed.

    >>> main = Conversation(repository=Path("/r/.git"), runtime="rt", session="s1")
    >>> ids(main), ids(main.model_copy(update={"agent": "a1"}))
    ('rt session s1', 'subagent a1 of rt session s1')
    """
    session = f"{conversation.runtime} session {conversation.session}"
    if conversation.agent is None:
        return session
    return f"subagent {conversation.agent} of {session}"


class Roster(MutableModel):
    """The conversations the inbox knows, each by the name lup calls it: its path, with its runtime's ids where another of its repository has the same path, or those ids alone where it has none.

    Made from the inbox as it stands (`Delivery.roster`), and read as often as
    a party is named while it does: what it finds, each repository's paths
    and the names told at subagents' ends, it keeps for its next reading.
    """

    names: dict[str, str]
    """Each session's name, by its runtime's id for it: its launch's, as lup
    last kept it (`Names.all`)."""
    places: dict[str, Whereabouts]
    """Each conversation's whereabouts, by its key, as the inbox holds them."""
    items: dict[int, Item]
    """Every item the inbox holds, by number: a subagent's end among them says
    its name, from before whereabouts kept one."""
    version: int = 0
    """The inbox's version it was made from (`Inbox.version`)."""
    told: dict[str, str] | None = None
    """The name each subagent's end was told with, by its conversation's key,
    the latest where it ended more than once; none until it's first read."""
    known: dict[Path, dict[str, list[Conversation]]] = {}
    """By repository, the conversations of it the inbox knows, by their paths,
    as far as they've been read."""

    def own(self, conversation: Conversation) -> str | None:
        """Return a conversation's own name: a session's as lup last kept it; a subagent's as its whereabouts last heard it, else as its end was told; none where lup knows none."""
        if conversation.agent is None:
            return self.names.get(conversation.session)
        place = self.places.get(conversation.key())
        if place is not None and place.name is not None:
            return place.name
        return self.ended().get(conversation.key())

    def ended(self) -> dict[str, str]:
        """Return the name each subagent's end was told with, by its conversation's key, the latest where it ended more than once."""
        if self.told is None:
            self.told = {
                item.sender.key(): item.reason.name
                for _, item in sorted(self.items.items())
                if isinstance(item.reason, Ended)
                and isinstance(item.sender, Conversation)
            }
        return self.told

    def parent(self, conversation: Conversation) -> Conversation | None:
        """Return the conversation that spawned a subagent, as its whereabouts keep it; none for a session's own, or one whose parent isn't known."""
        place = self.places.get(conversation.key())
        return None if place is None else place.parent

    def path(self, conversation: Conversation, depth: int = 0) -> str | None:
        """Return a conversation's path as lup's commands call it: its session's name, then each subagent's name down to it, an unnamed one by its runtime's id; none where its session's name isn't known."""
        if conversation.agent is None:
            return self.own(conversation)
        if depth > len(self.places):
            return None
        above = self.parent(conversation) or conversation.main()
        root = self.path(above, depth + 1)
        if root is None:
            return None
        return f"{root}/{self.own(conversation) or conversation.agent}"

    def alike(
        self, conversation: Conversation, also: Sequence[Conversation] = ()
    ) -> list[Conversation]:
        """Return the other conversations of `conversation`'s repository that have its path: those the inbox knows, and those of `also`, such as a session starting, which it hasn't heard yet; none where it has none."""
        path = self.path(conversation)
        if path is None:
            return []
        known = self.indexed(conversation.repository).get(path, [])
        starting = [
            each
            for each in also
            if each.repository == conversation.repository and self.path(each) == path
        ]
        return [
            each for each in dict.fromkeys([*known, *starting]) if each != conversation
        ]

    def indexed(self, repository: Path) -> dict[str, list[Conversation]]:
        """Return the conversations of `repository` the inbox knows, by their paths: each whose whereabouts it keeps, and each an item is from, for or was addressed to."""
        if repository not in self.known:
            parties = [
                each
                for item in self.items.values()
                for each in [item.sender, item.recipient, item.addressed]
                if isinstance(each, Conversation) and each.repository == repository
            ]
            placed = [
                place.conversation
                for place in self.places.values()
                if place.conversation.repository == repository
            ]
            pathed = sorted(
                (
                    (path, each)
                    for each in dict.fromkeys([*placed, *parties])
                    if (path := self.path(each)) is not None
                ),
                key=lambda pair: pair[0],
            )
            index = {
                path: [each for _, each in group]
                for path, group in groupby(pathed, key=lambda pair: pair[0])
            }
            self.known = {**self.known, repository: index}
        return self.known[repository]

    def called(self, party: Party) -> str:
        """Name a party as a tag's attribute says it: `operator`; a conversation by its path, its runtime's ids in brackets after it where another of its repository has the same path; by its ids alone where it has none."""
        match party:
            case Operator():
                return "operator"
            case Conversation():
                path = self.path(party)
                if path is None:
                    return ids(party)
                return f"{path} ({ids(party)})" if self.alike(party) else path

    def who(self, party: Party, also: Sequence[Conversation] = ()) -> str:
        """Name a party in a sentence: the operator; a conversation as `called` names it, its path quoted, `also` among those that might share it (`alike`)."""
        match party:
            case Operator():
                return "the operator"
            case Conversation():
                path = self.path(party)
                if path is None:
                    return ids(party)
                if self.alike(party, also):
                    return f"`{path}` ({ids(party)})"
                return f"`{path}`"

    def handle(
        self, conversation: Conversation, also: Sequence[Conversation] = ()
    ) -> str:
        """Return what reads `conversation` where a call or a command names one, as `inbox`'s `conversation` takes it: its path, where no other of its repository has it, `also` among them (`alike`); else the runtime's id for it, which never changes."""
        path = self.path(conversation)
        if path is not None and not self.alike(conversation, also):
            return path
        return conversation.agent or conversation.session
