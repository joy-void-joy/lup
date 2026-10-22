"""A file tool's write, judged before it lands."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

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
    Worktree,
)
from lup_dev.policy.holds import Holds, Response, answer
from lup_dev.policy.verdicts import VerdictLog
from lup_dev.policy.worktrees import Place, place
from lup_dev.private.withheld import Held, Withheld, kept
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from conftest import Dying, Kit, Shell

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
    assert [(pending.call, pending.path) for pending in session.pending] == [
        ("e1", CORE)
    ]


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
    assert decision == Decision(
        outcome="allow",
        reason=(
            f"lup held the write to {repo}/src/pkg/core.py for the operator's "
            "review, and they approved it."
        ),
    )
    assert [each.asks for each in hold.files] == [
        ["the write replaces the whole of src/pkg/core.py"]
    ]
    assert hold.diff.startswith("--- a/src/pkg/core.py\n+++ b/src/pkg/core.py\n")
    assert kit.announced.runtimes == ["asking"]
    assert (hold.call, hold.agent) == ("w1", None)
    session = read_model(kit.layout.store(repo).session("s1"), Session)
    assert session is not None
    assert [(each.call, each.path) for each in session.pending] == [("w1", CORE)]
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
        text=(
            "src/pkg/rooms.py landed, flagged for the operator's review. It holds at "
            "landing: `main` lands once they approve it."
        ),
        summary="src/pkg/rooms.py is a new production file",
        worktree=repo,
        path=ROOMS,
        branch="main",
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
        new=room + "\n\nCAPACITY = 4\n",
    )
    landed(kit, repo, plain)
    _, joined, refreshed = kit.flags.asked
    # The class added asks on its own; joined, the file is judged whole since the item was made: new, which asks nothing of its names.
    assert joined.joining == 1
    assert joined.file.before is None
    assert joined.file.after == Text(text=first + room)
    assert joined.file.reading == Reading(
        role="production", asks=[Asked(name="new-file", taken="flagged")]
    )
    assert joined.flagged.summary == "src/pkg/rooms.py is a new production file"
    # A write flagging nothing of its own refreshes the item, judged whole: it shows the file as it stands.
    kept = (repo / ROOMS).read_text()
    assert (refreshed.joining, refreshed.refreshing, refreshed.call) == (1, True, "e2")
    assert (refreshed.file.before, refreshed.file.after) == (None, Text(text=kept))
    assert refreshed.file.reading == joined.file.reading
    assert refreshed.flagged.summary == joined.flagged.summary
    assert "+CAPACITY = 4" in refreshed.diff
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


def rewrite(repo: Path, call: str = "w1") -> Overwrite:
    """A whole write of the core module, which asks, so it's held."""
    text = (repo / CORE).read_text() + "\n"
    return Overwrite(call=call, tool="Write", path=repo / CORE, text=text)


def ran(kit: Kit, repo: Path, call: str) -> str:
    """A shell call of the session's that writes nothing: what its finish tells."""
    CallStarted(session="s1", cwd=repo, call=call, tool="Bash").apply(kit.bench)
    return CallFinished(session="s1", cwd=repo, call=call).apply(kit.bench).context


def test_a_held_write_holds_its_file_as_a_checkpoints_change_does_while_it_waits(
    kit: Kit, repo: Path
) -> None:
    """So a write landing under it anyway is left to its answer, and no file tool
    writes the file meanwhile, which a retried write would hold a second time."""
    kit.announced.answering = None
    store = Worktree.at(repo, kit.layout).store
    seen: list[tuple[list[Path], Decision]] = []

    def meanwhile() -> None:
        [hold] = kit.announced.holds
        holding = [each.path for each in store.state().holding]
        again = before(kit.bench, rewrite(repo, "w2"), "s1", repo)
        seen.append((holding, again))
        Holds(layout=kit.layout.store(repo)).answer(
            hold.key, Response(approved=True), kit.clock
        )

    kit.clock.on_sleep.append(meanwhile)
    assert before(kit.bench, rewrite(repo), "s1", repo).outcome == "allow"
    [hold] = kit.announced.holds
    assert seen == [
        (
            [CORE],
            Decision(
                outcome="deny",
                reason=(
                    f"lup holds {repo}/src/pkg/core.py for the operator's review "
                    f"(hold {hold.key}), so it isn't written until they answer, "
                    "which reaches the conversation that made the change at its "
                    "next call."
                ),
            ),
        )
    ]
    assert store.state().holding == []


GONE = (
    "lup's host service went away while your call waited for the operator's answer "
    "to the change to"
)


def test_a_held_write_whose_call_died_is_made_once_the_operator_approves(
    kit: Kit, repo: Path, dying: Dying
) -> None:
    """The hook's connection lost with the service, its call didn't run; the
    operator's approval still makes the write, at the next checkpoint in its
    worktree, where the file is as it was."""
    kit.announced.answering = None
    start = SessionStarted(session="s1", cwd=repo)
    start.apply(kit.bench)
    original = (repo / CORE).read_text()
    dying.at_next_wait(kit.clock)
    with pytest.raises(dying.died):
        before(kit.bench, rewrite(repo), "s1", repo)
    assert (repo / CORE).read_text() == original
    [hold] = kit.announced.holds
    answer(kit.layout, hold.key, Response(approved=True, comment="fine"), [], kit.clock)
    assert ran(kit, repo, "c1") == (
        f"{GONE} {repo}/src/pkg/core.py, which they have since approved: fine. "
        "It's in place."
    )
    assert (repo / CORE).read_text() == original + "\n"
    store = Worktree.at(repo, kit.layout).store
    assert store.content(store.accepted(), CORE) == (original + "\n").encode()
    assert len(kit.announced.holds) == 1


