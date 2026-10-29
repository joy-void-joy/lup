"""The inbox's files and the review marks' files of an earlier lup, each converted once onto the ledger, and the check of a conversion the operator runs on the host.

`docs/inbox.md`, *Kept on the ledger*. Before the ledger, the inbox kept one JSON
file per item, per conversation's whereabouts, per diff and per changed files,
and one each for the draft, the review's order and what the operator wrote on
each conversation, under `$XDG_STATE_HOME/lup/inbox/` (`InboxLayout`). The host
service converts them the first time it starts on a ledger holding no item
(`converted`), in one transaction: every file read, or nothing kept and the
service refusing to start, naming the file that doesn't read. Each item keeps
its number, the sequence moving past the last; each is one version, at when it
was made or last edited, its links drawn from its fields as every version's
are (`Inbox.linked`), and where it stands an edge. The files are left as they
were, a backup.

The review marks were a file of each module's per repository
(`MarksLayout`), each module's latest mark of each key. The host service
converts them the first time it starts on a ledger holding no mark
(`marks_converted`), in one transaction, each mark an edge the operator drew at
the time it says (`lup_dev.inbox.marks`), where its repository is one lup knows
by its git directory; the judge's marks of each branch from before the files
held them carried in first, where its file says it never carried them
(`Carrying`). A file of a repository lup knows no name of, whose directory is
named by its digest, is left where it is, and said.

`rehearsed` runs the inbox's conversion into a scratch ledger and compares it
with the files, item by item and field by field, timing the conversion and a
hook's lookups on it; `marks_rehearsed` does the same for the review marks. Each
says counts, times and what differs by item number, or by repository, module
and mark, and field, never what an item says or what a mark is on, so the
operator can run it on their own store and pass on what it says.
"""

import statistics
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from lup.types import Model
from lup_dev.inbox.marks import MarksFile, MarkStore, ReviewMark, keyed
from lup_dev.inbox.store import (
    KINDS,
    ORDER,
    Draft,
    Inbox,
    InboxError,
    Item,
    ItemNode,
    Order,
    Stands,
    Talk,
    Told,
    Waiting,
    Whereabouts,
    linking,
    named,
    stands,
    talked_on,
)
from lup_dev.listing import many
from lup_dev.stored import read_model, write_model
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.records import Edge

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import datetime

    from lup_dev.layout import InboxLayout, Layout


def read[M: Model](path: Path, model: type[M]) -> M:
    """Read one of the inbox's files as `model`, naming it where it doesn't read."""
    try:
        found = read_model(path, model)
    except (OSError, ValidationError) as unread:
        message = f"the inbox's {path} doesn't read: {unread}"
        raise InboxError(message) from unread
    if found is None:
        message = f"the inbox's {path} is gone"
        raise InboxError(message)
    return found


class Files(Model):
    """The inbox's files, read: what a conversion keeps on the ledger."""

    items: list[Item]
    """By number."""
    places: list[Whereabouts]
    """In the order each conversation was first heard."""
    talks: dict[str, Talk]
    """By the key of the conversation they're on."""
    draft: Draft | None
    order: Order | None
    diffs: dict[int, Path]
    """Each diff's file, by its item's number: copied as it is, read only on request."""
    changed: dict[int, Path]
    """Each file of the files a change touches, by its item's number."""

    @classmethod
    def read(cls, layout: InboxLayout) -> Files:
        """Read the inbox's files at `layout`; none there reads as an empty inbox.

        Raise `InboxError` naming a file that doesn't read: an item, a
        conversation's whereabouts, the draft, the order or a talk. A diff and
        a change's files are copied unread, as the inbox read them only on
        request.
        """
        items = [read(path, Item) for path in layout.items.glob("*.json")]
        places = [read(path, Whereabouts) for path in layout.parties.glob("*.json")]
        return cls(
            items=sorted(items, key=lambda each: each.number),
            places=sorted(
                places, key=lambda each: (each.since, each.conversation.key())
            ),
            talks={path.stem: read(path, Talk) for path in layout.talks.glob("*.json")},
            draft=read(layout.draft, Draft) if layout.draft.is_file() else None,
            order=read(layout.order, Order) if layout.order.is_file() else None,
            diffs={int(path.stem): path for path in layout.diffs.glob("*.json")},
            changed={int(path.stem): path for path in layout.files.glob("*.json")},
        )


