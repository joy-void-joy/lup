"""A file tool's write, judged before it lands."""

from pathlib import Path
from typing import TYPE_CHECKING

from lup_dev.inbox.store import (
    ApiChanged,
    Asked,
    ChangedFile,
    Conversation,
    Flagged,
    Reading,
    Text,
)
from lup_dev.policy.before import Decision, Overwrite, Proposal, Replacement, before
from lup_dev.policy.checkpoint import (
    CallFinished,
    CallStarted,
    Session,
    SessionStarted,
)
from lup_dev.policy.holds import Holds, Response
from lup_dev.policy.verdicts import VerdictLog
from lup_dev.policy.worktrees import Place, place
from lup_dev.stored import read_model

if TYPE_CHECKING:
    from conftest import Kit, Shell

CORE = Path("src/pkg/core.py")


def replace(
    repo: Path, old: str, new: str, *, path: Path = CORE, everywhere: bool = False
) -> Replacement:
    return Replacement(
        call="e1",
        tool="Edit",
        path=repo / path,
        old=old,
        new=new,
        everywhere=everywhere,
    )


def test_a_replacement_applies_as_the_tool_does() -> None:
    once = Replacement(call="1", tool="t", path=Path("/a"), old="x", new="y")
    assert once.content("axb") == "ayb"
    assert once.content("axbx") is None
    everywhere = Replacement(
        call="1", tool="t", path=Path("/a"), old="x", new="y", everywhere=True
    )
    assert everywhere.content("axbx") == "ayby"
    assert once.content("abc") is None
    assert (
        Replacement(call="1", tool="t", path=Path("/a"), old="", new="new").content(
            None
        )
        == "new"
    )


def test_an_allowed_edit_is_remembered_until_its_call_finishes(
    kit: Kit, repo: Path
) -> None:
    decision = before(
        kit.bench, replace(repo, "return x\n", "return x + 1\n"), "s1", repo
    )
    assert decision.outcome == "allow"
    assert decision.reason == ""
    session = read_model(kit.layout.store(repo).session("s1"), Session)
    assert session is not None
    assert [
        (pending.call, pending.path, pending.asked) for pending in session.pending
    ] == [("e1", CORE, False)]


def test_an_edit_with_a_finding_is_allowed_its_finding_told_with_the_call(
    kit: Kit, repo: Path
) -> None:
    decision = before(
        kit.bench, replace(repo, "return x\n", "return x  # BAD regex\n"), "s1", repo
    )
    assert decision.outcome == "allow"
    assert decision.reason == ""
    assert decision.told.startswith("lup's findings on the lines changed")
    assert f"  {repo}/src/pkg/core.py:" in decision.told
    assert " - regex: " in decision.told
    session = read_model(kit.layout.store(repo).session("s1"), Session)
    assert session is not None
    assert [pending.path for pending in session.pending] == [CORE]
    assert not (repo / ".lup" / "saved").exists()


def test_a_write_that_asks_is_held_for_the_operator_and_let_through_on_a_yes(
    kit: Kit, repo: Path
) -> None:
    was = (repo / CORE).read_text()
    write = Overwrite(call="w1", tool="Write", path=repo / CORE, text=was + "\n")
    decision = before(kit.bench, write, "s1", repo)
    [hold] = kit.announced.holds
    assert kit.announced.files == [
        [
            ChangedFile(
                path=CORE,
                before=Text(text=was),
                after=Text(text=was + "\n"),
                reading=Reading(
                    role="production", asks=[Asked(name="whole-file", taken="held")]
                ),
            )
        ]
    ]
    assert decision == Decision(outcome="allow")
    assert [each.asks for each in hold.files] == [
        ["the write replaces the whole of src/pkg/core.py"]
    ]
    assert hold.diff.startswith("--- a/src/pkg/core.py\n+++ b/src/pkg/core.py\n")
    assert kit.announced.runtimes == ["asking"]
    assert (hold.call, hold.agent) == ("w1", None)
    session = read_model(kit.layout.store(repo).session("s1"), Session)
    assert session is not None
    assert [(each.path, each.asked) for each in session.pending] == [(CORE, True)]
    assert session.approved == [CORE]
    *_, logged = VerdictLog(path=kit.layout.verdicts(repo / ".git")).read()
    assert (logged.outcome, logged.answer) == ("hold", "approved")


