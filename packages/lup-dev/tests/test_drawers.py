"""The drawers under an agent's banner: what its branch changed since the operator approved it, read as the worktree stands and marked good; and a remark on its code telling which quoted lines changed since."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup_dev import cli
from lup_dev.host.pushes import Pushes
from lup_dev.inbox.delivery import Delivery, changed_since
from lup_dev.inbox.notices import Notices
from lup_dev.inbox.store import Asked as Ask
from lup_dev.inbox.store import (
    ChangedFile,
    Conversation,
    Decided,
    Flagged,
    Inbox,
    InboxError,
    Operator,
    Quote,
    Quoted,
    Reading,
    Remark,
    Review,
    Text,
    Whereabouts,
)
from lup_dev.layout import InboxLayout, Layout
from lup_dev.policy.since import ApproveSince, Reader, ShowSince

if TYPE_CHECKING:
    from conftest import FakeClock, Shell


class Silent(Notices):
    """Raises nothing."""

    @override
    async def notify(self, summary: str, body: str) -> None:
        pass


def alone(tmp_path: Path, clock: FakeClock) -> Delivery:
    """A delivery over an inbox under `tmp_path`, outside any service."""
    known = cli.Adapters(known=cli.adapters())
    return Delivery(
        inbox=Inbox.opened(InboxLayout(home=tmp_path / "inbox")),
        waker=cli.Wakers(adapters=known),
        pushes=Pushes(),
        layout=Layout(state=tmp_path / "state", runtime=tmp_path / "run").host,
        notices=Silent(),
        clock=clock,
        say=lambda _: None,
    )


class Branch:
    """A branch `feat` of the bare repository, checked out in a worktree of its own, where the conversation `party` works; `dev` the integration branch, checked out beside it."""

    def __init__(
        self, bare: Path, shell: Shell, delivery: Delivery, clock: FakeClock
    ) -> None:
        self.repository = bare
        self.shell = shell
        self.delivery = delivery
        self.clock = clock
        shell.git(bare, "branch", "dev", "main")
        self.dev = bare / "tree" / "dev"
        shell.git(bare, "worktree", "add", "-q", str(self.dev), "dev")
        self.feat = bare / "tree" / "feat"
        shell.git(bare, "worktree", "add", "-q", "-b", "feat", str(self.feat), "dev")
        self.party = Conversation(repository=bare, runtime="claude", session="s1")
        delivery.inbox.placed(
            Whereabouts(
                conversation=self.party,
                launch="one",
                worktree=self.feat,
                since=clock.now(),
            )
        )

    def reader(self, tmp_path: Path) -> Reader:
        return Reader(
            delivery=self.delivery,
            layout=Layout(state=tmp_path / "state", runtime=tmp_path / "run"),
            integration="dev",
        )

    def wrote(self, path: str, content: str, *, committed: bool = True) -> None:
        """Write `path` in the branch's worktree, and commit it unless told not to."""
        file = self.feat / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
        if committed:
            self.shell.commit(self.feat, f"write {path}")

    def flagged(self, path: str, before: str | None, after: str) -> int:
        """Put a write making `path` hold `after` that landed flagged on `feat` in the operator's inbox, as the judge does, and return its number."""
        reading = Reading(
            role="production",
            asks=[
                Ask(
                    name="new-file" if before is None else "whole-file", taken="flagged"
                )
            ],
        )
        item = asyncio.run(
            self.delivery.flagged(
                Flagged(
                    text=f"{path} landed, flagged for the operator's review.",
                    summary=f"{path} asks",
                    worktree=self.feat,
                    path=Path(path),
                    branch="feat",
                ),
                self.party,
                "",
                ChangedFile.of(
                    Path(path),
                    None if before is None else before.encode(),
                    after.encode(),
                    reading,
                ),
            )
        )
        return item.number