class Converted(Model):
    """What a conversion kept on the ledger: how many of each."""

    items: int
    conversations: int
    states: int
    """Edges saying where an item stands, one for each item not waiting."""
    links: int
    """Edges drawn from an item's fields: what it answers, replies to, cites."""
    attachments: int
    """Diffs and changes' files attached."""
    talks: int
    nowhere: int
    """Items of no repository, between the operator and themselves about none, kept under `/`."""

    def said(self) -> str:
        """Say it in a line, as the host service tells the operator.

        >>> print(Converted(items=2, conversations=1, states=1, links=0, attachments=0, talks=0, nowhere=0).said())
        2 items, 1 conversation, 1 edge of where an item stands, 0 links, 0 attachments, 0 talks
        """
        nowhere = (
            ""
            if not self.nowhere
            else f"; {many(self.nowhere, 'item')} of no repository, kept under /"
        )
        return (
            f"{many(self.items, 'item')}, {many(self.conversations, 'conversation')}, "
            f"{self.states} edge{'' if self.states == 1 else 's'} of where an item "
            f"stands, {many(self.links, 'link')}, "
            f"{many(self.attachments, 'attachment')}, {many(self.talks, 'talk')}"
            f"{nowhere}"
        )


def converted(ledger: Ledger, layout: InboxLayout) -> Converted | None:
    """Convert the inbox's files at `layout` onto `ledger`, where it keeps no item, and say what it kept; none where it keeps items already, so it runs once.

    One transaction: where a file doesn't read, or the ledger refuses a record,
    nothing is kept, and `InboxError` or `LupLedgerError` says why. The files
    are left as they were.
    """
    if ledger.keeps(ItemNode):
        return None
    return conversion(ledger, Files.read(layout))


def first(item: Item) -> datetime:
    """Return when `item`'s one version on the ledger is at: when it was made, or its last edit, after which what it says is as its file keeps it."""
    return max([item.made, *(each.at for each in item.edits)])


def conversion(ledger: Ledger, files: Files) -> Converted:
    """Keep `files` on `ledger`, in one transaction, and say what was kept.

    Every item first, each its one version and its attachments, so each link
    and each state naming another finds it there; then the links each item's
    fields say (`Inbox.linked`, the one place they're drawn), where it stands,
    and the plain records: each conversation's whereabouts, the draft, the
    order and each talk.
    """
    inbox = Inbox(ledger=ledger, marks=MarkStore(ledger=ledger))

    def attachments(item: Item) -> dict[str, str]:
        diff = files.diffs.get(item.number)
        changed = files.changed.get(item.number)
        return {
            **({} if diff is None else {"diff": ledger.attached(diff.read_bytes())}),
            **(
                {}
                if changed is None
                else {"files": ledger.attached(changed.read_bytes())}
            ),
        }

    with ledger.writing():
        nodes = [
            ledger.kept(
                ItemNode.of(item, first(item)).model_copy(update=attachments(item))
            )
            for item in files.items
        ]
        links = len(ledger.drawn_of(Edge))
        for node in nodes:
            inbox.linked(node)
        links = len(ledger.drawn_of(Edge)) - links
        standing = [item for item in files.items if item.state != Waiting()]
        for item in standing:
            ledger.drawn(stands(item, inbox.source(item, named(item.state))))
        for place in files.places:
            inbox.placed(place)
        if files.draft is not None:
            inbox.drafted(files.draft)
        if files.order is not None:
            ledger.rewritten(ORDER, files.order)
        for key, talk in files.talks.items():
            ledger.rewritten(talked_on(key), talk)
    return Converted(
        items=len(nodes),
        conversations=len(files.places),
        states=len(standing),
        links=links,
        attachments=len([each for each in nodes if each.diff])
        + len([each for each in nodes if each.files]),
        talks=len(files.talks),
        nowhere=len([each for each in nodes if each.repository == Path("/")]),
    )


