"""The drawers under an agent's banner: what their branch changed since the operator last saw it, read as the worktree stands, its files marked reviewed; and a remark on their code telling which quoted lines changed since."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from pydantic import ValidationError

from lup_dev import cli
from lup_dev.declaration.project import Project
from lup_dev.declaration.resolve import Declaration
from lup_dev.host.pushes import Pushes
from lup_dev.inbox.delivery import Delivery, changed_since
from lup_dev.inbox.notices import Notices
from lup_dev.inbox.store import (
    KINDS,
    ChangedFile,
    Decided,
    Flagged,
    Inbox,
    InboxError,
    Quote,
    Quoted,
    Reading,
    Remark,
    Review,
    Text,
    Waiting,
    Whereabouts,
)
from lup_dev.inbox.store import Asked as Ask
from lup_dev.layout import Layout
from lup_dev.policy.checkpoint import LastDeclaration
from lup_dev.policy.landing import Baseline, Saw
from lup_dev.policy.reviewed import Mark, Reviews
from lup_dev.policy.since import (
    Reader,
    ReviewSince,
    ShowSince,
    Since,
    SinceFile,
    SincePlace,
    SinceReviewed,
    ViewedFile,
)
from lup_dev.policy.worktrees import Holding as Worked
from lup_dev.policy.worktrees import SessionIndex
from lup_dev.stored import write_model
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.parties import Conversation, Operator

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
        inbox=Inbox.opened(
            Ledger.opened(LedgerLayout(home=tmp_path / "ledger"), KINDS)
        ),
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


def only(since: Since) -> SincePlace:
    """Return the one place `since` shows."""
    [place] = since.places
    return place


def test_since_you_approved_shows_each_file_from_the_version_last_seen_and_a_file_marked_reviewed_is_a_line_until_written_again(
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
    [place] = shown.places
    assert (place.worktree, place.branch, shown.same) == (branch.feat, "feat", False)
    assert [each.path for each in only(shown).files] == [
        Path("README.md"),
        Path("src/pkg/rooms.py"),
    ]
    readme, rooms = only(shown).files
    # The uncommitted change counts, from the integration branch's tip, which the operator saw nothing of.
    assert readme.file == ChangedFile(
        path=Path("README.md"),
        before=Text(text="# Work\n"),
        after=Text(text="# Work\n\nMore.\n"),
    )
    assert (readme.flags, readme.since, readme.reviewed) == ([], None, None)
    # The new module, flagged: whole, with the judge's reading of its flag, and the flag it's approved by.
    assert rooms.file is not None
    assert (rooms.file.before, rooms.file.after) == (None, Text(text=first))
    assert rooms.file.reading is not None
    assert rooms.file.reading.asks[0].name == "new-file"
    assert (rooms.flags, rooms.since) == ([flag], None)
    assert rooms.version == shell.git(branch.feat, "rev-parse", "HEAD:src/pkg/rooms.py")

    # Asked again with the version shown, the files are left out: nothing changed.
    again = reader.read(ShowSince(conversation=branch.party, seen=shown.version))
    assert (again.same, again.places, again.version) == (True, [], shown.version)

    # Marked reviewed at the version shown: its flag is approved, and it's a line, nothing under it.
    reviewed = reader.reviewed(
        ReviewSince(
            conversation=branch.party,
            files=[ViewedFile(path=rooms.path, version=rooms.version)],
        )
    )
    assert reviewed == SinceReviewed(reviewed=[rooms.path], approved=[flag], moved=[])
    assert delivery.inbox.item(flag).state == Decided(at=clock.now(), approved=True)
    settled = reader.read(ShowSince(conversation=branch.party, seen=shown.version))
    assert settled.same is False
    assert [each.path for each in only(settled).files] == [readme.path, rooms.path]
    assert only(settled).files[1] == SinceFile(
        path=rooms.path, version=rooms.version, reviewed=clock.now()
    )

    # Written again, it comes back with only what changed since the version reviewed; read by a reader made anew, as after a restart.
    clock.sleep(60)
    second = first + "\n\ndef enter() -> None:\n    pass\n"
    branch.wrote("src/pkg/rooms.py", second, committed=False)
    grown = branch.reader(tmp_path).read(ShowSince(conversation=branch.party))
    rooms = only(grown).files[1]
    assert rooms.file == ChangedFile(
        path=rooms.path, before=Text(text=first), after=Text(text=second)
    )
    assert (rooms.since, rooms.flags, rooms.reviewed) == (None, [], reviewed_at(clock))

    # A file nothing flagged is marked reviewed as well, and deleting one is reviewed as its deletion.
    (branch.feat / "src/pkg/rooms.py").unlink()
    gone = reader.read(ShowSince(conversation=branch.party))
    [readme, rooms] = only(gone).files
    assert rooms.file is not None
    assert (rooms.version, rooms.file.before, rooms.file.after) == (
        None,
        Text(text=first),
        None,
    )
    reader.reviewed(
        ReviewSince(
            conversation=branch.party,
            files=[
                ViewedFile(path=readme.path, version=readme.version),
                ViewedFile(path=rooms.path, version=None),
            ],
        )
    )
    lines = reader.read(ShowSince(conversation=branch.party))
    assert [(each.path, each.file, each.reviewed) for each in only(lines).files] == [
        (readme.path, None, clock.now()),
        (rooms.path, None, clock.now()),
    ]


def test_the_drawer_reads_every_place_the_conversation_worked_each_its_own_and_marks_each_on_its_branch(
    bare: Path, shell: Shell, clock: FakeClock, tmp_path: Path
) -> None:
    delivery = alone(tmp_path, clock)
    branch = Branch(bare, shell, delivery, clock)
    reader = branch.reader(tmp_path)
    layout = Layout(state=tmp_path / "state", runtime=tmp_path / "run")
    # The conversation's file tools wrote in `dev`'s worktree, then in `feat`'s.
    SessionIndex(layout=layout).write(
        "s1",
        Worked(
            repository=bare,
            worktrees=[branch.dev, branch.feat],
            wrote={"": [branch.dev, branch.feat]},
        ),
    )
    branch.wrote("src/pkg/rooms.py", '"""Rooms."""\n')
    (branch.dev / "notes.md").write_text("# Notes\n")
    # A branch no worktree has checked out holds a flag of theirs, read at its tip; a branch gone holds another.
    shell.git(bare, "branch", "fix", "dev")
    fix = bare / "tree" / "fix"
    shell.git(bare, "worktree", "add", "-q", str(fix), "fix")
    (fix / "src" / "fix.py").write_text("x = 1\n")
    shell.commit(fix, "write src/fix.py")
    shell.git(bare, "worktree", "remove", str(fix))
    fixed = flag_on(branch, "src/fix.py", "fix")
    gone = flag_on(branch, "src/old.py", "old")

    shown = reader.read(ShowSince(conversation=branch.party))
    assert [(each.worktree, each.branch, each.gone) for each in shown.places] == [
        (branch.dev, "dev", False),
        (branch.feat, "feat", False),
        (None, "fix", False),
        (None, "old", True),
    ]
    dev, feat, at_tip, old = shown.places
    assert [each.path for each in dev.files] == [Path("notes.md")]
    assert [each.path for each in feat.files] == [Path("src/pkg/rooms.py")]
    [fix_file] = at_tip.files
    assert fix_file.file is not None
    assert (fix_file.flags, fix_file.file.after) == ([fixed], Text(text="x = 1\n"))
    assert [(each.path, each.flags, each.file) for each in old.files] == [
        (Path("src/old.py"), [gone], None)
    ]

    # Marked on its place, a branch alone: its flag approved, the mark on `fix`.
    marked = reader.reviewed(
        ReviewSince(
            conversation=branch.party,
            branch="fix",
            files=[ViewedFile(path=fix_file.path, version=fix_file.version)],
            seen=shown.version,
        )
    )
    assert (marked.approved, marked.moved) == ([fixed], [])
    assert marked.version is not None
    reviews = Reviews.of(layout, bare)
    assert reviews.marks("fix").files == [
        Mark(path=fix_file.path, version=fix_file.version, at=clock.now())
    ]
    # On a branch gone, the flag is approved, nothing marked; and the branch's place is no more.
    reader.reviewed(
        ReviewSince(
            conversation=branch.party,
            branch="old",
            files=[ViewedFile(path=Path("src/old.py"))],
        )
    )
    assert delivery.inbox.item(gone).state == Decided(at=clock.now(), approved=True)
    assert reviews.marks("old").files == []
    after = reader.read(ShowSince(conversation=branch.party))
    assert [each.branch for each in after.places] == ["dev", "feat"]
    # A place no longer the conversation's is refused.
    with pytest.raises(InboxError) as refused:
        reader.reviewed(
            ReviewSince(
                conversation=branch.party,
                branch="old",
                files=[ViewedFile(path=Path("src/old.py"))],
            )
        )
    assert str(refused.value) == "old is no place the conversation worked"


def flag_on(branch: Branch, path: str, on: str) -> int:
    """Put a write making `path` that landed flagged on the branch `on` in the operator's inbox from `branch`'s conversation, and return its number."""
    item = asyncio.run(
        branch.delivery.flagged(
            Flagged(
                text=f"{path} landed, flagged for the operator's review.",
                summary=f"{path} asks",
                worktree=branch.feat,
                path=Path(path),
                branch=on,
            ),
            branch.party,
            "",
            ChangedFile.of(Path(path), None, b"x = 1\n"),
        )
    )
    return item.number


def test_a_file_nothing_flagged_carries_its_role_by_the_declaration_the_judge_last_loaded(
    bare: Path, shell: Shell, clock: FakeClock, tmp_path: Path
) -> None:
    delivery = alone(tmp_path, clock)
    branch = Branch(bare, shell, delivery, clock)
    branch.wrote("src/rooms.test.ts", "test('rooms', () => {});\n")
    branch.wrote("fixture.json", "{}\n")
    branch.wrote("src/rooms.ts", "export const rooms = 1;\n")

    # Before the judge has loaded any declaration of the repository, nothing says a file's role.
    unknown = branch.reader(tmp_path).read(ShowSince(conversation=branch.party))
    assert [each.file.reading for each in only(unknown).files if each.file] == [
        None
    ] * 3

    layout = Layout(state=tmp_path / "state", runtime=tmp_path / "run")
    last = LastDeclaration(declaration=Declaration.of(Project()), commit="c1")
    write_model(layout.declaration(bare), last)
    shown = branch.reader(tmp_path).read(ShowSince(conversation=branch.party))
    roles = {
        str(each.path): each.file.reading.role
        for each in only(shown).files
        if each.file is not None and each.file.reading is not None
    }
    assert roles == {
        "fixture.json": "data",
        "src/rooms.test.ts": "test",
        "src/rooms.ts": "production",
    }


def test_a_file_is_shown_from_where_the_branch_left_the_integration_branch_so_what_that_took_in_since_is_never_shown_undone(
    bare: Path, shell: Shell, clock: FakeClock, tmp_path: Path
) -> None:
    delivery = alone(tmp_path, clock)
    branch = Branch(bare, shell, delivery, clock)
    reader = branch.reader(tmp_path)
    middle = "x = 0\ny = 0\nz = 0\n"
    (branch.dev / "shared.py").write_text(f"a = 1\n{middle}b = 1\n")
    shell.commit(branch.dev, "shared")
    shell.git(branch.feat, "merge", "-q", "--ff-only", "dev")
    # The branch changes the shared module's last line; the integration branch, after it left, its first, and a file
    # of its own.
    branch.wrote("shared.py", f"a = 1\n{middle}b = 2\n")
    (branch.dev / "shared.py").write_text(f"a = 2\n{middle}b = 1\n")
    (branch.dev / "landed.py").write_text("landed = True\n")
    shell.commit(branch.dev, "landed")

    [shared] = only(reader.read(ShowSince(conversation=branch.party))).files
    assert shared.file == ChangedFile(
        path=Path("shared.py"),
        before=Text(text=f"a = 1\n{middle}b = 1\n"),
        after=Text(text=f"a = 1\n{middle}b = 2\n"),
    )

    # Merged into the branch, what the integration branch took in is its own still: the shared module shows the
    # branch's change alone, on the integration branch's version.
    shell.git(branch.feat, "merge", "-q", "--no-edit", "dev")
    [merged] = only(reader.read(ShowSince(conversation=branch.party))).files
    assert merged.file == ChangedFile(
        path=Path("shared.py"),
        before=Text(text=f"a = 2\n{middle}b = 1\n"),
        after=Text(text=f"a = 2\n{middle}b = 2\n"),
    )


def reviewed_at(clock: FakeClock) -> datetime:
    """Return when the file was marked reviewed: a minute before `clock`'s time."""
    return clock.now() - timedelta(minutes=1)