def test_since_you_approved_shows_each_file_the_branch_changed_from_the_version_approved_and_marks_it_good(
    bare: Path, shell: Shell, clock: FakeClock, tmp_path: Path
) -> None:
    delivery = alone(tmp_path, clock)
    branch = Branch(bare, shell, delivery, clock)
    reader = branch.reader(tmp_path)
    first = '"""Rooms."""\n\n\nclass Room:\n    pass\n'
    branch.wrote("src/pkg/rooms.py", first)
    flag = branch.flagged("src/pkg/rooms.py", None, first)
    branch.wrote("README.md", "# Work\n\nMore.\n", committed=False)
    (branch.feat / ".venv").mkdir()
    (branch.feat / ".venv" / "ignored.py").write_text("x = 1\n")

    shown = reader.read(ShowSince(conversation=branch.party))
    assert (shown.worktree, shown.branch, shown.same, shown.writes) == (
        branch.feat,
        "feat",
        False,
        1,
    )
    assert [each.file.path for each in shown.files] == [
        Path("README.md"),
        Path("src/pkg/rooms.py"),
    ]
    readme, rooms = shown.files
    # The uncommitted change counts, from the integration branch's tip, which the operator saw nothing of.
    assert (readme.file.before, readme.file.after) == (
        Text(text="# Work\n"),
        Text(text="# Work\n\nMore.\n"),
    )
    assert (readme.flags, readme.since, readme.file.reading) == ([], None, None)
    # The new module, flagged: whole, with the judge's reading of its flag, and the flag it's approved by.
    assert (rooms.file.before, rooms.file.after) == (None, Text(text=first))
    assert rooms.file.reading is not None
    assert rooms.file.reading.asks[0].name == "new-file"
    assert (rooms.flags, rooms.since) == ([flag], None)
    assert rooms.version == shell.git(branch.feat, "rev-parse", "HEAD:src/pkg/rooms.py")
    assert shown.version.endswith(" 0")

    # Asked again with the version shown, the files are left out: nothing changed.
    again = reader.read(ShowSince(conversation=branch.party, seen=shown.version))
    assert (again.same, again.files, again.version) == (True, [], shown.version)

    # Marked good: the flag is approved, and the file is shown from that version on.
    approved = reader.approved(ApproveSince(conversation=branch.party))
    assert approved.flags == [flag]
    assert delivery.inbox.item(flag).state == Decided(at=clock.now(), approved=True)
    # The baseline moved, so the version did: what's shown from it on is read anew.
    settled = reader.read(ShowSince(conversation=branch.party, seen=shown.version))
    assert (settled.same, settled.version.endswith(" 1")) == (False, True)
    assert [each.file.path for each in settled.files] == [Path("README.md")]
    second = first + "\n\ndef enter() -> None:\n    pass\n"
    branch.wrote("src/pkg/rooms.py", second, committed=False)
    grown = reader.read(ShowSince(conversation=branch.party))
    rooms = next(
        each for each in grown.files if each.file.path == Path("src/pkg/rooms.py")
    )
    assert (rooms.file.before, rooms.file.after, rooms.since, rooms.flags) == (
        Text(text=first),
        Text(text=second),
        flag,
        [],
    )
    # The reading of an approved flag isn't the file's: its asks are kept without their lines.
    assert rooms.file.reading is None