class Differs(Model):
    """What a check found differing: an item's number, or a conversation's key's start, and the field."""

    of: str
    field: str


class Timing(Model):
    """How long a check took, at its median and its 90th percentile, in milliseconds."""

    median: float
    p90: float

    @classmethod
    def of(cls, seconds: list[float]) -> Timing:
        """Return the timing of each run, `seconds` long."""
        ordered = sorted(seconds)
        return cls(
            median=statistics.median(ordered) * 1000,
            p90=ordered[int(len(ordered) * 0.9)] * 1000,
        )

    def said(self) -> str:
        """Say it: `0.42 ms (p90 0.51 ms)`."""
        return f"{self.median:.2f} ms (p90 {self.p90:.2f} ms)"


class Rehearsal(Model):
    """What a check of the conversion found: what it read and kept, how long each part took, and what differs."""

    read: float
    """Reading the files, in seconds: what the inbox did at its start."""
    converted: Converted
    conversion: float
    """Converting them onto the scratch ledger, in seconds."""
    opened: float
    """Opening the inbox from the ledger, in seconds: what the host service does at its start."""
    waiting: Timing
    """Each conversation's items waiting, as every hook asks."""
    told_file: Timing
    """An item told, written whole as a file, as the inbox did."""
    told_ledger: Timing
    """An item told, an edge drawn on the ledger."""
    edited_file: Timing
    """A change to what an item says, written whole as a file."""
    edited_ledger: Timing
    """A change to what an item says, a version kept on the ledger."""
    unlinked: int
    """Links an item's fields name that aren't drawn: their item isn't on the
    ledger, or is another repository's."""
    differs: list[Differs]

    def said(self) -> list[str]:
        """Say it, a line each: counts, times and what differs by item number and field, never what an item says."""
        differs = (
            [
                "Every item, state, link, version, conversation, attachment, talk, the draft and the order read alike."
            ]
            if not self.differs
            else [
                f"{many(len(self.differs), 'difference')}:",
                *(f"  {each.of}: {each.field}" for each in self.differs),
            ]
        )
        return [
            f"Read the files in {self.read:.2f}s.",
            f"Converted them in {self.conversion:.2f}s: {self.converted.said()}.",
            f"Opened the inbox from the ledger in {self.opened:.2f}s.",
            f"Links a field names that aren't drawn, their item not on the ledger or another repository's: {self.unlinked}.",
            f"A hook's lookup of what waits for a conversation: {self.waiting.said()}.",
            f"An item told: {self.told_ledger.said()} on the ledger, {self.told_file.said()} as a file.",
            f"An item changed: {self.edited_ledger.said()} on the ledger, {self.edited_file.said()} as a file.",
            *differs,
        ]