def test_marking_a_file_reviewed_approves_its_flags_only_where_it_stands_as_shown(
    bare: Path, shell: Shell, clock: FakeClock, tmp_path: Path
) -> None:
    delivery = alone(tmp_path, clock)
    branch = Branch(bare, shell, delivery, clock)
    reader = branch.reader(tmp_path)
    branch.wrote("src/pkg/a.py", "a = 1\n")
    branch.wrote("src/pkg/b.py", "b = 1\n")
    one = branch.flagged("src/pkg/a.py", None, "a = 1\n")
    two = branch.flagged("src/pkg/b.py", None, "b = 1\n")
    shown = reader.read(ShowSince(conversation=branch.party))
    viewed = [
        ViewedFile(path=each.path, version=each.version) for each in only(shown).files
    ]
    # A write the page hasn't read yet comes as the operator marks what it shows.
    branch.wrote("src/pkg/a.py", "a = 2\n", committed=False)
    reviewed = reader.reviewed(ReviewSince(conversation=branch.party, files=viewed))
    assert reviewed == SinceReviewed(
        reviewed=[Path("src/pkg/a.py"), Path("src/pkg/b.py")],
        approved=[two],
        moved=[Path("src/pkg/a.py")],
    )
    assert delivery.inbox.item(one).state == Waiting()
    assert isinstance(delivery.inbox.item(two).state, Decided)
    # The file moved shows what changed since the version marked, its flag waiting on the operator still.
    [a, b] = only(reader.read(ShowSince(conversation=branch.party))).files
    assert a.file is not None
    assert (a.file.before, a.file.after, a.flags) == (
        Text(text="a = 1\n"),
        Text(text="a = 2\n"),
        [one],
    )
    assert (b.file, b.flags) == (None, [])

    unknown = ViewedFile(path=Path("src/pkg/a.py"), version="0" * 40)
    with pytest.raises(InboxError) as lost:
        reader.reviewed(ReviewSince(conversation=branch.party, files=[unknown]))
    assert str(lost.value) == (
        f"the worktree's store keeps no {'0' * 40}, a version the page shows: read "
        "the drawer again"
    )
    with pytest.raises(ValidationError):
        ViewedFile(path=Path("src/pkg/a.py"), version="--batch")
    shell.git(branch.feat, "checkout", "-q", "--detach")
    with pytest.raises(InboxError) as refused:
        reader.reviewed(ReviewSince(conversation=branch.party, files=viewed))
    assert "has no branch checked out" in str(refused.value)
    unheard = Conversation(repository=bare, runtime="claude", session="s9")
    with pytest.raises(InboxError) as unknown_party:
        reader.read(ShowSince(conversation=unheard))
    assert str(unknown_party.value) == "lup's inbox has never heard of the conversation"