def test_a_flagged_write_lands_unasked_unless_the_operator_holds_its_agents(
    kit: Kit, repo: Path
) -> None:
    kit.announced.holding_all = False
    write = Overwrite(
        call="w1", tool="Write", path=repo / CORE, text=(repo / CORE).read_text() + "\n"
    )
    decision = before(kit.bench, write, "s1", repo, agent="a1")
    assert decision == Decision(outcome="allow")
    assert kit.announced.holds == []
    assert kit.announced.asked == ["asking/s1/a1"]
    [verdict] = VerdictLog(path=kit.layout.verdicts(repo / ".git")).read()
    assert (verdict.outcome, verdict.reasons) == ("allow", ["whole-file"])


def test_a_flagged_items_text_names_its_file_from_the_worktrees_root_alone(
    kit: Kit, repo: Path
) -> None:
    kit.announced.holding_all = False
    was = (repo / CORE).read_text()
    write = Overwrite(
        call="w1",
        tool="Write",
        path=repo / CORE,
        text=was + "\n\nclass Room:\n    pass\n",
    )
    before(kit.bench, write, "s1", repo)
    [asked] = kit.flags.asked
    assert asked.flagged.summary.splitlines() == [
        "the write replaces the whole of src/pkg/core.py",
        "src/pkg/core.py adds the class `Room`",
    ]
    assert str(repo) not in f"{asked.flagged.text}\n{asked.flagged.summary}"


ROOMS = Path("src/pkg/rooms.py")


def landed(kit: Kit, repo: Path, proposal: Proposal, agent: str = "") -> Decision:
    """Judge a file tool's write before it lands, then land it as its call runs and finishes."""
    decision = before(kit.bench, proposal, "s1", repo, agent=agent or None)
    call = proposal.call
    CallStarted(
        session="s1", agent=agent, cwd=repo, call=call, tool=proposal.tool
    ).apply(kit.bench)
    path = proposal.path
    path.write_text(
        proposal.content(path.read_text() if path.is_file() else None) or ""
    )
    CallFinished(session="s1", agent=agent, cwd=repo, call=call).apply(kit.bench)
    return decision


def test_a_flagged_write_is_put_before_the_operator_as_it_lands_holding_no_one(
    kit: Kit, repo: Path
) -> None:
    kit.announced.holding_all = False
    text = '"""Rooms."""\n'
    write = Overwrite(call="w1", tool="Write", path=repo / ROOMS, text=text)
    decision = landed(kit, repo, write, agent="a1")
    assert decision == Decision(outcome="allow")
    assert kit.announced.holds == []
    [asked] = kit.flags.asked
    assert (asked.sender, asked.call, asked.joining) == (
        Conversation(
            repository=repo / ".git", runtime="asking", session="s1", agent="a1"
        ),
        "w1",
        None,
    )
    # Each summary line is the reason alone, naming the file from the worktree's root: the file's header names it.
    assert asked.flagged == Flagged(
        text="src/pkg/rooms.py landed, flagged for the operator's review.",
        summary="src/pkg/rooms.py is a new production file",
        worktree=repo,
        path=ROOMS,
    )
    assert asked.file == ChangedFile(
        path=ROOMS,
        before=None,
        after=Text(text=text),
        reading=Reading(
            role="production", asks=[Asked(name="new-file", taken="flagged")]
        ),
    )
    assert asked.diff.startswith("--- a/src/pkg/rooms.py\n+++ b/src/pkg/rooms.py\n")