def compared(inbox: Inbox, files: Files) -> list[Differs]:
    """Return what differs between `inbox`, converted onto its ledger, and `files`: each item's fields, where it stands among them, its versions, its links and its attachments; each conversation's whereabouts; each talk, the draft and the order."""
    ledger = inbox.ledger
    numbers = [each.number for each in files.items]

    def item(stored: Item) -> list[Differs]:
        held = inbox.items.get(stored.number)
        if held is None:
            return [Differs(of=f"@{stored.number}", field="missing")]
        node = ledger.node(stored.number, ItemNode)
        drawn = sorted(
            linking(each)
            for each in ledger.drawn_from(stored.number, Edge, current=True)
            if not isinstance(each, Stands)
        )
        wanted = sorted(
            linking(each)
            for each in node.links(1)
            if (found := ledger.found(each.target)) is not None
            and found.repository == node.repository
        )
        diff = files.diffs.get(stored.number)
        changed = files.changed.get(stored.number)
        attached = [
            *(
                []
                if diff is None
                or node.diff is None
                or ledger.attachment(node.diff) != diff.read_bytes()
                else ["diff"]
            ),
            *(
                []
                if changed is None
                or node.files is None
                or ledger.attachment(node.files) != changed.read_bytes()
                else ["files"]
            ),
        ]
        return [
            *(
                Differs(of=f"@{stored.number}", field=field)
                for field in Item.model_fields
                if getattr(held, field) != getattr(stored, field)
            ),
            *(
                [Differs(of=f"@{stored.number}", field="versions")]
                if len(ledger.versions(stored.number)) != 1
                else []
            ),
            *(
                [Differs(of=f"@{stored.number}", field="links")]
                if drawn != wanted
                else []
            ),
            *(
                Differs(of=f"@{stored.number}", field=each)
                for each in ["diff", "files"]
                if each not in attached
                and (diff if each == "diff" else changed) is not None
            ),
        ]

    def place(stored: Whereabouts) -> list[Differs]:
        key = stored.conversation.key()
        held = inbox.whereabouts.get(key)
        if held is None:
            return [Differs(of=f"conversation {key}", field="missing")]
        return [
            Differs(of=f"conversation {key}", field=field)
            for field in Whereabouts.model_fields
            if getattr(held, field) != getattr(stored, field)
        ]

    talks = [
        Differs(of=f"talk {key}", field="talk")
        for key, talk in files.talks.items()
        if ledger.plain(talked_on(key), Talk) != talk
    ]
    return [
        *(each for stored in files.items for each in item(stored)),
        *(
            Differs(of=f"@{each}", field="extra")
            for each in inbox.items
            if each not in numbers
        ),
        *(each for stored in files.places for each in place(stored)),
        *(
            [Differs(of="conversations", field="extra")]
            if len(inbox.whereabouts) != len(files.places)
            else []
        ),
        *talks,
        *(
            [Differs(of="draft", field="draft")]
            if files.draft is not None and inbox.draft() != files.draft
            else []
        ),
        *(
            [Differs(of="order", field="order")]
            if files.order is not None and inbox.order() != files.order
            else []
        ),
    ]


def timed[T](action: Callable[[], T], runs: int) -> Timing:
    """Run `action` `runs` times, and return how long each took."""

    def once() -> float:
        started = time.perf_counter()
        action()
        return time.perf_counter() - started

    return Timing.of([once() for _ in range(runs)])


def unlinked(ledger: Ledger) -> int:
    """Count the links the items on `ledger` name in their fields that no edge is drawn for: their item isn't on the ledger, or is another repository's."""

    def drawable(node: ItemNode, edge: Edge) -> bool:
        found = ledger.found(edge.target)
        return found is not None and found.repository == node.repository

    return sum(
        1
        for node in ledger.every(ItemNode)
        for edge in node.links(1)
        if not drawable(node, edge)
    )


class Writes(Model):
    """A write each way, timed: an item told, and a change to what it says, as a file and on the ledger."""

    told_file: Timing
    told_ledger: Timing
    edited_file: Timing
    edited_ledger: Timing


def writes(inbox: Inbox, item: Item, copies: Path) -> Writes:
    """Time writing `item` told, and changed, each way: whole as a file under `copies`, as the inbox did, and on `inbox`'s ledger, alternating its state with waiting so each write is one."""
    told = Told(at=item.made, how="call")
    turns = iter(range(1_000_000))

    def told_ledger() -> None:
        held = inbox.items[item.number]
        state = Waiting() if isinstance(held.state, Told) else told
        inbox.kept(held.model_copy(update={"state": state}))

    def edited_ledger() -> None:
        held = inbox.items[item.number]
        inbox.kept(held.model_copy(update={"call": f"timed {next(turns)}"}))

    copies.mkdir(parents=True, exist_ok=True)
    copy = copies / f"{item.number}.json"
    return Writes(
        told_file=timed(
            lambda: write_model(copy, item.model_copy(update={"state": told})), 100
        ),
        told_ledger=timed(told_ledger, 100),
        edited_file=timed(
            lambda: write_model(
                copy, item.model_copy(update={"call": f"timed {next(turns)}"})
            ),
            100,
        ),
        edited_ledger=timed(edited_ledger, 100),
    )