def test_a_file_the_operator_saw_in_an_item_is_shown_from_the_version_kept_beside_it(
    bare: Path, shell: Shell, clock: FakeClock, tmp_path: Path
) -> None:
    delivery = alone(tmp_path, clock)
    branch = Branch(bare, shell, delivery, clock)
    reader = branch.reader(tmp_path)
    branch.wrote("src/pkg/a.py", "a = 1\n")
    flag = branch.flagged("src/pkg/a.py", None, "a = 1\n")
    delivery.flag_approved(flag)

    # Standing as the item kept it, it's a line saying where they saw it.
    [a] = only(reader.read(ShowSince(conversation=branch.party))).files
    assert (a.file, a.since, a.flags) == (None, flag, [])

    # Written since, it's shown from that version.
    branch.wrote("src/pkg/a.py", "a = 2\n", committed=False)
    [a] = only(reader.read(ShowSince(conversation=branch.party))).files
    assert a.file == ChangedFile(
        path=a.path, before=Text(text="a = 1\n"), after=Text(text="a = 2\n")
    )
    assert a.since == flag


def test_marking_files_reviewed_answers_with_the_drawer_as_it_stands_where_it_stood_as_the_page_shows_it(
    bare: Path, shell: Shell, clock: FakeClock, tmp_path: Path
) -> None:
    delivery = alone(tmp_path, clock)
    branch = Branch(bare, shell, delivery, clock)
    reader = branch.reader(tmp_path)
    branch.wrote("src/pkg/a.py", "a = 1\n")
    branch.wrote("src/pkg/b.py", "b = 1\n")
    flag = branch.flagged("src/pkg/a.py", None, "a = 1\n")
    shown = reader.read(ShowSince(conversation=branch.party))
    [a, b] = only(shown).files

    # Nothing changed since the page read the drawer: the answer is the drawer as it stands, the file marked a line.
    marked = reader.reviewed(
        ReviewSince(
            conversation=branch.party,
            files=[ViewedFile(path=a.path, version=a.version)],
            seen=shown.version,
        )
    )
    now = reader.read(ShowSince(conversation=branch.party))
    assert (marked.approved, marked.version, marked.files) == (
        [flag],
        now.version,
        [only(now).files[0]],
    )
    assert marked.files == [
        SinceFile(path=a.path, version=a.version, reviewed=clock.now())
    ]
    assert only(now).files[1] == b

    # A write came after the page read it: the page's drawer isn't the one as it stands, and it's read again.
    clock.sleep(60)
    branch.wrote("src/pkg/a.py", "a = 2\n", committed=False)
    again = reader.reviewed(
        ReviewSince(
            conversation=branch.party,
            files=[ViewedFile(path=b.path, version=b.version)],
            seen=now.version,
        )
    )
    assert (again.reviewed, again.version, again.files) == ([b.path], None, [])
    # Without the version shown, as an older page asks, it's read again too.
    unsaid = reader.reviewed(
        ReviewSince(
            conversation=branch.party,
            files=[ViewedFile(path=b.path, version=b.version)],
        )
    )
    assert (unsaid.version, unsaid.files) == (None, [])