def test_a_later_flagged_write_joins_the_item_judged_whole_since_it_was_made(
    kit: Kit, repo: Path
) -> None:
    kit.announced.holding_all = False
    first = '"""Rooms."""\n'
    room = "\n\nclass Room:\n    pass\n"
    hall = "\n\nclass Hall:\n    pass\n"
    landed(kit, repo, Overwrite(call="w1", tool="Write", path=repo / ROOMS, text=first))
    adds = Replacement(
        call="e1", tool="Edit", path=repo / ROOMS, old=first, new=first + room
    )
    landed(kit, repo, adds)
    plain = Replacement(
        call="e2",
        tool="Edit",
        path=repo / ROOMS,
        old=room,
        new=room + "\n\ndef open_room() -> None:\n    pass\n",
    )
    landed(kit, repo, plain)
    _, joined, refreshed = kit.flags.asked
    # The class added asks on its own; joined, the file is judged whole since the item was made: new, with its class.
    assert joined.joining == 1
    assert joined.file.before is None
    assert joined.file.after == Text(text=first + room)
    assert joined.file.reading == Reading(
        role="production",
        asks=[
            Asked(name="new-file", taken="flagged"),
            Asked(
                name="public-api",
                taken="flagged",
                line=4,
                api=ApiChanged(kind="class-added", name="Room"),
            ),
        ],
    )
    assert joined.flagged.summary == (
        "src/pkg/rooms.py is a new production file\n"
        "src/pkg/rooms.py adds the class `Room`"
    )
    # A write flagging nothing of its own refreshes the item, judged whole: it shows the file as it stands.
    kept = (repo / ROOMS).read_text()
    assert (refreshed.joining, refreshed.refreshing, refreshed.call) == (1, True, "e2")
    assert (refreshed.file.before, refreshed.file.after) == (None, Text(text=kept))
    assert refreshed.file.reading == joined.file.reading
    assert refreshed.flagged.summary == joined.flagged.summary
    assert "def open_room" in refreshed.diff
    assert sorted(kit.flags.items) == [1]
    # Read, the item gathers no more: the next flagged write is an item of its own, from where the file stands.
    kit.flags.read.append(1)
    landed(
        kit,
        repo,
        Replacement(
            call="e3", tool="Edit", path=repo / ROOMS, old=kept, new=kept + hall
        ),
    )
    # Another conversation's flagged write to the file is its own item too.
    later = (repo / ROOMS).read_text()
    landed(
        kit,
        repo,
        Replacement(
            call="e4",
            tool="Edit",
            path=repo / ROOMS,
            old=later,
            new=later + "\n\nclass Door:\n    pass\n",
        ),
        agent="a2",
    )
    *_, alone, other = kit.flags.asked
    assert (alone.joining, alone.file.before) == (None, Text(text=kept))
    assert alone.file.reading is not None
    assert [each.api for each in alone.file.reading.asks] == [
        ApiChanged(kind="class-added", name="Hall")
    ]
    assert (other.joining, other.sender.agent) == (None, "a2")
    assert sorted(kit.flags.items) == [1, 2, 3]


def test_a_write_to_a_file_no_item_gathers_asks_the_inbox_nothing(
    kit: Kit, repo: Path
) -> None:
    kit.announced.holding_all = False
    landed(kit, repo, replace(repo, "return x\n", "return x + 1\n"))
    assert (kit.flags.shown, kit.flags.asked) == ([], [])


def test_once_the_item_is_read_a_write_flagging_nothing_makes_none_nor_asks_again(
    kit: Kit, repo: Path
) -> None:
    kit.announced.holding_all = False
    first = '"""Rooms."""\n'
    landed(kit, repo, Overwrite(call="w1", tool="Write", path=repo / ROOMS, text=first))
    kit.flags.read.append(1)

    def plain(call: str) -> Replacement:
        kept = (repo / ROOMS).read_text()
        return Replacement(
            call=call,
            tool="Edit",
            path=repo / ROOMS,
            old=kept,
            new=f"{kept}\nX_{call.upper()} = 1\n",
        )

    landed(kit, repo, plain("e1"))
    # The inbox said no item gathers the file: nothing's made, and the next write doesn't ask again.
    assert len(kit.flags.shown) == 2
    assert len(kit.flags.asked) == 1
    landed(kit, repo, plain("e2"))
    assert len(kit.flags.shown) == 2
    session = read_model(kit.layout.store(repo).session("s1"), Session)
    assert session is not None
    assert session.flagging == {"": []}


def test_a_refresh_taking_out_all_the_item_flagged_says_so(
    kit: Kit, repo: Path
) -> None:
    kit.announced.holding_all = False
    was = (repo / CORE).read_text()
    room = "\n\nclass Room:\n    pass\n"
    landed(kit, repo, replace(repo, "return x\n", "return x\n" + room))
    landed(kit, repo, replace(repo, room, ""))
    made, refreshed = kit.flags.asked
    assert made.flagged.summary == "src/pkg/core.py adds the class `Room`"
    assert (refreshed.joining, refreshed.refreshing) == (1, True)
    assert refreshed.file.after == Text(text=was)
    assert refreshed.flagged.summary == (
        "src/pkg/core.py's whole change flags nothing any more"
    )


def test_a_flagged_write_lands_though_the_operators_inbox_cant_be_reached(
    kit: Kit, repo: Path
) -> None:
    kit.announced.holding_all = False
    kit.flags.refusing = "no host service answers on /run/control.sock"
    write = Overwrite(call="w1", tool="Write", path=repo / ROOMS, text='"""Rooms."""\n')
    decision = before(kit.bench, write, "s1", repo)
    assert decision.outcome == "allow"
    assert decision.told == (
        f"lup couldn't put the flagged write to {repo}/src/pkg/rooms.py before the "
        "operator (no host service answers on /run/control.sock). It landed all "
        "the same: tell the operator."
    )