def rehearsed(layout: InboxLayout, scratch: Path | None = None) -> Rehearsal:
    """Convert the inbox's files at `layout`, read alone, into a scratch ledger at `scratch`, or a temporary directory removed after, and compare them; time the conversion, the inbox's opening, a hook's lookup, and a write each way.

    The writes are timed on the scratch ledger and on copies under it, never
    on the files at `layout`. Raise `InboxError` where the inbox holds no item
    to time them on.
    """
    if scratch is None:
        with tempfile.TemporaryDirectory() as temporary:
            return rehearsed(layout, Path(temporary))
    started = time.perf_counter()
    files = Files.read(layout)
    reading = time.perf_counter() - started
    if not files.items or not files.places:
        message = f"the inbox at {layout.home} holds no item, or no conversation"
        raise InboxError(message)
    ledger = Ledger.opened(LedgerLayout(home=scratch / "ledger"), KINDS)
    try:
        started = time.perf_counter()
        kept = conversion(ledger, files)
        converting = time.perf_counter() - started
        started = time.perf_counter()
        inbox = Inbox.opened(ledger)
        opening = time.perf_counter() - started
        differs = compared(inbox, files)
        parties = [each.conversation for each in files.places]
        turns = iter(range(1_000_000))
        waiting = timed(lambda: inbox.waiting(parties[next(turns) % len(parties)]), 200)
        timings = writes(inbox, files.items[-1], scratch / "files")
        return Rehearsal(
            read=reading,
            converted=kept,
            conversion=converting,
            opened=opening,
            waiting=waiting,
            told_file=timings.told_file,
            told_ledger=timings.told_ledger,
            edited_file=timings.edited_file,
            edited_ledger=timings.edited_ledger,
            unlinked=unlinked(ledger),
            differs=differs,
        )
    finally:
        ledger.close()


class Carrying(Model):
    """An older store of one module's marks, which its marks file carries in once, where the file says it never did (`MarksFile.carried`): the judge's marks of each branch from before the files held them."""

    module: str
    name: str
    """As `MarksFile.carried` records it."""
    read: Callable[[Path], list[ReviewMark]]
    """Its marks of a repository, by the repository's git directory."""


class MarkFiles(Model):
    """The review marks' files of an earlier lup, read: what a conversion keeps on the ledger."""

    kept: dict[Path, list[MarksFile]]
    """Each module's file of each repository lup knows, by its git directory,
    with the older stores each carries in."""
    carried: int
    """How many marks of an older store were carried in."""
    unnamed: list[Path]
    """Each file of a repository lup knows no name of, left as it is."""

    @classmethod
    def read(
        cls, layout: Layout, repositories: Collection[Path], carrying: list[Carrying]
    ) -> MarkFiles:
        """Read the marks' files lup's state at `layout` keeps of each of `repositories`, each older store of `carrying` carried in where its module's file never did; and list those of any other repository.

        Raise `InboxError` naming a file that doesn't read.
        """

        def carried(repository: Path, files: list[MarksFile]) -> list[MarksFile]:
            def one(file: MarksFile, carry: Carrying) -> MarksFile:
                if file.module != carry.module or carry.name in file.carried:
                    return file
                ours = {keyed(each.key): each for each in file.marks}
                theirs = [
                    each
                    for each in carry.read(repository)
                    if keyed(each.key) not in ours
                ]
                return MarksFile(
                    module=file.module,
                    marks=[*theirs, *file.marks],
                    carried=[*file.carried, carry.name],
                )

            modules = [each.module for each in files]
            missing = {
                each.module: MarksFile(module=each.module)
                for each in carrying
                if each.module not in modules
            }
            found = [*files, *missing.values()]
            for carry in carrying:
                found = [one(each, carry) for each in found]
            return [each for each in found if each.marks]

        named = {layout.marks(each).home: each for each in repositories}
        read_files = {
            repository: [
                read(path, MarksFile) for path in layout.marks(repository).modules()
            ]
            for repository in repositories
        }
        kept = {
            repository: carried(repository, files)
            for repository, files in read_files.items()
        }
        before = sum(len(each.marks) for files in read_files.values() for each in files)
        after = sum(len(each.marks) for files in kept.values() for each in files)
        return cls(
            kept={repository: files for repository, files in kept.items() if files},
            carried=after - before,
            unnamed=[
                path
                for marks in layout.every_marks()
                if marks.home not in named
                for path in marks.modules()
            ],
        )