def test_a_held_write_whose_call_died_and_was_declined_never_lands(
    kit: Kit, repo: Path, dying: Dying
) -> None:
    kit.announced.answering = None
    SessionStarted(session="s1", cwd=repo).apply(kit.bench)
    original = (repo / CORE).read_text()
    dying.at_next_wait(kit.clock)
    with pytest.raises(dying.died):
        before(kit.bench, rewrite(repo), "s1", repo)
    [hold] = kit.announced.holds
    answer(kit.layout, hold.key, Response(approved=False), [], kit.clock)
    assert ran(kit, repo, "c1") == (
        f"{GONE} {repo}/src/pkg/core.py, which they have since declined. It was put "
        "back, or never landed, and your version saved."
    )
    assert (repo / CORE).read_text() == original
    saved = repo / ".lup/saved/1/src/pkg/core.py"
    assert saved.read_text() == original + "\n"


def test_a_write_landing_under_its_open_hold_is_left_to_the_holds_answer(
    kit: Kit, repo: Path, dying: Dying
) -> None:
    """As a hook that heard no answer let it land before lup told a lost
    connection from one: the checkpoint doesn't judge it afresh, nor hold it a
    second time, and the operator's decline puts it back."""
    kit.announced.answering = None
    SessionStarted(session="s1", cwd=repo).apply(kit.bench)
    original = (repo / CORE).read_text()
    dying.at_next_wait(kit.clock)
    with pytest.raises(dying.died):
        before(kit.bench, rewrite(repo), "s1", repo)
    (repo / CORE).write_text(original + "\n")
    assert ran(kit, repo, "c1") == ""
    assert len(kit.announced.holds) == 1
    store = Worktree.at(repo, kit.layout).store
    assert store.content(store.accepted(), CORE) == original.encode()
    [hold] = kit.announced.holds
    answer(kit.layout, hold.key, Response(approved=False), [], kit.clock)
    ran(kit, repo, "c2")
    assert (repo / CORE).read_text() == original


def test_a_held_write_whose_call_is_interrupted_is_denied_and_told_at_the_next_call(
    kit: Kit, repo: Path, tmp_path: Path
) -> None:
    kit.announced.answering = None
    SessionStarted(session="s1", cwd=repo).apply(kit.bench)
    original = (repo / CORE).read_text()
    mark = tmp_path / "ended"
    bench = kit.bench.model_copy(update={"ended": mark})
    kit.clock.on_sleep.append(mark.touch)
    assert before(bench, rewrite(repo), "s1", repo).outcome == "deny"
    assert (repo / CORE).read_text() == original
    [hold] = kit.announced.holds
    kept = Holds(layout=kit.layout.store(repo)).get(hold.key)
    assert kept is not None
    assert (kept.abandoned, kept.interrupted) == (True, True)
    saved = repo / ".lup/saved/1/src/pkg/core.py"
    assert ran(kit, repo, "c1") == (
        "lup refused 1 file. It is unchanged; your version is saved.\n\n"
        f"{repo}/src/pkg/core.py (saved at {saved})\n"
        "  Its call was interrupted while it waited for the operator; the hold "
        "stays open in their inbox, and their answer reaches you at a later call."
    )
    assert ran(kit, repo, "c2") == ""


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


# A value never published, told with the call before it lands


def listed(kit: Kit, repo: Path) -> None:
    """Keep a made-up list of values never published for `repo`, as a launch would."""
    withheld = Withheld(held=[Held(kind="home", text="/home/op")])
    write_model(kept(kit.layout.module_data("private", repo / ".git")), withheld)


def test_an_edit_carrying_a_private_value_lands_its_value_told_with_the_call(
    kit: Kit, repo: Path
) -> None:
    listed(kit, repo)
    kit.announced.holding_all = False
    edit = replace(repo, "    return x\n", "    return x  # see /home/op\n")
    decision = before(kit.bench, edit, "s1", repo)
    assert decision.outcome == "allow"
    assert decision.told.startswith("Values never published, on the lines changed")
    assert (
        f"  {repo}/src/pkg/core.py:10:21 - private: the operator's home path\n"
        "      steer: write it as `~`, or a path in the repository from its root"
    ) in decision.told
    [verdict] = VerdictLog(path=kit.layout.verdicts(repo / ".git")).read()
    assert (verdict.outcome, verdict.reasons) == ("allow", ["private"])
    assert kit.announced.holds == []
    [flagged] = kit.flags.asked
    assert flagged.flagged.summary == ("src/pkg/core.py:10 - the operator's home path")


def test_a_write_to_a_path_git_ignores_is_told_no_private_value(
    kit: Kit, repo: Path
) -> None:
    listed(kit, repo)
    write = Overwrite(
        call="w1", tool="Write", path=repo / ".lup" / "notes.md", text="/home/op\n"
    )
    decision = before(kit.bench, write, "s1", repo)
    assert decision.outcome == "allow"
    assert "private" not in decision.told


def test_a_judge_finding_no_list_builds_it_as_a_launch_would(
    kit: Kit, repo: Path
) -> None:
    kit.announced.holding_all = False
    kit.facts.home = Path("/home/op")
    edit = replace(repo, "    return x\n", "    return x  # see /home/op\n")
    decision = before(kit.bench, edit, "s1", repo)
    assert "core.py:10:21 - private: the operator's home path" in decision.told
    built = read_model(kept(kit.layout.module_data("private", repo / ".git")), Withheld)
    assert built is not None
    assert Held(kind="home", text="/home/op") in built.held