def test_space_a_approves_the_flags_on_one_file_and_a_detached_head_is_refused(
    bare: Path, shell: Shell, clock: FakeClock, tmp_path: Path
) -> None:
    delivery = alone(tmp_path, clock)
    branch = Branch(bare, shell, delivery, clock)
    reader = branch.reader(tmp_path)
    branch.wrote("src/pkg/a.py", "a = 1\n")
    branch.wrote("src/pkg/b.py", "b = 1\n")
    one = branch.flagged("src/pkg/a.py", None, "a = 1\n")
    two = branch.flagged("src/pkg/b.py", None, "b = 1\n")
    approved = reader.approved(
        ApproveSince(conversation=branch.party, path=Path("src/pkg/a.py"))
    )
    assert approved.flags == [one]
    assert isinstance(delivery.inbox.item(one).state, Decided)
    assert not isinstance(delivery.inbox.item(two).state, Decided)
    shell.git(branch.feat, "checkout", "-q", "--detach")
    with pytest.raises(InboxError) as refused:
        reader.approved(ApproveSince(conversation=branch.party))
    assert "has no branch checked out" in str(refused.value)
    unheard = Conversation(repository=bare, runtime="claude", session="s9")
    with pytest.raises(InboxError) as unknown:
        reader.read(ShowSince(conversation=unheard))
    assert str(unknown.value) == "lup's inbox has never heard of the conversation"


def test_a_remark_on_code_says_which_quoted_lines_changed_since_it_was_written(
    tmp_path: Path, clock: FakeClock
) -> None:
    worktree = tmp_path / "w"
    (worktree / "src").mkdir(parents=True)
    file = worktree / "src" / "a.py"
    file.write_text("a = 1\nb = 2\nc = 3\nd = 4\n")
    quoted = Quoted(
        worktree=worktree,
        path=Path("src/a.py"),
        version="v1",
        first=2,
        lines=["b = 2", "c = 3"],
    )
    assert changed_since(quoted) is None
    file.write_text("start = 0\na = 1\nb = 2\nc = 30\nd = 4\n")
    assert changed_since(quoted) == "3"
    file.unlink()
    assert changed_since(quoted) == "all"

    delivery = alone(tmp_path, clock)
    party = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    other = party.model_copy(update={"agent": "a1"})
    delivery.inbox.placed(
        Whereabouts(
            conversation=other, launch="one", worktree=worktree, since=clock.now()
        )
    )
    file.write_text("a = 1\nb = 2\nc = 30\n")
    review = Review(
        covers=[],
        remarks=[
            Remark(
                to=party,
                quote=Quote(text="src/a.py:2-3\n b = 2\n c = 3", start=0, end=20),
                text="Name these.",
                code=quoted,
            ),
            Remark(
                to=other,
                quote=Quote(text="I'll read the records first.", start=0, end=28),
                text="Read the field notes too.",
                step=4,
            ),
        ],
    )
    told = delivery.reviewing(review, party)
    context = "\n".join(
        [
            "<context>",
            "What the operator said in the same reply on other agents' items and to other agents: not yours to act on, unless it says so.",
            f'<remark to="subagent a1 of claude session s1" worktree="{worktree}">',
            "<quote>I'll read the records first.</quote>",
            "<reply>Read the field notes too.</reply>",
            "</remark>",
            "</context>",
        ]
    )
    assert [part.written() if not isinstance(part, str) else part for part in told] == [
        '<remark>\n<quote changed="3">\nsrc/a.py:2-3\n b = 2\n c = 3\n</quote>\n<reply>Name these.</reply>\n</remark>',
        context,
    ]


def test_a_draft_of_remarks_alone_is_a_review_to_each_agent_remarked_to(
    tmp_path: Path, clock: FakeClock
) -> None:
    delivery = alone(tmp_path, clock)
    party = Conversation(repository=tmp_path / ".git", runtime="claude", session="s1")
    delivery.inbox.placed(
        Whereabouts(
            conversation=party, launch="one", worktree=tmp_path, since=clock.now()
        )
    )
    remark = Remark(
        to=party, quote=Quote(text="Going.", start=0, end=6), text="Go on.", step=1
    )
    delivery.inbox.drafted(
        delivery.inbox.draft().model_copy(update={"remarks": [remark]})
    )
    [sent] = delivery.reviews(delivery.inbox.draft(), [])
    assert sent.recipient == party
    assert isinstance(sent.reason, Review)
    assert sent.reason.remarks == [remark]
    assert sent.sender == Operator()
    assert sent.made == datetime(2026, 10, 1, 12, tzinfo=UTC)