class MarksConverted(Model):
    """What a conversion of the review marks kept on the ledger: how many of each."""

    repositories: int
    modules: int
    marks: int
    carried: int
    """Marks carried in from an older store, among `marks`."""
    unnamed: int
    """Files of a repository lup knows no name of, left as they are."""

    def said(self) -> str:
        """Say it in a line, as the host service tells the operator.

        >>> print(MarksConverted(repositories=1, modules=2, marks=3, carried=0, unnamed=1).said())
        3 marks of 2 modules in 1 repository; 1 file of a repository lup knows no name of left as it is
        """
        unnamed = (
            ""
            if not self.unnamed
            else f"; {many(self.unnamed, 'file')} of a repository lup knows no "
            f"name of left as {'it is' if self.unnamed == 1 else 'they are'}"
        )
        carried = (
            ""
            if not self.carried
            else f", {self.carried} of them carried in from the judge's older store,"
        )
        repositories = (
            "1 repository"
            if self.repositories == 1
            else f"{self.repositories} repositories"
        )
        return (
            f"{many(self.marks, 'mark')}{carried} of {many(self.modules, 'module')} "
            f"in {repositories}{unnamed}"
        )


def marks_converted(store: MarkStore, files: MarkFiles) -> MarksConverted | None:
    """Keep the marks `files` read on the ledger `store` holds, where it keeps no mark, and say what it kept; none where it keeps marks already, so it runs once.

    One transaction: where the ledger refuses a mark, nothing is kept, and
    `HostError` says why. The files are left as they were.
    """
    if store.held or store.anchors:
        return None
    with store.ledger.writing():
        for repository, kept in files.kept.items():
            for each in kept:
                store.moved(repository, each.module, each.marks)
    return MarksConverted(
        repositories=len(files.kept),
        modules=sum(len(each) for each in files.kept.values()),
        marks=sum(len(each.marks) for kept in files.kept.values() for each in kept),
        carried=files.carried,
        unnamed=len(files.unnamed),
    )


class MarksRehearsal(Model):
    """What a check of the review marks' conversion found: what it read and kept, how long each part took, and what differs."""

    read: float
    """Reading the files, in seconds."""
    converted: MarksConverted
    conversion: float
    """Converting them onto the scratch ledger, in seconds."""
    opened: float
    """Reading every mark back from the ledger, in seconds: what the host service does at its start."""
    lookup: Timing
    """A module's mark on one key, as a view reads it."""
    moved_file: Timing
    """A mark moved, its module's file read and written whole, as an earlier lup did."""
    moved_ledger: Timing
    """A mark moved, an edge drawn on the ledger."""
    differs: list[Differs]

    def said(self) -> list[str]:
        """Say it, a line each: counts, times and what differs by repository, module, mark's place and field, never what a mark is on."""
        differs = (
            ["Every mark read back alike: what it's on, how far, and when."]
            if not self.differs
            else [
                f"{many(len(self.differs), 'difference')}:",
                *(f"  {each.of}: {each.field}" for each in self.differs),
            ]
        )
        return [
            f"Read the review marks' files in {self.read:.2f}s.",
            f"Converted them in {self.conversion:.2f}s: {self.converted.said()}.",
            f"Read every mark back from the ledger in {self.opened:.2f}s.",
            f"A module's mark on one key: {self.lookup.said()}.",
            f"A mark moved: {self.moved_ledger.said()} on the ledger, {self.moved_file.said()} as a file.",
            *differs,
        ]