def test_what_the_operator_last_saw_of_a_file_is_the_later_of_its_mark_and_an_item_they_settled(
    tmp_path: Path, clock: FakeClock
) -> None:
    delivery = alone(tmp_path, clock)
    repository = tmp_path / "proj.git"
    party = Conversation(repository=repository, runtime="claude", session="s1")
    reviews = Reviews.of(Layout(state=tmp_path / "state"), repository)
    baseline = Baseline(inbox=delivery.inbox, repository=repository, reviews=reviews)
    path = Path("src/a.py")
    assert baseline.saw(path, ["feat"]) is None
    flagged = asyncio.run(
        delivery.flagged(
            Flagged(
                text="src/a.py landed, flagged.",
                summary="new-file",
                worktree=tmp_path,
                path=path,
                branch="feat",
            ),
            party,
            "",
            ChangedFile.of(path, None, b"a = 1\n"),
        )
    )
    delivery.flag_approved(flagged.number)
    assert baseline.saw(path, ["feat"]) == Saw(content=b"a = 1\n", item=flagged.number)
    # A mark made as the item was settled is the later.
    mark = Mark(path=path, version="1" * 40, at=clock.now())
    reviews.marked("feat", [mark], {"1" * 40: b"a = 2\n"})
    assert baseline.saw(path, ["feat"]) == Saw(content=b"a = 2\n", reviewed=mark)
    assert baseline.saw(path, ["other"]) is None
    assert reviews.marks("feat").files == [mark]
    stamp = reviews.stamp("feat")
    # Marked again, the mark replaces the one before, and the branch's stamp moves.
    clock.sleep(60)
    deleted = Mark(path=path, version=None, at=clock.now())
    reviews.marked("feat", [deleted], {})
    assert reviews.marks("feat").files == [deleted]
    assert reviews.stamp("feat") != stamp
    assert baseline.saw(path, ["feat"]) == Saw(content=None, reviewed=deleted)


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
    told = delivery.reviewing(review, party, [])
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