def test_a_refresh_the_inbox_cant_take_lands_its_write_saying_so(
    kit: Kit, repo: Path
) -> None:
    kit.announced.holding_all = False
    first = '"""Rooms."""\n'
    landed(kit, repo, Overwrite(call="w1", tool="Write", path=repo / ROOMS, text=first))
    kit.flags.refusing = "no host service answers on /run/control.sock"
    edit = Replacement(
        call="e1", tool="Edit", path=repo / ROOMS, old=first, new=first + "X = 1\n"
    )
    decision = landed(kit, repo, edit)
    assert decision.outcome == "allow"
    assert decision.told == (
        f"lup couldn't bring the operator's item on {repo}/src/pkg/rooms.py to your "
        "write (no host service answers on /run/control.sock). It landed all the "
        "same."
    )


def test_a_held_write_declined_never_lands_its_version_saved_the_comment_told(
    kit: Kit, repo: Path
) -> None:
    kit.announced.answering = Response(approved=False, comment="use the other module")
    original = (repo / CORE).read_text()
    write = Overwrite(call="w1", tool="Write", path=repo / CORE, text=original + "\n")
    decision = before(kit.bench, write, "s1", repo)
    saved = repo / ".lup/saved/1/src/pkg/core.py"
    assert decision.outcome == "deny"
    assert decision.reason == (
        "lup refused 1 file. It is unchanged; your version is saved.\n\n"
        f"{repo}/src/pkg/core.py (saved at {saved})\n"
        "  The operator declined it: use the other module"
    )
    assert saved.read_text() == original + "\n"
    assert (repo / CORE).read_text() == original


def test_a_held_write_left_unanswered_is_denied_and_its_hold_stays_open(
    kit: Kit, repo: Path
) -> None:
    kit.announced.answering = None
    write = Overwrite(
        call="w1", tool="Write", path=repo / CORE, text=(repo / CORE).read_text() + "\n"
    )
    decision = before(kit.bench, write, "s1", repo)
    [hold] = kit.announced.holds
    assert decision.outcome == "deny"
    assert "Nobody answered in time" in decision.reason
    kept = Holds(layout=kit.layout.store(repo)).get(hold.key)
    assert kept is not None
    assert kept.abandoned


def test_writes_outside_the_repository_arent_judged(
    kit: Kit, repo: Path, tmp_path: Path
) -> None:
    write = Overwrite(
        call="w1", tool="Write", path=tmp_path / "elsewhere.py", text="x = 1\n"
    )
    assert before(kit.bench, write, "s1", repo).outcome is None


def test_writes_in_another_repository_arent_judged(
    kit: Kit, repo: Path, tmp_path: Path, shell: Shell
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    shell.git(other, "init", "-q")
    write = Overwrite(
        call="w1", tool="Write", path=other / "x.py", text="x = 1  # BAD regex\n"
    )
    assert before(kit.bench, write, "s1", repo).outcome is None


def test_where_a_path_is(repo: Path, linked: Path, bare: Path, tmp_path: Path) -> None:
    common = repo / ".git"
    assert place(repo / CORE) == Place(repository=common, worktree=repo, path=CORE)
    assert place(linked / "src" / "new" / "deep.py") == Place(
        repository=common, worktree=linked, path=Path("src/new/deep.py")
    )
    assert place(common / "config") == Place(
        repository=common, worktree=None, path=Path("config")
    )
    assert place(bare / "tree" / "next.py") == Place(
        repository=bare, worktree=None, path=Path("tree/next.py")
    )
    assert place(tmp_path / "nowhere.py") is None


def test_a_replacement_the_tool_would_refuse_is_allowed(kit: Kit, repo: Path) -> None:
    assert (
        before(kit.bench, replace(repo, "not there", "x"), "s1", repo).outcome
        == "allow"
    )


def test_the_edit_is_judged_against_the_accepted_state(kit: Kit, repo: Path) -> None:
    SessionStarted(session="s1", cwd=repo).apply(kit.bench)
    (repo / "src" / "pkg" / "sneaked.py").write_text(
        '"""Made by a command not yet judged."""\n'
    )
    edit = replace(repo, "Made by", "Written by", path=Path("src/pkg/sneaked.py"))
    before(kit.bench, edit, "s1", repo)
    [hold] = kit.announced.holds
    assert [each.asks for each in hold.files] == [
        ["src/pkg/sneaked.py is a new production file"]
    ]


def test_each_edit_is_logged(kit: Kit, repo: Path) -> None:
    before(
        kit.bench, replace(repo, "return x\n", "return x  # BAD regex\n"), "s1", repo
    )
    [verdict] = VerdictLog(path=kit.layout.verdicts(repo / ".git")).read()
    assert (verdict.tool, verdict.outcome, verdict.session) == ("Edit", "allow", "s1")
    assert verdict.reasons == ["regex"]
    assert (verdict.worktree, verdict.path) == (repo, CORE)