def marks_compared(store: MarkStore, files: MarkFiles) -> list[Differs]:
    """Return what differs between the marks `store` holds and those `files` read: each mark of each module of each repository, in order, by its place, and any the store holds that the files don't."""

    def module(repository: Path, file: MarksFile) -> list[Differs]:
        held = store.kept(repository, file.module).marks
        where = f"{repository} {file.module}"
        return [
            *(
                Differs(of=f"{where} mark {at}", field=field)
                for at, (wanted, found) in enumerate(
                    zip(file.marks, held, strict=False), start=1
                )
                for field in ReviewMark.model_fields
                if (keyed(found.key) if field == "key" else getattr(found, field))
                != (keyed(wanted.key) if field == "key" else getattr(wanted, field))
            ),
            *(
                [Differs(of=where, field=f"{len(held)} marks, not {len(file.marks)}")]
                if len(held) != len(file.marks)
                else []
            ),
        ]

    wanted = {
        repository: [each.module for each in kept]
        for repository, kept in files.kept.items()
    }
    extra = [
        Differs(of=f"{repository} {module}", field="extra")
        for repository, modules in store.held.items()
        for module in modules
        if module not in wanted.get(repository, [])
    ]
    return [
        *(
            each
            for repository, kept in files.kept.items()
            for file in kept
            for each in module(repository, file)
        ),
        *extra,
    ]


def marks_rehearsed(
    layout: Layout,
    repositories: Collection[Path],
    carrying: list[Carrying],
    scratch: Path | None = None,
) -> MarksRehearsal:
    """Convert the review marks' files lup's state at `layout` keeps of `repositories`, read alone, onto a scratch ledger at `scratch`, or a temporary directory removed after, and compare them with what reads back; time the conversion, reading it back, a lookup, and a move each way.

    The moves are timed on the scratch ledger and on a copy of a file under it,
    never on the files at `layout`. Raise `InboxError` where no repository
    keeps a mark to time them on.
    """
    if scratch is None:
        with tempfile.TemporaryDirectory() as temporary:
            return marks_rehearsed(layout, repositories, carrying, Path(temporary))
    started = time.perf_counter()
    files = MarkFiles.read(layout, repositories, carrying)
    reading = time.perf_counter() - started
    marked = [
        (repository, each)
        for repository, kept in files.kept.items()
        for each in kept
        if each.marks
    ]
    if not marked:
        message = f"no repository's review marks are kept under {layout.state}"
        raise InboxError(message)
    ledger = Ledger.opened(LedgerLayout(home=scratch / "ledger"), KINDS)
    try:
        started = time.perf_counter()
        converted = marks_converted(MarkStore(ledger=ledger), files)
        converting = time.perf_counter() - started
        if converted is None:
            message = "the scratch ledger held marks before the conversion"
            raise InboxError(message)
        started = time.perf_counter()
        store = MarkStore.opened(ledger)
        opening = time.perf_counter() - started
        differs = marks_compared(store, files)
        [(repository, file), *_] = marked
        keys = [each.key for each in file.marks]
        turns = iter(range(1_000_000))
        lookup = timed(
            lambda: store.of(repository, file.module, keys[next(turns) % len(keys)]),
            200,
        )
        copy = scratch / "files" / f"{file.module}.json"
        write_model(copy, file)
        last = file.marks[-1]

        def moved_file() -> None:
            kept = read_model(copy, MarksFile) or file
            write_model(copy, kept.with_marks([last]))

        return MarksRehearsal(
            read=reading,
            converted=converted,
            conversion=converting,
            opened=opening,
            lookup=lookup,
            moved_file=timed(moved_file, 100),
            moved_ledger=timed(
                lambda: store.moved(repository, file.module, [last]), 100
            ),
            differs=differs,
        )
    finally:
        ledger.close()
